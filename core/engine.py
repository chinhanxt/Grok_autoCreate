"""
Scrapling and Camoufox Stealth Engine for Grok & x.ai.
Handles Cloudflare bypass, Turnstile solving, and headless browser automation.
"""
import os
import time
import json
import logging
from typing import Optional, Dict, Any, Tuple, List

try:
    from camoufox.sync_api import Camoufox
    USE_CAMOUFOX = True
except ImportError:
    USE_CAMOUFOX = False

try:
    from patchright.sync_api import sync_playwright as sync_patchright
    USE_PATCHRIGHT = True
except ImportError:
    USE_PATCHRIGHT = False

from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser, Response

logger = logging.getLogger("xai_engine")


class StealthEngine:
    """
    Stealth browser automation engine that bypasses Cloudflare and Turnstile.
    """

    def __init__(
        self,
        headless: bool = True,
        proxy: Optional[str] = None,
        timeout_ms: int = 60000
    ):
        self.headless = headless
        self.proxy = proxy
        self.timeout_ms = timeout_ms
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.engine_type = "none"
        self.captured_cookies: Dict[str, str] = {}
        self.captured_rpc_responses: List[Dict[str, Any]] = []

    def _parse_proxy(self) -> Optional[Dict[str, str]]:
        if not self.proxy:
            return None
        # Format: http://user:pass@host:port or socks5://host:port
        server = self.proxy
        username = None
        password = None
        if "@" in server:
            prefix, host_part = server.split("@", 1)
            proto_auth = prefix.split("://", 1)
            proto = proto_auth[0]
            auth = proto_auth[1]
            if ":" in auth:
                username, password = auth.split(":", 1)
            server = f"{proto}://{host_part}"
        proxy_dict = {"server": server}
        if username:
            proxy_dict["username"] = username
        if password:
            proxy_dict["password"] = password
        return proxy_dict

    def start(self) -> Page:
        """
        Launches the stealth browser (Camoufox or Patchright/Playwright with anti-detect flags).
        """
        proxy_cfg = self._parse_proxy()

        # 1. Try Camoufox
        if USE_CAMOUFOX:
            try:
                import asyncio
                try:
                    asyncio.set_event_loop(None)
                except Exception:
                    pass
                self.camoufox_cm = Camoufox(
                    headless=self.headless,
                    proxy=proxy_cfg,
                    humanize=True,
                    geoip=False
                )
                self.browser = self.camoufox_cm.__enter__()
                self.context = self.browser.new_context()
                self.page = self.context.new_page()
                self.page.set_default_timeout(self.timeout_ms)
                self._setup_network_listeners()
                self.engine_type = "camoufox"
                return self.page
            except Exception as e:
                logger.warning(f"Camoufox launch failed ({e}), falling back to Patchright/Playwright...")
                self.browser = None
                self.context = None
                self.page = None

        # 2. Fallback to Patchright or Playwright Stealth
        launcher = sync_patchright if USE_PATCHRIGHT else sync_playwright
        self.playwright = launcher().__enter__()
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars"
        ]
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            proxy=proxy_cfg,
            args=args
        )
        self.context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York"
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        self._setup_network_listeners()
        self.engine_type = "patchright" if USE_PATCHRIGHT else "playwright"
        return self.page

    def _setup_network_listeners(self):
        """
        Listens to network responses to capture authentication cookies and RPC responses.
        Filters out heavy unnecessary resources (images, fonts, media, tracking) to maximize speed.
        """
        import re

        try:
            def _route_filter(route):
                req = route.request
                url = req.url
                # Never block anything from Cloudflare or xAI/Grok domains (needed for Turnstile proof-of-work)
                if any(domain in url for domain in ["cloudflare.com", "x.ai", "grok.com", "auth.x.ai"]):
                    route.continue_()
                    return

                if req.resource_type in ["media"]:
                    route.abort()
                    return
                if any(t in url for t in ["google-analytics", "doubleclick", "datadoghq", "sentry.io", "segment.io", "intercom"]):
                    route.abort()
                    return
                route.continue_()

            self.page.route("**/*", _route_filter)
        except Exception:
            pass

        def on_response(response: Response):
            try:
                url = response.url
                status = response.status

                if "auth.grok.com/set-cookie" in url or "set-cookie" in url:
                    if "q=" in url:
                        q_token = url.split("q=")[1].split("&")[0]
                        self.captured_cookies["sso_redirect_token"] = q_token

                if "x.ai" in url or "grok.com" in url or "grokusercontent.com" in url or "grokipedia.com" in url:
                    headers = {}
                    try:
                        headers = response.all_headers() if hasattr(response, "all_headers") else response.headers
                    except Exception:
                        headers = response.headers

                    # Parse all Set-Cookie headers precisely via headers_array
                    headers_array = []
                    try:
                        if hasattr(response, "headers_array"):
                            headers_array = response.headers_array()
                    except Exception:
                        pass

                    if headers_array:
                        for h in headers_array:
                            if h.get("name", "").lower() == "set-cookie":
                                part = h.get("value", "")
                                if "sso=" in part:
                                    m = re.search(r"sso=([^;,\s]+)", part)
                                    if m:
                                        self.captured_cookies["sso"] = m.group(1)
                                if "sso-rw=" in part:
                                    m = re.search(r"sso-rw=([^;,\s]+)", part)
                                    if m:
                                        self.captured_cookies["sso-rw"] = m.group(1)
                                if "x-userid=" in part:
                                    m = re.search(r"x-userid=([^;,\s]+)", part)
                                    if m:
                                        self.captured_cookies["x-userid"] = m.group(1)

                    # Fallback check on string Set-Cookie
                    set_cookie = headers.get("set-cookie", "")
                    if set_cookie:
                        for part in re.split(r"[\n\r]+", set_cookie):
                            if "sso=" in part:
                                m = re.search(r"sso=([^;,\s]+)", part)
                                if m:
                                    self.captured_cookies["sso"] = m.group(1)
                            if "sso-rw=" in part:
                                m = re.search(r"sso-rw=([^;,\s]+)", part)
                                if m:
                                    self.captured_cookies["sso-rw"] = m.group(1)
                            if "x-userid=" in part:
                                m = re.search(r"x-userid=([^;,\s]+)", part)
                                if m:
                                    self.captured_cookies["x-userid"] = m.group(1)

                    if "auth_mgmt" in url or "VerifyEmailValidationCode" in url or "CreateUserAndSession" in url or "ValidatePassword" in url:
                        self.captured_rpc_responses.append({
                            "url": url,
                            "status": status,
                            "headers": headers
                        })
            except Exception:
                pass

        self.page.on("response", on_response)

    def wait_for_cloudflare(self, timeout_sec: int = 15) -> bool:
        """
        Waits for Cloudflare challenge / interstitial to clear.
        Returns immediately once actual form elements are present.
        """
        start = time.time()
        while time.time() - start < timeout_sec:
            try:
                title = self.page.title()
                if "Just a moment" in title or "Attention Required" in title:
                    time.sleep(0.5)
                    continue

                # If signup buttons or inputs are loaded, Cloudflare is resolved!
                if self.page.locator('button, input, form, [data-testid]').count() > 0:
                    return True
            except Exception:
                time.sleep(0.3)
        return True

    def get_cookies_dict(self) -> Dict[str, str]:
        """
        Retrieves all cookies from the current browser context and network responses.
        """
        res = dict(self.captured_cookies)
        if self.context:
            try:
                cookies = self.context.cookies()
                for c in cookies:
                    res[c["name"]] = c["value"]
            except Exception:
                pass
        self.captured_cookies = res
        return res

    def close(self):
        """
        Closes the browser and cleans up resources.
        """
        try:
            if self.context:
                self.context.close()
            if self.browser:
                if self.engine_type == "camoufox" and hasattr(self, "camoufox_cm"):
                    self.camoufox_cm.__exit__(None, None, None)
                else:
                    self.browser.close()
            if self.playwright:
                self.playwright.__exit__(None, None, None)
        except Exception:
            pass
