"""
Auth controller for Grok & x.ai registration flow.
"""
import time
import base64
import json
import logging
import requests
from typing import Optional, Dict, Any, Tuple

from config import XAI_SIGNUP_URL, GROK_SESSION_URL, DEFAULT_TOS_VERSION
from core.engine import StealthEngine
from core.exporter import AccountRecord

logger = logging.getLogger("xai_auth")


def extract_user_id_from_jwt(jwt_token: str) -> str:
    """
    Extracts user ID from JWT payload without secret verification.
    """
    try:
        parts = jwt_token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1]
            payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8"))
            return data.get("sub") or data.get("userId") or data.get("user_id") or data.get("id") or ""
    except Exception:
        pass
    return ""


class AccountCreator:
    """
    Manages the end-to-end account registration flow.
    """

    def __init__(self, engine: StealthEngine):
        self.engine = engine
        self.page = None
        self.email: Optional[str] = None
        self.password: Optional[str] = None
        self.first_name: Optional[str] = None
        self.last_name: Optional[str] = None

    def start_signup(self, email: str) -> bool:
        """
        Navigates to signup page, clicks 'Sign up with email', fills email and dispatches OTP.
        """
        self.email = email
        self.page = self.engine.start()

        logger.info(f"Navigating to {XAI_SIGNUP_URL}...")
        self.page.goto(XAI_SIGNUP_URL, wait_until="domcontentloaded")

        # 1. Solve Cloudflare Turnstile if present
        self.engine.wait_for_cloudflare(timeout_sec=15)

        # 2. Check for Region Lock / Unsupported Country on x.ai
        try:
            content = self.page.content().lower()
            if "not available in your region" in content or "not available in your country" in content:
                raise RuntimeError("IP Tor hiện tại nằm trong khu vực chưa hỗ trợ của x.ai (Region Blocked).")
        except Exception as e:
            if "Region Blocked" in str(e):
                raise e

        # 3. Cleanly dismiss all OneTrust cookie banners & overlays
        try:
            self.page.evaluate('''() => {
                const els = document.querySelectorAll('#onetrust-banner-sdk, .onetrust-pc-dark-filter, #onetrust-consent-sdk, #onetrust-style');
                els.forEach(el => el.remove());
                const style = document.createElement('style');
                style.innerHTML = '#onetrust-banner-sdk, .onetrust-pc-dark-filter, #onetrust-consent-sdk { display: none !important; }';
                document.head.appendChild(style);
            }''')
        except Exception:
            pass

        # 3. Transition to email input (Active polling loop for Tor and varied connection speeds)
        email_selector = 'input[data-testid="email"], input[name="email"], input[type="email"]'
        email_input = None
        start_time = time.time()

        while time.time() - start_time < 30:
            try:
                # If email input is already visible and ready, proceed immediately
                loc = self.page.locator(email_selector)
                if loc.count() > 0 and loc.first.is_visible():
                    email_input = loc.first
                    break

                # Otherwise find and click 'Sign up with email'
                signup_btn = self.page.locator('button:has-text("Sign up with email"), a:has-text("Sign up with email")').first
                if signup_btn.count() > 0 and signup_btn.is_visible():
                    logger.info("Clicking 'Sign up with email'...")
                    try:
                        signup_btn.click(timeout=2000)
                    except Exception:
                        signup_btn.evaluate("el => el.click()")
            except Exception:
                pass
            time.sleep(0.8)

        if not email_input:
            email_input = self.page.wait_for_selector(email_selector, timeout=8000)

        # 4. Fill Email (Direct fill & safe focus)
        try:
            email_input.click(timeout=1500, force=True)
        except Exception:
            pass
        email_input.fill(email)
        time.sleep(0.3)

        # 5. Click Sign up submit button
        submit_btn = self.page.wait_for_selector(
            'button[type="submit"]:not([disabled]), button:has-text("Sign up"):not([disabled]), button:has-text("Continue"):not([disabled])',
            timeout=8000
        )
        try:
            submit_btn.click(timeout=2000, force=True)
        except Exception:
            submit_btn.evaluate("el => el.click()")
        logger.info(f"Submitted email {email}. Waiting for OTP dispatch...")
        time.sleep(0.8)

        # Check for immediate errors (e.g. invalid email or rate limit)
        try:
            time.sleep(1.0)
            error_loc = self.page.locator('[data-slot="error"], .text-destructive, [role="alert"]')
            if error_loc.count() > 0 and error_loc.first.is_visible():
                err_msg = error_loc.first.inner_text().strip()
                if err_msg:
                    logger.warning(f"Error returned by x.ai during email submission: {err_msg}")
                    raise ValueError(f"x.ai phản hồi lỗi: {err_msg}")
        except ValueError:
            raise
        except Exception:
            pass

        return True

    def submit_otp(self, code: str) -> bool:
        """
        Inputs the 6-digit OTP code received in email and clicks Confirm.
        """
        code = str(code).strip().replace("-", "").replace(" ", "")
        logger.info(f"Submitting 6-digit OTP: {code}")
        time.sleep(0.8)

        # 1. Target single OTP input (data-input-otp or name=code) or 6 separate inputs
        otp_single = self.page.locator('input[data-input-otp="true"], input[name="code"], input[autocomplete="one-time-code"]')
        if otp_single.count() > 0 and otp_single.first.is_visible():
            try:
                otp_single.first.click(timeout=1500, force=True)
            except Exception:
                pass
            otp_single.first.fill(code)
        else:
            digit_inputs = self.page.locator('input[maxlength="1"], input[data-index], input[type="tel"]')
            if digit_inputs.count() == 6:
                for i, digit in enumerate(code):
                    digit_inputs.nth(i).fill(digit)
                    time.sleep(0.05)
            else:
                fallback_inp = self.page.locator('input[placeholder*="code" i], input[type="text"]').first
                try:
                    fallback_inp.click(timeout=1500, force=True)
                except Exception:
                    pass
                fallback_inp.fill(code)

        time.sleep(1.2)

        # 2. Click Confirm email button if present
        confirm_btn = self.page.locator('button:has-text("Confirm email"), button:has-text("Verify"), button[type="submit"]').first
        if confirm_btn.count() > 0 and confirm_btn.is_visible():
            confirm_btn.evaluate("el => el.click()")

        time.sleep(3)

        # 3. Check for OTP error message
        body_text = self.page.locator('body').inner_text()
        if "code is invalid" in body_text or "code has expired" in body_text or "incorrect" in body_text:
            raise ValueError("Mã OTP không hợp lệ hoặc đã hết hạn!")

        return True

    def complete_registration(
        self,
        first_name: str,
        last_name: str,
        password: str
    ) -> AccountRecord:
        """
        Fills user profile details (givenName, familyName, password), waits for Turnstile, and extracts session.
        """
        self.first_name = first_name
        self.last_name = last_name
        self.password = password

        logger.info(f"Filling profile: {first_name} {last_name}...")
        
        # 1. Wait for profile inputs: givenName or password
        self.page.wait_for_selector(
            'input[data-testid="givenName"], input[name="givenName"], input[name="password"], input[type="password"]',
            timeout=20000
        )
        time.sleep(1)

        # 2. First Name (givenName)
        fn_loc = self.page.locator('input[data-testid="givenName"], input[name="givenName"], input[autocomplete="given-name"], input[placeholder*="First" i]')
        if fn_loc.count() > 0:
            fn = fn_loc.first
            try:
                fn.click(timeout=1500, force=True)
            except Exception:
                pass
            fn.fill(first_name)
            time.sleep(0.2)

        # 3. Last Name (familyName)
        ln_loc = self.page.locator('input[data-testid="familyName"], input[name="familyName"], input[autocomplete="family-name"], input[placeholder*="Last" i]')
        if ln_loc.count() > 0:
            ln = ln_loc.first
            try:
                ln.click(timeout=1500, force=True)
            except Exception:
                pass
            ln.fill(last_name)
            time.sleep(0.2)

        # 4. Password
        pwd_loc = self.page.locator('input[data-testid="password"], input[name="password"], input[type="password"]')
        if pwd_loc.count() > 0:
            pwd = pwd_loc.first
            try:
                pwd.click(timeout=1500, force=True)
            except Exception:
                pass
            pwd.fill(password)
            time.sleep(0.2)

        # 5. Active loop: Solve Cloudflare Turnstile, submit registration, and capture SSO cookies
        logger.info("Solving Cloudflare Turnstile & submitting final registration...")
        sso_cookie = ""
        sso_rw_cookie = ""
        user_id = ""
        session_id = ""

        start_wait = time.time()
        while time.time() - start_wait < 45:
            cookies_dict = self.engine.get_cookies_dict()
            sso_cookie = cookies_dict.get("sso", "") or cookies_dict.get("sso_redirect_token", "")
            sso_rw_cookie = cookies_dict.get("sso-rw", "")
            user_id = cookies_dict.get("x-userid", "")

            # Also check page context cookies directly
            if not sso_cookie and self.page and self.page.context:
                try:
                    for c in self.page.context.cookies():
                        if c["name"] == "sso":
                            sso_cookie = c["value"]
                        elif c["name"] == "sso-rw":
                            sso_rw_cookie = c["value"]
                        elif c["name"] == "x-userid":
                            user_id = c["value"]
                except Exception:
                    pass

            if sso_cookie or user_id or "grok.com" in self.page.url or "accounts.x.ai/account" in self.page.url:
                time.sleep(1)
                break

            # A. Click Turnstile checkbox if present in iframe
            for frame in self.page.frames:
                if "challenges.cloudflare.com" in frame.url:
                    try:
                        box = frame.locator('input[type="checkbox"], #challenge-stage, .ctp-checkbox-label').first
                        if box.count() > 0 and box.is_visible():
                            box.click(timeout=1000)
                    except Exception:
                        pass

            # B. Trigger submit button or press Enter
            try:
                submit_btn = self.page.locator('button[type="submit"], button:has-text("Complete sign up"), button:has-text("Create account"), button:has-text("Sign up"), button:has-text("Tiếp tục")').first
                if submit_btn.count() > 0 and submit_btn.is_visible():
                    is_disabled = submit_btn.get_attribute("disabled") is not None
                    if not is_disabled:
                        submit_btn.click(timeout=1500)
                    else:
                        if pwd_loc and pwd_loc.count() > 0:
                            pwd_loc.first.press("Enter")
            except Exception:
                pass

            time.sleep(1.0)

        # Final cookie refresh to ensure all redirect cookies (sso, sso-rw, x-userid) are captured
        cookies_dict = self.engine.get_cookies_dict()
        if not sso_cookie:
            sso_cookie = cookies_dict.get("sso", "") or cookies_dict.get("sso_redirect_token", "")
        if not sso_rw_cookie:
            sso_rw_cookie = cookies_dict.get("sso-rw", "")
        if not user_id:
            user_id = cookies_dict.get("x-userid", "")

        # Extract user_id from JWT if not present
        if sso_cookie and not user_id:
            user_id = extract_user_id_from_jwt(sso_cookie)

        # Verify session with Grok API
        session_data = self.verify_grok_session(cookies_dict)
        if session_data:
            if not user_id:
                user_id = session_data.get("session", {}).get("userId", "")
            session_id = session_data.get("session", {}).get("sessionId", "")

        # Mint official xAI / Grok CLI OAuth 2.0 Tokens (at+jwt)
        access_token = ""
        refresh_token = ""
        try:
            from core.oauth import OAuthTokenManager
            oauth_mgr = OAuthTokenManager()
            tokens = oauth_mgr.mint_tokens_for_page(self.page, proxy=self.engine.proxy)
            access_token = tokens.get("access_token", "")
            refresh_token = tokens.get("refresh_token", "")
            logger.info("Successfully minted official xAI OAuth 2.0 CLI Tokens!")
        except Exception as e:
            logger.warning(f"Auto OAuth token minting notice ({e}). Falling back to SSO session.")

        record = AccountRecord(
            email=self.email or "",
            password=self.password or "",
            first_name=self.first_name or "",
            last_name=self.last_name or "",
            user_id=user_id,
            session_id=session_id,
            sso_cookie=sso_cookie,
            sso_rw_cookie=sso_rw_cookie,
            access_token=access_token,
            refresh_token=refresh_token,
            status="active" if (sso_cookie or user_id or access_token or "grok.com" in self.page.url) else "created",
            extra={"session_details": session_data} if session_data else {}
        )

        return record

    def verify_grok_session(self, cookies: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """
        Verifies session with grok.com/api/auth/session using requests.
        """
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": "https://grok.com/"
        }
        proxies = {"http": self.engine.proxy, "https": self.engine.proxy} if self.engine.proxy else None
        try:
            resp = requests.get(
                GROK_SESSION_URL,
                headers=headers,
                cookies=cookies,
                proxies=proxies,
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "authenticated":
                    return data
        except Exception as e:
            logger.debug(f"Error verifying Grok session: {e}")
        return None
