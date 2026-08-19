"""
xAI / Grok CLI OAuth 2.0 Token Generation Module.
Automates Device Authorization flow (RFC 8628) and obtains official 'at+jwt' Access Tokens & Refresh Tokens.
"""
import time
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
        proxies = {"http": proxy, "https": proxy} if proxy else None
        resp = requests.post(
            XAI_DEVICE_CODE_URL,
            data=data,
            headers=headers,
            proxies=proxies,
            timeout=15
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Device code request failed ({resp.status_code}): {resp.text}")
        return resp.json()

    def authorize_device_flow(self, page: Page, verification_url: str) -> bool:
        """
        Navigates to verification URL with the active authenticated browser session,
        clicks Step 1 (Continue) and Step 2 (Allow) to approve the OAuth CLI grant.
        """
        logger.info(f"Navigating to OAuth device authorization: {verification_url}")
        # Inject style to hide OneTrust cookie overlays
        try:
            page.add_init_script("""
                window.addEventListener("DOMContentLoaded", () => {
                    const style = document.createElement("style");
                    style.innerHTML = "#onetrust-banner-sdk, .onetrust-pc-dark-filter, #onetrust-consent-sdk { display: none !important; }";
                    document.head.appendChild(style);
                });
            """)
        except Exception:
            pass

        page.goto(verification_url, wait_until="domcontentloaded")
        time.sleep(1.5)

        # Step 1: Click 'Continue' / 'Confirm' on device page
        try:
            btn1 = page.locator('button:has-text("Tiếp tục"), button:has-text("Continue"), button:has-text("Confirm"), button:has-text("继续"), button[type="submit"]').first
            if btn1.count() > 0:
                btn1.click(force=True)
        except Exception as e:
            logger.warning(f"Step 1 click warning: {e}")

        # Wait for navigation to consent or done page
        try:
            page.wait_for_url(lambda url: "consent" in url or "done" in url, timeout=8000)
        except Exception:
            pass

        time.sleep(1.0)

        # Step 2: Click 'Allow' on consent page
        try:
            time.sleep(1.5)
            # Remove any cookie banners
            page.evaluate("""() => {
                document.querySelectorAll('#onetrust-consent-sdk, #onetrust-banner-sdk, .onetrust-pc-dark-filter').forEach(el => el.remove());
            }""")
            
            clicked = page.evaluate("""() => {
                const buttons = Array.from(document.querySelectorAll('button, input[type="submit"]'));
                for (const b of buttons) {
                    const txt = (b.innerText || b.value || '').trim();
                    if ((txt === 'Allow' || txt === 'Cho phép' || txt === 'Approve') && !b.id.includes('accept') && !b.id.includes('reject')) {
                        b.click();
                        return true;
                    }
                }
                // Fallback: look for button inside consent form
                const submitBtn = document.querySelector('form button[type="submit"]');
                if (submitBtn) {
                    submitBtn.click();
                    return true;
                }
                return false;
            }""")
            
            if not clicked:
                # Fallback to Playwright click if needed
                btn2 = page.locator('button[type="submit"]:has-text("Allow"), button[type="submit"]:has-text("Cho phép"), button:has-text("Allow"), button:has-text("Cho phép")').first
                if btn2.count() > 0:
                    btn2.click(force=True)

            try:
                page.wait_for_url(lambda url: "done" in url, timeout=8000)
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
        proxies = {"http": proxy, "https": proxy} if proxy else None

        for attempt in range(max_attempts):
            time.sleep(1.0 if attempt == 0 else 2.0)
            resp = requests.post(
                XAI_TOKEN_URL,
                data=data,
                headers=headers,
                proxies=proxies,
                timeout=15
            )
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
