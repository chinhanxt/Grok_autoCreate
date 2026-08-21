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
        for nav_try in range(3):
            try:
                self.page.goto(XAI_SIGNUP_URL, wait_until="domcontentloaded", timeout=25000)
                break
            except Exception as e:
                err_str = str(e)
                if "NS_ERROR_NET_RESET" in err_str or "ERR_CONNECTION_RESET" in err_str or "timeout" in err_str.lower():
                    logger.warning(f"Navigation retry {nav_try+1}/3 due to connection reset: {e}")
                    if nav_try == 2:
                        raise RuntimeError(f"Lỗi kết nối mạng/proxy khi tải x.ai ({err_str[:100]})")
                    time.sleep(1.0 + nav_try * 1.0)
                else:
                    raise

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
            time.sleep(0.2)

        if not email_input:
            email_input = self.page.wait_for_selector(email_selector, timeout=8000)

        # 4. Fill Email (Direct fill & safe focus)
        try:
            email_input.click(timeout=1000, force=True)
        except Exception:
            pass
        email_input.fill(email)

        # 5. Click Sign up submit button
        submit_btn = self.page.wait_for_selector(
            'button[type="submit"]:not([disabled]), button:has-text("Sign up"):not([disabled]), button:has-text("Continue"):not([disabled])',
            timeout=8000
        )
        try:
            submit_btn.click(timeout=1500, force=True)
        except Exception:
            submit_btn.evaluate("el => el.click()")
        logger.info(f"Submitted email {email}. Waiting for OTP dispatch...")

        # Check for immediate errors (e.g. invalid email or rate limit)
        try:
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

        # 0. Dismiss any cookie banners / OneTrust overlays if present
        try:
            cookie_accept = self.page.locator('#onetrust-accept-btn-handler, #onetrust-reject-all-handler, button:has-text("Accept all"), button:has-text("Accept")')
            if cookie_accept.count() > 0 and cookie_accept.first.is_visible():
                cookie_accept.first.click(timeout=1000, force=True)
                time.sleep(0.2)
        except Exception:
            pass

        # 1. Wait up to 10s for the real OTP input element to appear
        try:
            self.page.wait_for_selector(
                'input[data-input-otp="true"], input[autocomplete="one-time-code"], input[name="code"], input[placeholder*="code" i], input[maxlength="1"]',
                timeout=10000
            )
        except Exception:
            pass

        time.sleep(0.2)

        # 2. Try input-otp (single input with data-input-otp, name=code, autocomplete=one-time-code)
        otp_single = self.page.locator('input[data-input-otp="true"], input[name="code"], input[autocomplete="one-time-code"], input[placeholder*="code" i]:not(#vendor-search-handler)')
        filled = False

        if otp_single.count() > 0:
            for idx in range(otp_single.count()):
                loc = otp_single.nth(idx)
                try:
                    inp_id = loc.get_attribute("id") or ""
                    inp_name = loc.get_attribute("name") or ""
                    if "vendor" in inp_id or "vendor" in inp_name:
                        continue
                    
                    loc.click(timeout=1500, force=True)
                    loc.fill("")
                    self.page.keyboard.type(code, delay=50)
                    filled = True
                    break
                except Exception:
                    try:
                        loc.fill(code, timeout=3000)
                        filled = True
                        break
                    except Exception:
                        pass

        if not filled:
            # 3. Try 6 separate digit slots
            digit_inputs = self.page.locator('input[maxlength="1"]:not(#vendor-search-handler), input[data-index]:not(#vendor-search-handler), input[type="tel"]:not(#vendor-search-handler)')
            if digit_inputs.count() >= 6:
                try:
                    digit_inputs.first.click(timeout=1500, force=True)
                    self.page.keyboard.type(code, delay=50)
                    filled = True
                except Exception:
                    for i, digit in enumerate(code):
                        try:
                            digit_inputs.nth(i).fill(digit, timeout=2000)
                        except Exception:
                            pass
                    filled = True

        if not filled:
            # 4. Safe visible fallback (strictly excluding vendor-search-handler and search inputs)
            visible_inputs = self.page.locator('input:visible:not(#vendor-search-handler):not([name="vendor-search-handler"]):not([aria-label*="search" i]):not([type="hidden"])')
            for idx in range(visible_inputs.count()):
                loc = visible_inputs.nth(idx)
                try:
                    inp_id = loc.get_attribute("id") or ""
                    inp_name = loc.get_attribute("name") or ""
                    if "vendor" in inp_id or "vendor" in inp_name:
                        continue
                    loc.click(timeout=1500, force=True)
                    self.page.keyboard.type(code, delay=50)
                    filled = True
                    break
                except Exception:
                    pass

        # 5. Backup JS event dispatch
        try:
            self.page.evaluate("""(code) => {
                const el = document.querySelector('input[data-input-otp="true"], input[name="code"], input[autocomplete="one-time-code"], input[maxlength="1"]');
                if (el && (!el.value || el.value.length < 6)) {
                    el.focus();
                    el.value = code;
                    el.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
                }
            }""", code)
        except Exception:
            pass

        time.sleep(0.3)

        # 6. Click Confirm email button if present
        confirm_btn = self.page.locator('button:has-text("Confirm email"), button:has-text("Verify"), button:has-text("Continue"), button[type="submit"]:not(#onetrust-accept-btn-handler)').first
        if confirm_btn.count() > 0 and confirm_btn.is_visible():
            try:
                confirm_btn.click(timeout=2000, force=True)
            except Exception:
                confirm_btn.evaluate("el => el.click()")

        # 7. Adaptive wait for next step (Profile page)
        try:
            self.page.wait_for_selector(
                'input[data-testid="givenName"], input[name="givenName"], input[name="password"], input[type="password"]',
                timeout=12000
            )
            # If Profile inputs are visible, OTP was accepted!
            return True
        except Exception:
            pass

        # 8. Check for genuine OTP error alerts
        try:
            error_loc = self.page.locator('[data-slot="error"], .text-destructive, [role="alert"]')
            if error_loc.count() > 0 and error_loc.first.is_visible():
                err_text = error_loc.first.inner_text().strip().lower()
                if "invalid" in err_text or "expired" in err_text or "incorrect" in err_text:
                    raise ValueError(f"Mã OTP không hợp lệ hoặc đã hết hạn ({err_text})!")
        except ValueError:
            raise
        except Exception:
            pass

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
        try:
            self.page.wait_for_selector(
                'input[data-testid="givenName"], input[name="givenName"], input[name="password"], input[type="password"]',
                timeout=12000
            )
        except Exception:
            pass
        time.sleep(0.1)

        # 2. First Name (givenName)
        fn_loc = self.page.locator('input[data-testid="givenName"], input[name="givenName"], input[autocomplete="given-name"], input[placeholder*="First" i]').first
        if fn_loc.count() > 0:
            try:
                fn_loc.click(timeout=1000, force=True)
                fn_loc.fill("")
                self.page.keyboard.type(first_name, delay=25)
            except Exception:
                fn_loc.fill(first_name)

        # 3. Last Name (familyName)
        ln_loc = self.page.locator('input[data-testid="familyName"], input[name="familyName"], input[autocomplete="family-name"], input[placeholder*="Last" i]').first
        if ln_loc.count() > 0:
            try:
                ln_loc.click(timeout=1000, force=True)
                ln_loc.fill("")
                self.page.keyboard.type(last_name, delay=25)
            except Exception:
                ln_loc.fill(last_name)

        # 4. Password
        pwd_loc = self.page.locator('input[data-testid="password"], input[name="password"], input[type="password"]').first
        if pwd_loc.count() > 0:
            try:
                pwd_loc.click(timeout=1000, force=True)
                pwd_loc.fill("")
                self.page.keyboard.type(password, delay=25)
            except Exception:
                pwd_loc.fill(password)

        # Dispatch synthetic blur/change events to ensure React validation enables submit button
        try:
            self.page.evaluate("""() => {
                document.querySelectorAll('input').forEach(el => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                });
            }""")
        except Exception:
            pass

        # 5. Active loop: Solve Cloudflare Turnstile, submit registration, and capture SSO cookies
        logger.info("Solving Cloudflare Turnstile & submitting final registration...")
        sso_cookie = ""
        sso_rw_cookie = ""
        user_id = ""
        session_id = ""

        start_wait = time.time()
        while time.time() - start_wait < 25:
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
                time.sleep(0.3)
                break

            # A. Click Turnstile checkbox if present in iframe or main DOM
            try:
                for frame in self.page.frames:
                    if "challenges.cloudflare.com" in frame.url:
                        box = frame.locator('input[type="checkbox"], #challenge-stage, .ctp-checkbox-label').first
                        if box.count() > 0 and box.is_visible():
                            box.click(timeout=1000, force=True)
                
                # Check main page turnstile
                main_ts = self.page.locator('.cf-turnstile, iframe[src*="cloudflare"], #challenge-stage').first
                if main_ts.count() > 0 and main_ts.is_visible():
                    main_ts.click(timeout=1000, force=True)
            except Exception:
                pass

            # B. Trigger submit button or press Enter
            try:
                submit_btn = self.page.locator('button[type="submit"], button:has-text("Complete sign up"), button:has-text("Create account"), button:has-text("Sign up"), button:has-text("Tiếp tục"), button:has-text("Continue")').first
                if submit_btn.count() > 0 and submit_btn.is_visible():
                    is_disabled = submit_btn.get_attribute("disabled") is not None
                    if not is_disabled:
                        submit_btn.click(timeout=1500, force=True)
                    else:
                        if pwd_loc and pwd_loc.count() > 0:
                            pwd_loc.press("Enter")
                else:
                    self.page.evaluate("""() => {
                        const btn = document.querySelector('button[type="submit"], form button');
                        if (btn && !btn.disabled) btn.click();
                    }""")
            except Exception:
                pass

            time.sleep(0.5)

        # Final cookie refresh to ensure all redirect cookies (sso, sso-rw, x-userid) are captured
        cookies_dict = self.engine.get_cookies_dict()
        if not sso_cookie:
            sso_cookie = cookies_dict.get("sso", "") or cookies_dict.get("sso_redirect_token", "")
        if not sso_rw_cookie:
            sso_rw_cookie = cookies_dict.get("sso-rw", "")
        if not user_id:
            user_id = cookies_dict.get("x-userid", "")

        # Also pull all cookies across domains from Playwright context
        if self.page and self.page.context:
            try:
                for c in self.page.context.cookies():
                    c_name = c.get("name", "").lower()
                    c_val = c.get("value", "")
                    if not sso_cookie and c_name in ("sso", "sso_redirect_token", "__session", "token", "auth_token", "jwt"):
                        sso_cookie = c_val
                    if not sso_rw_cookie and c_name in ("sso-rw", "sso_rw"):
                        sso_rw_cookie = c_val
                    if not user_id and c_name in ("x-userid", "user_id", "userid"):
                        user_id = c_val
                    # Any JWT string
                    if not sso_cookie and c_val.startswith("eyJ") and len(c_val) > 40:
                        sso_cookie = c_val
            except Exception:
                pass

        # Check localStorage for auth tokens
        if not sso_cookie:
            try:
                storage_data = self.page.evaluate("""() => {
                    const data = {};
                    for (let i = 0; i < localStorage.length; i++) {
                        const k = localStorage.key(i);
                        data[k] = localStorage.getItem(k);
                    }
                    return data;
                }""")
                for k, v in (storage_data or {}).items():
                    if "sso" in k.lower() or "token" in k.lower() or "auth" in k.lower() or "jwt" in k.lower():
                        if isinstance(v, str) and (v.startswith("eyJ") or len(v) > 30):
                            sso_cookie = v
                            break
            except Exception:
                pass

        # If session is still missing, perform instant fallback sign-in recovery
        if not sso_cookie and not user_id and self.email and self.password:
            logger.info("Attempting automatic sign-in recovery for newly created account...")
            try:
                self.page.goto("https://accounts.x.ai/sign-in?redirect=grok-com", wait_until="domcontentloaded", timeout=15000)
                time.sleep(1.0)

                # Click 'Sign in with email' if present
                try:
                    sign_in_email_btn = self.page.locator('button:has-text("Sign in with email"), a:has-text("Sign in with email")').first
                    if sign_in_email_btn.count() > 0 and sign_in_email_btn.is_visible():
                        sign_in_email_btn.click(timeout=1500, force=True)
                        time.sleep(0.5)
                except Exception:
                    pass

                em_inp = self.page.locator('input[type="email"], input[name="email"], input[data-testid="email"]').first
                if em_inp.count() > 0:
                    em_inp.click(timeout=1000, force=True)
                    em_inp.fill(self.email)
                    
                    # Click Next or press Enter
                    next_btn = self.page.locator('button[type="submit"], button:has-text("Next"), button:has-text("Continue"), button:has-text("Tiếp tục")').first
                    if next_btn.count() > 0 and next_btn.is_visible():
                        next_btn.click(timeout=1500, force=True)
                    else:
                        self.page.keyboard.press("Enter")
                    time.sleep(1.5)

                pw_inp = self.page.locator('input[type="password"], input[name="password"], input[data-testid="password"]').first
                if pw_inp.count() > 0:
                    pw_inp.click(timeout=1000, force=True)
                    pw_inp.fill(self.password)

                    # Click Log in or press Enter
                    log_btn = self.page.locator('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in"), button:has-text("Đăng nhập")').first
                    if log_btn.count() > 0 and log_btn.is_visible():
                        log_btn.click(timeout=1500, force=True)
                    else:
                        self.page.keyboard.press("Enter")
                    time.sleep(2.5)

                    # Check cookies again
                    for c in self.page.context.cookies():
                        if not sso_cookie and c["name"] == "sso":
                            sso_cookie = c["value"]
                        if not sso_rw_cookie and c["name"] == "sso-rw":
                            sso_rw_cookie = c["value"]
                        if not user_id and c["name"] == "x-userid":
                            user_id = c["value"]
            except Exception as e:
                logger.debug(f"Auto-recovery sign-in notice: {e}")

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
        time.sleep(1.0)
        try:
            from core.oauth import OAuthTokenManager
            oauth_mgr = OAuthTokenManager()
            tokens = oauth_mgr.mint_tokens_for_page(self.page, proxy=self.engine.proxy)
            access_token = tokens.get("access_token", "")
            refresh_token = tokens.get("refresh_token", "")
            logger.info("Successfully minted official xAI OAuth 2.0 CLI Tokens!")
        except Exception as e:
            logger.warning(f"Auto OAuth token minting notice ({e}). Falling back to SSO session.")

        # Normalize tokens if sso_cookie was extracted as access_token or vice-versa
        if not sso_cookie and access_token:
            sso_cookie = access_token
        if not access_token and sso_cookie and sso_cookie.startswith("eyJ"):
            access_token = sso_cookie

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
