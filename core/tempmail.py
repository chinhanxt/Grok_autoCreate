"""
TempMail integration module using web2.temp-mail.org (with curl_cffi Chrome impersonation)
Faithfully restored and optimized from /home/chinhan/Downloads/temp_mail_gui.py.
"""
import time
import json
import logging
import re
from typing import Optional, Tuple, Dict, Any

try:
    from curl_cffi import requests
    USE_CFFI = True
except ImportError:
    import requests
    USE_CFFI = False

logger = logging.getLogger("xai_tempmail")

BASE_URL = "https://web2.temp-mail.org"

RATE_LIMIT_MAX_ATTEMPTS = 4  # initial request + 3 retries, then raise
NETWORK_MAX_ATTEMPTS = 2  # initial request + 1 retry, then raise
RATE_LIMIT_DEFAULT_DELAY = 30.0
NETWORK_RETRY_DELAY = 0.5


class TempMailRateLimitError(RuntimeError):
    """Raised when temp-mail.org keeps returning HTTP 429 after all retries."""

DEFAULT_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.7",
    "origin": "https://temp-mail.org",
    "priority": "u=1, i",
    "referer": "https://temp-mail.org/",
    "sec-ch-ua": '"Not=A?Brand";v="99", "Brave";v="151", "Chromium";v="151"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "sec-gpc": "1",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
}


def extract_otp_from_text(text: str) -> Optional[str]:
    """
    Extracts a 6-digit OTP code from subject/body text (supporting 123-456, 123 456, or 123456).
    """
    if not text:
        return None
    # 1. Pattern like "SpaceXAI confirmation code: 349-759" or "349 759"
    m = re.search(r"\b(\d{3})[-\s](\d{3})\b", text)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    # 2. Standard 6-digit continuous sequence
    m2 = re.search(r"\b(\d{6})\b", text)
    if m2:
        return m2.group(1)
    return None


def _retry_after_delay(resp) -> float:
    """Seconds to wait from the Retry-After header, or 30.0 if absent/unparseable."""
    headers = getattr(resp, "headers", None) or {}
    items = getattr(headers, "items", None)
    if items is None:
        return RATE_LIMIT_DEFAULT_DELAY
    for key, value in items():
        if key.lower() == "retry-after":
            try:
                return max(0.0, float(str(value).strip()))
            except (TypeError, ValueError):
                break
    return RATE_LIMIT_DEFAULT_DELAY


class TempMailClient:
    """
    Temp-Mail.org client matching /home/chinhan/Downloads/temp_mail_gui.py.
    """

    def __init__(self, proxy: Optional[str] = None):
        self.headers = dict(DEFAULT_HEADERS)
        self.token: Optional[str] = None
        self.mailbox: Optional[str] = None
        self.email: Optional[str] = None
        self.proxy = proxy
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.provider = "temp-mail.org"

    def set_token(self, token: str):
        if not token.startswith("Bearer "):
            token = f"Bearer {token}"
        self.token = token
        self.headers["authorization"] = self.token

    def _request(self, method: str, url: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        last_err = None

        for attempt in range(RATE_LIMIT_MAX_ATTEMPTS):
            try:
                if USE_CFFI:
                    resp = requests.request(
                        method,
                        url,
                        headers=self.headers,
                        json=data if data else None,
                        proxies=self.proxies,
                        impersonate="chrome",
                        timeout=20,
                    )
                else:
                    resp = requests.request(
                        method,
                        url,
                        headers=self.headers,
                        json=data if data else None,
                        proxies=self.proxies,
                        timeout=20,
                    )
            except Exception as e:
                last_err = str(e)
                if attempt + 1 >= NETWORK_MAX_ATTEMPTS:
                    break
                time.sleep(NETWORK_RETRY_DELAY)
                continue

            if resp.status_code == 429:
                last_err = f"HTTP 429: {resp.text[:200]}"
                if attempt + 1 >= RATE_LIMIT_MAX_ATTEMPTS:
                    raise TempMailRateLimitError(
                        f"Temp-Mail rate limited (HTTP 429: {resp.text[:200]})"
                    )
                time.sleep(_retry_after_delay(resp))
                continue

            try:
                res_json = resp.json()
            except Exception:
                last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if attempt + 1 >= NETWORK_MAX_ATTEMPTS:
                    break
                time.sleep(NETWORK_RETRY_DELAY)
                continue

            return res_json

        raise RuntimeError(f"Lỗi kết nối Temp-Mail ({last_err})")

    def create_mailbox(self) -> Dict[str, Any]:
        res = self._request("POST", f"{BASE_URL}/mailbox")
        if "token" in res:
            self.set_token(res["token"])
            self.mailbox = res.get("mailbox")
            self.email = self.mailbox
            logger.info(f"Created temp-mail.org inbox: {self.email}")
            return res
        raise ValueError(f"Failed to create mailbox: {res}")

    def create_inbox(self) -> Tuple[str, str]:
        res = self.create_mailbox()
        return self.email, self.token

    def get_messages(self) -> Dict[str, Any]:
        return self._request("GET", f"{BASE_URL}/messages")

    def get_message_detail(self, message_id: str) -> Dict[str, Any]:
        return self._request("GET", f"{BASE_URL}/messages/{message_id}")

    def fetch_otp_code(
        self,
        timeout_sec: int = 120,
        poll_interval: float = 3.0,
        page: Optional[Any] = None
    ) -> Optional[str]:
        """
        Polls web2.temp-mail.org/messages for OTP code matching temp_mail_gui logic.
        """
        if not self.email or not self.token:
            raise ValueError("Mailbox not created. Call create_inbox() first.")

        start_time = time.time()
        resend_attempted = False

        while time.time() - start_time < timeout_sec:
            elapsed = time.time() - start_time

            # Auto-click Resend after 30s if needed
            if page and elapsed >= 30 and not resend_attempted:
                try:
                    resend_btn = page.locator('button:has-text("Resend"), button:has-text("Gửi lại"), a:has-text("Resend"), a:has-text("Gửi lại"), [data-testid*="resend"]').first
                    if resend_btn.count() > 0 and resend_btn.is_visible():
                        logger.info("Clicking Resend code on x.ai...")
                        resend_btn.click(force=True)
                        resend_attempted = True
                except Exception:
                    pass

            try:
                data = self.get_messages()
                messages = data.get("messages", [])
                for msg in messages:
                    subject = msg.get("subject", "")
                    otp = extract_otp_from_text(subject)
                    if otp:
                        return otp

                    msg_id = msg.get("_id")
                    if msg_id:
                        detail = self.get_message_detail(msg_id)
                        body_text = detail.get("bodyText") or detail.get("bodyHtml") or ""
                        otp = extract_otp_from_text(body_text)
                        if otp:
                            return otp
            except Exception as e:
                logger.debug(f"Polling messages warning: {e}")

            time.sleep(poll_interval)

        return None
