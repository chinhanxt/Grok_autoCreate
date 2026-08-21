"""
xAI / Grok CLI OAuth 2.0 Token Generation Module.
Automates Device Authorization flow (RFC 8628) and obtains official 'at+jwt' Access Tokens & Refresh Tokens.
"""
import time
import threading
import requests
import logging
from typing import Optional, Dict, Any, Tuple
from playwright.sync_api import Page

logger = logging.getLogger("xai_oauth")

XAI_OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_OAUTH_SCOPE = (
    "openid profile email offline_access grok-cli:access api:access "
    "conversations:read conversations:write workspaces:read workspaces:write"
)
XAI_DEVICE_CODE_URL = "https://auth.x.ai/oauth2/device/code"
XAI_TOKEN_URL = "https://auth.x.ai/oauth2/token"


class OAuthTokenManager:
    """
    Manages automated OAuth token acquisition for xAI / Grok accounts.
    """

    def __init__(self, client_id: str = XAI_OAUTH_CLIENT_ID, scope: str = XAI_OAUTH_SCOPE):
        self.client_id = client_id
        self.scope = scope

    def request_device_code(self, proxy: Optional[str] = None) -> Dict[str, Any]:
        """
        Initiates device code grant flow with auth.x.ai.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        data = {
            "client_id": self.client_id,
            "scope": self.scope
        }

        # Try proxy first if provided, fallback to direct
        proxy_candidates = [proxy, None] if proxy else [None]
        last_exc = None
        for p in proxy_candidates:
            try:
                proxies = {"http": p, "https": p} if p else None
                resp = requests.post(
                    XAI_DEVICE_CODE_URL,
                    data=data,
                    headers=headers,
                    proxies=proxies,
                    timeout=15
                )
                if resp.status_code == 200:
                    return resp.json()
                elif p is None:
                    raise RuntimeError(f"Device code request failed ({resp.status_code}): {resp.text}")
            except Exception as e:
                last_exc = e
                continue

        raise RuntimeError(f"Device code request failed: {last_exc}")

    def authorize_device_flow(self, page: Page, verification_url: str) -> bool:
        """
        Navigates to verification URL with the active authenticated browser session,
        clicks Step 1 (Continue) and Step 2 (Allow) to approve the OAuth CLI grant.
        """
        logger.info(f"Navigating to OAuth device authorization: {verification_url}")
        # Explicitly propagate SSO cookies to auth.x.ai and accounts.x.ai to prevent sign-in redirect
        try:
            current_cookies = page.context.cookies()
            sso_val = next((c["value"] for c in current_cookies if c["name"] == "sso"), None)
            sso_rw_val = next((c["value"] for c in current_cookies if c["name"] == "sso-rw"), None)
            if sso_val:
                extra_cookies = []
                for domain in [".x.ai", "accounts.x.ai", "auth.x.ai"]:
                    extra_cookies.append({"name": "sso", "value": sso_val, "domain": domain, "path": "/"})
                    if sso_rw_val:
                        extra_cookies.append({"name": "sso-rw", "value": sso_rw_val, "domain": domain, "path": "/"})
                page.context.add_cookies(extra_cookies)
        except Exception:
            pass

        try:
            page.goto(verification_url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass
        time.sleep(0.5)

        # Step 1: Wait for Continue button to become enabled and click
        try:
            btn1 = page.wait_for_selector(
                'button:has-text("Continue"), button:has-text("Tiếp tục")',
                timeout=10000
            )
            if btn1:
                btn1.click(force=True)
        except Exception as e:
            logger.warning(f"Step 1 click warning: {e}")

        # Wait for navigation to consent / verify / done page
        try:
            page.wait_for_url(lambda url: "consent" in url or "verify" in url or "done" in url, timeout=8000)
        except Exception:
            pass

        time.sleep(0.3)

        # Step 2: Strictly click Confirm / Allow / Authorize (Never Deny or Cookie banner)
        try:
            btn2 = page.wait_for_selector(
                'button:has-text("Allow"):not(#accept-recommended-btn-handler), button:has-text("Confirm"), button:has-text("Authorize"), button:has-text("Cho phép"), button:has-text("Xác nhận")',
                timeout=10000
            )
            if btn2:
                btn2.click(force=True)
            
            try:
                page.wait_for_url(lambda url: "done" in url, timeout=6000)
            except Exception:
                pass
            return True
        except Exception as e:
            logger.warning(f"Step 2 click warning: {e}")
            return False

    def exchange_tokens(self, device_code: str, proxy: Optional[str] = None, max_attempts: int = 12) -> Dict[str, Any]:
        """
        Exchanges device_code for official OAuth access_token (at+jwt) and refresh_token.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": self.client_id
        }

        for attempt in range(max_attempts):
            time.sleep(1.0 if attempt == 0 else 2.0)
            proxy_candidates = [proxy, None] if proxy else [None]
            resp = None
            for p in proxy_candidates:
                try:
                    proxies = {"http": p, "https": p} if p else None
                    resp = requests.post(
                        XAI_TOKEN_URL,
                        data=data,
                        headers=headers,
                        proxies=proxies,
                        timeout=15
                    )
                    break
                except Exception:
                    continue

            if resp is None:
                continue

            if resp.status_code == 200:
                return resp.json()

            res_json = {}
            try:
                res_json = resp.json()
            except Exception:
                pass

            err = res_json.get("error", "")
            if err == "authorization_pending":
                continue
            elif err == "slow_down":
                time.sleep(3.0)
                continue
            else:
                raise RuntimeError(f"Token exchange failed ({resp.status_code}): {resp.text}")

        raise TimeoutError("OAuth token polling timed out waiting for authorization.")

    def mint_tokens_for_page(self, page: Page, proxy: Optional[str] = None) -> Dict[str, Any]:
        """
        Performs full end-to-end OAuth minting using the currently open browser page.
        Returns dict containing access_token, refresh_token, expires_in, id_token.
        """
        dev_info = self.request_device_code(proxy=proxy)
        verify_url = dev_info.get("verification_uri_complete") or dev_info.get("verification_uri")
        device_code = dev_info["device_code"]

        self.authorize_device_flow(page, verify_url)
        tokens = self.exchange_tokens(device_code=device_code, proxy=proxy)
        return tokens


_auto_oauth_daemon_running = False
_in_progress_emails = set()
_in_progress_lock = threading.Lock()

def start_auto_oauth_daemon(interval_sec: float = 3.0, max_workers: int = 2):
    """
    Starts a permanent background daemon that continuously watches accounts.json.
    Whenever any new or existing account without an OAuth token is detected,
    it automatically launches a background task to mint and save the OAuth token for that account.
    """
    global _auto_oauth_daemon_running
    if _auto_oauth_daemon_running:
        return
    _auto_oauth_daemon_running = True

    def _daemon_worker():
        from core.engine import StealthEngine
        from core.exporter import load_accounts, save_account, AccountRecord
        from config import DEFAULT_JSON_OUTPUT, DEFAULT_TXT_OUTPUT, DEFAULT_PASSWORD
        from concurrent.futures import ThreadPoolExecutor

        oauth_mgr = OAuthTokenManager()

        def _mint_one(acc):
            email = acc.get("email")
            sso = acc.get("sso_cookie")
            sso_rw = acc.get("sso_rw_cookie", sso)
            if not email or not sso:
                return

            with _in_progress_lock:
                if email in _in_progress_emails:
                    return
                _in_progress_emails.add(email)

            logger.info(f"⚡ [Auto-OAuth] Phát hiện tài khoản chưa có token: {email}. Bắt đầu tự động lấy token...")
            engine = StealthEngine(headless=True)
            try:
                page = engine.start()
                cookies = [
                    {"name": "sso", "value": sso, "domain": ".x.ai", "path": "/"},
                    {"name": "sso-rw", "value": sso_rw, "domain": ".x.ai", "path": "/"},
                    {"name": "sso", "value": sso, "domain": "accounts.x.ai", "path": "/"},
                    {"name": "sso-rw", "value": sso_rw, "domain": "accounts.x.ai", "path": "/"},
                    {"name": "sso", "value": sso, "domain": "auth.x.ai", "path": "/"},
                    {"name": "sso-rw", "value": sso_rw, "domain": "auth.x.ai", "path": "/"},
                ]
                page.context.add_cookies(cookies)
                tokens = oauth_mgr.mint_tokens_for_page(page)
                
                rec = AccountRecord(
                    email=email,
                    password=acc.get("password", DEFAULT_PASSWORD),
                    first_name=acc.get("first_name", ""),
                    last_name=acc.get("last_name", ""),
                    user_id=acc.get("user_id", "") or tokens.get("id_token", ""),
                    session_id=acc.get("session_id", ""),
                    sso_cookie=sso,
                    sso_rw_cookie=sso_rw,
                    access_token=tokens["access_token"],
                    refresh_token=tokens["refresh_token"]
                )
                save_account(rec, DEFAULT_JSON_OUTPUT, DEFAULT_TXT_OUTPUT)
                logger.info(f"🎉 [Auto-OAuth] ĐÃ TỰ ĐỘNG CẤP OAUTH CHO {email} THÀNH CÔNG!")
            except Exception as e:
                logger.warning(f"✘ [Auto-OAuth] Lỗi lấy token cho {email}: {e}")
            finally:
                engine.close()
                with _in_progress_lock:
                    _in_progress_emails.discard(email)

        while True:
            try:
                accounts = load_accounts(DEFAULT_JSON_OUTPUT)
                pending = [
                    acc for acc in accounts
                    if not (acc.get("access_token") and acc.get("access_token").startswith("eyJ"))
                    and acc.get("sso_cookie")
                    and acc.get("email") not in _in_progress_emails
                ]
                if pending:
                    with ThreadPoolExecutor(max_workers=max_workers) as pool:
                        list(pool.map(_mint_one, pending[:max_workers * 2]))
            except Exception as e:
                pass
            time.sleep(interval_sec)

    t = threading.Thread(target=_daemon_worker, daemon=True, name="AutoOAuthDaemon")
    t.start()
    logger.info("🚀 Đã kích hoạt [HỆ THỐNG TỰ ĐỘNG LẤY TOKEN OAUTH CHO MỌI TÀI KHOẢN MỚI]")
