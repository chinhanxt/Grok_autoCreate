"""
Account Revival Module for xAI / Grok Accounts.
Resurrects expired or dead tokens using OAuth Refresh Flow, SSO Session Browser Minting,
and Password Recovery, backed by automated grok-4.6 health-checks.
"""
import time
import logging
import threading
import requests
from typing import Optional, Dict, Any, Tuple, List, Callable
from concurrent.futures import ThreadPoolExecutor

from core.engine import StealthEngine
from core.oauth import OAuthTokenManager, XAI_TOKEN_URL, XAI_OAUTH_CLIENT_ID
from core.healthcheck import verify_grok_cli_health, GROK_USER_AGENT
from core.exporter import AccountRecord, save_account, load_accounts
from config import DEFAULT_JSON_OUTPUT, DEFAULT_TXT_OUTPUT

logger = logging.getLogger("xai_reviver")


def revive_single_account(
    account: Dict[str, Any],
    proxy: Optional[str] = None,
    headless: bool = True
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Attempts all layers of revival for a single account:
    1. Quick Health Check: If already 200 OK -> skip browser!
    2. OAuth Refresh Token Grant: Fast API-based refresh.
    3. Browser SSO Cookie Minting: Headless browser injected with sso & sso-rw.
    4. Password Sign-in Recovery: If SSO expired, logs in with email+password and mints tokens.

    Returns (is_alive, message, updated_account_dict).
    """
    email = account.get("email", "")
    password = account.get("password", "")
    access_token = account.get("access_token", "")
    refresh_token = account.get("refresh_token", "")
    sso_cookie = account.get("sso_cookie", "")
    sso_rw_cookie = account.get("sso_rw_cookie", sso_cookie)
    user_id = account.get("user_id", "")

    # Layer 1: Check if already alive
    if access_token:
        ok, code, msg = verify_grok_cli_health(access_token, proxy=proxy)
        if ok:
            account["status"] = "active"
            extra = account.get("extra", {}) or {}
            extra["health_verified"] = True
            account["extra"] = extra
            return True, "Already alive (HTTP 200 OK)", account

    # Layer 2: Fast OAuth Refresh Token Flow (No browser required)
    if refresh_token and refresh_token != access_token:
        try:
            headers = {
                "User-Agent": GROK_USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json"
            }
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": XAI_OAUTH_CLIENT_ID
            }
            proxies = {"http": proxy, "https": proxy} if proxy else None
            resp = requests.post(XAI_TOKEN_URL, data=data, headers=headers, proxies=proxies, timeout=12)
            if resp.status_code == 200:
                res_json = resp.json()
                new_acc = res_json.get("access_token")
                new_ref = res_json.get("refresh_token", refresh_token)
                if new_acc:
                    ok, code, msg = verify_grok_cli_health(new_acc, proxy=proxy)
                    if ok:
                        account["access_token"] = new_acc
                        account["refresh_token"] = new_ref
                        account["status"] = "active"
                        extra = account.get("extra", {}) or {}
                        extra["health_verified"] = True
                        account["extra"] = extra
                        return True, "Revived via OAuth Refresh Token (HTTP 200 OK)", account
        except Exception as e:
            logger.debug(f"Refresh token error for {email}: {e}")

    # Layer 3: Headless Browser SSO Cookie Minting
    if sso_cookie:
        engine = None
        try:
            oauth_mgr = OAuthTokenManager()
            engine = StealthEngine(headless=headless, proxy=proxy)
            page = engine.start()

            cookies = [
                {"name": "sso", "value": sso_cookie, "domain": ".x.ai", "path": "/"},
                {"name": "sso-rw", "value": sso_rw_cookie, "domain": ".x.ai", "path": "/"},
                {"name": "sso", "value": sso_cookie, "domain": "accounts.x.ai", "path": "/"},
                {"name": "sso-rw", "value": sso_rw_cookie, "domain": "accounts.x.ai", "path": "/"},
                {"name": "sso", "value": sso_cookie, "domain": "auth.x.ai", "path": "/"},
                {"name": "sso-rw", "value": sso_rw_cookie, "domain": "auth.x.ai", "path": "/"},
            ]
            page.context.add_cookies(cookies)

            tokens = oauth_mgr.mint_tokens_for_page(page, proxy=proxy)
            new_acc = tokens.get("access_token")
            new_ref = tokens.get("refresh_token")
            
            if new_acc:
                ok, code, msg = verify_grok_cli_health(new_acc, proxy=proxy)
                if ok:
                    account["access_token"] = new_acc
                    account["refresh_token"] = new_ref
                    account["status"] = "active"
                    extra = account.get("extra", {}) or {}
                    extra["health_verified"] = True
                    account["extra"] = extra
                    return True, "Revived via SSO Browser Minting (HTTP 200 OK)", account
        except Exception as e:
            logger.debug(f"SSO minting error for {email}: {e}")
        finally:
            if engine:
                try:
                    engine.close()
                except Exception:
                    pass

    # Layer 4: Full Sign-in Recovery with Email + Password
    if email and password:
        engine = None
        try:
            oauth_mgr = OAuthTokenManager()
            engine = StealthEngine(headless=headless, proxy=proxy)
            page = engine.start()
            page.goto("https://accounts.x.ai/sign-in?redirect=grok-com", wait_until="domcontentloaded", timeout=20000)
            time.sleep(1.0)

            # Click Sign in with email
            try:
                sign_in_email_btn = page.locator('button:has-text("Sign in with email"), a:has-text("Sign in with email")').first
                if sign_in_email_btn.count() > 0 and sign_in_email_btn.is_visible():
                    sign_in_email_btn.click(timeout=2000, force=True)
                    time.sleep(0.5)
            except Exception:
                pass

            em_inp = page.locator('input[type="email"], input[name="email"], input[data-testid="email"]').first
            if em_inp.count() > 0:
                em_inp.click(timeout=1000, force=True)
                em_inp.fill(email)
                next_btn = page.locator('button[type="submit"], button:has-text("Next"), button:has-text("Continue")').first
                if next_btn.count() > 0 and next_btn.is_visible():
                    next_btn.click(timeout=2000, force=True)
                else:
                    page.keyboard.press("Enter")
                time.sleep(1.5)

            pw_inp = page.locator('input[type="password"], input[name="password"], input[data-testid="password"]').first
            if pw_inp.count() > 0:
                pw_inp.click(timeout=1000, force=True)
                pw_inp.fill(password)
                log_btn = page.locator('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")').first
                if log_btn.count() > 0 and log_btn.is_visible():
                    log_btn.click(timeout=2000, force=True)
                else:
                    page.keyboard.press("Enter")
                time.sleep(3.0)

                # Pull fresh cookies
                for c in page.context.cookies():
                    if c["name"] == "sso":
                        sso_cookie = c["value"]
                        account["sso_cookie"] = sso_cookie
                    elif c["name"] == "sso-rw":
                        sso_rw_cookie = c["value"]
                        account["sso_rw_cookie"] = sso_rw_cookie

                # Mint fresh OAuth tokens
                tokens = oauth_mgr.mint_tokens_for_page(page, proxy=proxy)
                new_acc = tokens.get("access_token")
                new_ref = tokens.get("refresh_token")
                if new_acc:
                    ok, code, msg = verify_grok_cli_health(new_acc, proxy=proxy)
                    if ok:
                        account["access_token"] = new_acc
                        account["refresh_token"] = new_ref
                        account["status"] = "active"
                        extra = account.get("extra", {}) or {}
                        extra["health_verified"] = True
                        account["extra"] = extra
                        return True, "Revived via Password Login & OAuth (HTTP 200 OK)", account
        except Exception as e:
            logger.debug(f"Password recovery error for {email}: {e}")
        finally:
            if engine:
                try:
                    engine.close()
                except Exception:
                    pass

    account["status"] = "dead"
    extra = account.get("extra", {}) or {}
    extra["health_verified"] = False
    account["extra"] = extra
    return False, "Failed to revive: All recovery layers exhausted", account


class AccountReviveManager:
    """
    Thread-safe batch manager to revive accounts with realtime progress and logging.
    """

    def __init__(self, json_path: str = DEFAULT_JSON_OUTPUT, txt_path: str = DEFAULT_TXT_OUTPUT):
        self.json_path = json_path
        self.txt_path = txt_path
        self.is_running = False
        self.stop_requested = False
        self.total = 0
        self.processed = 0
        self.revived_count = 0
        self.failed_count = 0
        self.current_email = ""
        self.logs: List[str] = []
        self._lock = threading.Lock()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "is_running": self.is_running,
                "total": self.total,
                "processed": self.processed,
                "revived_count": self.revived_count,
                "failed_count": self.failed_count,
                "current_email": self.current_email,
                "logs": list(self.logs[-50:])
            }

    def stop(self):
        with self._lock:
            self.stop_requested = True
            self.logs.append("⚠ Yêu cầu dừng tiến trình hồi sinh tài khoản.")

    def run_revival(
        self,
        max_workers: int = 4,
        proxy: Optional[str] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self.stop_requested = False
            self.processed = 0
            self.revived_count = 0
            self.failed_count = 0
            self.logs.clear()

        try:
            accounts = load_accounts(self.json_path)
            self.total = len(accounts)
            self.logs.append(f"🚀 Bắt đầu quét & hồi sinh {self.total} tài khoản với {max_workers} luồng...")

            def _worker(item):
                idx, acc = item
                if self.stop_requested:
                    return None

                email = acc.get("email", "")
                with self._lock:
                    self.current_email = email

                ok, msg, updated_acc = revive_single_account(acc, proxy=proxy)
                
                with self._lock:
                    self.processed += 1
                    if ok:
                        self.revived_count += 1
                        log_line = f"✔ [{self.processed}/{self.total}] {email} -> {msg}"
                    else:
                        self.failed_count += 1
                        log_line = f"✘ [{self.processed}/{self.total}] {email} -> {msg}"
                    self.logs.append(log_line)

                    # Save updated account record
                    rec = AccountRecord(
                        email=updated_acc["email"],
                        password=updated_acc.get("password", "taikhoanAI123"),
                        first_name=updated_acc.get("first_name", ""),
                        last_name=updated_acc.get("last_name", ""),
                        user_id=updated_acc.get("user_id", ""),
                        session_id=updated_acc.get("session_id", ""),
                        sso_cookie=updated_acc.get("sso_cookie", ""),
                        sso_rw_cookie=updated_acc.get("sso_rw_cookie", ""),
                        access_token=updated_acc.get("access_token", ""),
                        refresh_token=updated_acc.get("refresh_token", ""),
                        status=updated_acc.get("status", "active"),
                        extra=updated_acc.get("extra", {})
                    )
                    save_account(rec, json_path=self.json_path, txt_path=self.txt_path)

                if on_progress:
                    on_progress(self.get_status())
                return ok

            items = list(enumerate(accounts))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                list(pool.map(_worker, items))

            with self._lock:
                from core.exporter import save_oauth_router_accounts
                router_count = save_oauth_router_accounts("grok_router_accounts.json", json_path=self.json_path, only_healthy=True)
                self.logs.append(f"🏁 HOÀN TẤT HỒI SINH! Đã làm sống lại {self.revived_count}/{self.total} tài khoản.")
                self.logs.append(f"🎉 Đã xuất {router_count} tài khoản sống 100% ra file 'grok_router_accounts.json'.")

        finally:
            with self._lock:
                self.is_running = False
