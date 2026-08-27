"""
TempMail integration module using web2.temp-mail.org (with curl_cffi Chrome impersonation)
Faithfully restored and optimized from /home/chinhan/Downloads/temp_mail_gui.py.
"""
import time
import json
import logging
import random
import re
from typing import Optional, Tuple, Dict, Any

try:
    from curl_cffi import requests
    USE_CFFI = True
except ImportError:
    import requests
    USE_CFFI = False

logger = logging.getLogger("xai_tempmail")

import threading
_inbox_creation_lock = threading.Lock()

BASE_URL = "https://web2.temp-mail.org"

RATE_LIMIT_MAX_ATTEMPTS = 6  # initial request + 5 retries
NETWORK_MAX_ATTEMPTS = 3  # initial request + 2 retries
RATE_LIMIT_DEFAULT_DELAY = 1.5
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
    """Seconds to wait from the Retry-After header, or default delay if absent/unparseable."""
    headers = getattr(resp, "headers", None) or {}
    items = getattr(headers, "items", None)
    if items is None:
        return RATE_LIMIT_DEFAULT_DELAY
    for key, value in items():
        if key.lower() == "retry-after":
            try:
                val = float(str(value).strip())
                return max(0.5, min(val, 5.0))
            except (TypeError, ValueError):
                break
    return RATE_LIMIT_DEFAULT_DELAY


class TempMailClient:
    """
    Temp-Mail.org client matching /home/chinhan/Downloads/temp_mail_gui.py.
    """

    def __init__(self, proxy: Optional[str] = None, max_retry_delay: Optional[float] = None):
        self.headers = dict(DEFAULT_HEADERS)
        self.token: Optional[str] = None
        self.mailbox: Optional[str] = None
        self.email: Optional[str] = None
        self.raw_proxy = proxy
        self.proxy = self._format_isolated_proxy(proxy)
        self.proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        self.max_retry_delay = max_retry_delay
        self.provider = "temp-mail.org"

    def _format_isolated_proxy(self, proxy: Optional[str]) -> Optional[str]:
        """Injects SOCKS5 stream isolation credentials if connecting via Tor."""
        if not proxy:
            return None
        import random
        if ("127.0.0.1:9050" in proxy or "localhost:9050" in proxy) and "@" not in proxy:
            rnd = random.randint(10000, 99999)
            return f"socks5://tor_w_{rnd}:pwd_{rnd}@127.0.0.1:9050"
        return proxy

    def rotate_tor_stream(self):
        """Rotates the Tor circuit by generating a new stream isolation user ID."""
        import random
        if self.raw_proxy and ("127.0.0.1:9050" in self.raw_proxy or "localhost:9050" in self.raw_proxy):
            rnd = random.randint(10000, 99999)
            self.proxy = f"socks5://tor_w_{rnd}:pwd_{rnd}@127.0.0.1:9050"
            self.proxies = {"http": self.proxy, "https": self.proxy}

    def set_proxy(self, proxy: Optional[str]):
        """Updates the proxy configuration for requests."""
        self.raw_proxy = proxy
        self.proxy = self._format_isolated_proxy(proxy)
        self.proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None

    def set_token(self, token: str, email: Optional[str] = None):
        if not token.startswith("Bearer "):
            token = f"Bearer {token}"
        self.token = token
        self.headers["authorization"] = self.token
        if email:
            self.email = email

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

            if resp.status_code in (403, 429):
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                # If using Tor, switch to a fresh exit circuit immediately for this stream
                self.rotate_tor_stream()
                
                delay = 0.5
                if resp.status_code == 429:
                    delay = _retry_after_delay(resp) + (attempt * 0.3)
                if attempt + 1 >= RATE_LIMIT_MAX_ATTEMPTS:
                    raise TempMailRateLimitError(
                        f"Temp-Mail rate limited/blocked (HTTP {resp.status_code}: {resp.text[:200]})"
                    )
                logger.warning(f"Temp-Mail HTTP {resp.status_code}. Xoay Tor IP & thử lại trong {delay:.1f}s...")
                time.sleep(delay)
                continue

            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if attempt + 1 >= NETWORK_MAX_ATTEMPTS:
                    break
                time.sleep(NETWORK_RETRY_DELAY)
                continue

            try:
                return resp.json()
            except Exception as e:
                last_err = f"JSON decode error: {e}"
                if attempt + 1 >= NETWORK_MAX_ATTEMPTS:
                    break
                time.sleep(NETWORK_RETRY_DELAY)
                continue

        raise RuntimeError(f"Lỗi kết nối Temp-Mail ({last_err})")

    def _create_mail_tm_inbox(self) -> Tuple[str, str]:
        """Fallback to api.mail.tm when temp-mail.org is rate limited."""
        import string
        import requests as std_requests

        for tm_attempt in range(3):
            try:
                # 1. Get active domain
                dom_resp = std_requests.get("https://api.mail.tm/domains", proxies=self.proxies, timeout=10)
                dom_data = dom_resp.json()
                members = dom_data.get("hydra:member", [])
                if not members:
                    raise RuntimeError("Không tìm thấy domain khả dụng trên Mail.tm")
                domain = random.choice(members)["domain"]

                # 2. Create account
                rand_user = "xai_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
                email = f"{rand_user}@{domain}"
                pwd = "PasswordAI123!"

                acc_resp = std_requests.post(
                    "https://api.mail.tm/accounts",
                    json={"address": email, "password": pwd},
                    proxies=self.proxies,
                    timeout=10
                )
                if acc_resp.status_code not in (200, 201):
                    time.sleep(0.3)
                    continue

                time.sleep(0.2)

                # 3. Get JWT token
                tok_resp = std_requests.post(
                    "https://api.mail.tm/token",
                    json={"address": email, "password": pwd},
                    proxies=self.proxies,
                    timeout=10
                )
                tok_data = tok_resp.json()
                token = tok_data.get("token")
                if not token:
                    time.sleep(0.3)
                    continue

                self.provider = "mail.tm"
                self.email = email
                self.set_token(token, email=email)
                logger.info(f"Created fallback mail.tm inbox: {self.email}")
                return self.email, self.token
            except Exception as e:
                if tm_attempt == 2:
                    logger.error(f"Mail.tm fallback error: {e}")
                    raise
                time.sleep(0.5)

    def create_mailbox(self) -> Dict[str, Any]:
        """
        Creates a new mailbox on web2.temp-mail.org and returns the raw response dictionary.
        """
        data = self._request("POST", f"{BASE_URL}/mailbox")
        self.token = data.get("token")
        if not self.token:
            raise RuntimeError(f"Invalid mailbox response: {data}")
        self.provider = "temp-mail.org"
        self.set_token(self.token)
        self.mailbox = data.get("mailbox")
        self.email = self.mailbox
        logger.info(f"Created temp-mail.org inbox: {self.email}")
        return data

    def create_inbox(self) -> Tuple[str, str]:
        """
        Creates a new mailbox on web2.temp-mail.org or falls back seamlessly to mail.tm.
        """
        try:
            self.create_mailbox()
            return self.email, self.token
        except Exception as e:
            logger.warning(f"Temp-mail.org rate limited/error ({e}). Seamlessly switching to Mail.tm...")
            return self._create_mail_tm_inbox()

    def get_messages(self) -> Dict[str, Any]:
        """
        Fetches all received emails for the current mailbox token.
        """
        if not self.token:
            raise ValueError("No mailbox token found. Call create_inbox() or set_token() first.")

        if self.provider == "mail.tm":
            import requests as std_requests
            headers = {"Authorization": self.token}
            try:
                resp = std_requests.get("https://api.mail.tm/messages", headers=headers, timeout=10)
                if resp.status_code == 200:
                    members = resp.json().get("hydra:member", [])
                    return {"messages": [{"_id": m["id"], "subject": m.get("subject", ""), "intro": m.get("intro", "")} for m in members]}
            except Exception:
                pass
            return {"messages": []}

        return self._request("GET", f"{BASE_URL}/messages")

    def get_message_detail(self, message_id: str) -> Dict[str, Any]:
        """
        Fetches details / body text for a specific email message.
        """
        if not self.token:
            raise ValueError("No mailbox token found. Call create_inbox() or set_token() first.")

        if self.provider == "mail.tm":
            import requests as std_requests
            headers = {"Authorization": self.token}
            try:
                resp = std_requests.get(f"https://api.mail.tm/messages/{message_id}", headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    html_content = data.get("html", "")
                    if isinstance(html_content, list):
                        html_content = html_content[0] if html_content else ""
                    return {
                        "bodyText": (data.get("text", "") or "") + " " + (data.get("intro", "") or ""),
                        "bodyHtml": html_content
                    }
            except Exception:
                pass
            return {}

        return self._request("GET", f"{BASE_URL}/messages/{message_id}")

    def fetch_otp_code(
        self,
        timeout_sec: int = 120,
        poll_interval: float = 0.8,
        page: Optional[Any] = None
    ) -> Optional[str]:
        """
        Polls web2.temp-mail.org/messages for OTP code matching temp_mail_gui logic.
        """
        if not self.token:
            raise ValueError("Mailbox token not set. Call set_token() or create_inbox() first.")

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
