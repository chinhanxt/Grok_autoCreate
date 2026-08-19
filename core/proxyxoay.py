"""
ProxyXoay Residential Rotating Proxy Module (proxyxoay.shop).
Handles API key queries, automatic IP rotation, whitelist configuration, and cooldown timers.
"""
import os
import re
import time
import json
import logging
import requests
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("xai_proxyxoay")

CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".proxyxoay_cache.json")


class ProxyXoayManager:
    """
    Manager for proxyxoay.shop rotating residential proxies with persistent caching and cooldown management.
    """

    BASE_URL = "https://proxyxoay.shop/api/get.php"

    def __init__(
        self,
        api_key: str,
        nhamang: str = "random",
        tinhthanh: str = "0",
        whitelist: Optional[str] = None
    ):
        self.api_key = (api_key or "").strip()
        self.nhamang = nhamang or "random"
        self.tinhthanh = str(tinhthanh if tinhthanh is not None else "0")
        self.whitelist = (whitelist or "").strip()

        self.last_proxy_http: Optional[str] = None
        self.last_proxy_socks5: Optional[str] = None
        self.last_ip: Optional[str] = None
        self.last_data: Dict[str, Any] = {}
        self.last_rotate_timestamp: float = 0

        # Load from disk cache
        self._load_cache()

    def _load_cache(self):
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("api_key") == self.api_key and data.get("proxy_http"):
                        self.last_proxy_http = data.get("proxy_http")
                        self.last_proxy_socks5 = data.get("proxy_socks5")
                        self.last_ip = data.get("ip")
                        self.last_data = data.get("details", {})
        except Exception:
            pass

    def _save_cache(self):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "api_key": self.api_key,
                    "proxy_http": self.last_proxy_http,
                    "proxy_socks5": self.last_proxy_socks5,
                    "ip": self.last_ip,
                    "details": self.last_data,
                    "timestamp": time.time()
                }, f)
        except Exception:
            pass

    @staticmethod
    def get_public_ip(timeout_sec: int = 5) -> str:
        """
        Auto-detects current public IP for whitelisting.
        """
        for url in ["https://api.ipify.org", "https://icanhazip.com", "https://ifconfig.me/ip"]:
            try:
                resp = requests.get(url, timeout=timeout_sec)
                if resp.status_code == 200 and resp.text.strip():
                    return resp.text.strip()
            except Exception:
                pass
        return ""

    def get_proxy(self, force_rotate: bool = False, timeout_sec: int = 10) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Fetches or rotates the proxy from proxyxoay.shop.
        Returns (is_success, proxy_url, response_data).
        """
        if not self.api_key:
            return False, None, {"error": "Chưa nhập API Key ProxyXoay"}

        wl = self.whitelist
        if not wl:
            wl = self.get_public_ip()
            if wl:
                self.whitelist = wl

        params = {
            "key": self.api_key,
            "nhamang": self.nhamang,
            "tinhthanh": self.tinhthanh,
            "whitelist": wl
        }

        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=timeout_sec)
            data = resp.json()
        except Exception as e:
            logger.error(f"ProxyXoay request failed: {e}")
            if self.last_proxy_http:
                return True, self.last_proxy_http, {
                    "reused": True,
                    "ip": self.last_ip,
                    "Nha Mang": self.last_data.get("Nha Mang"),
                    "Vi Tri": self.last_data.get("Vi Tri"),
                    "message": "Đang dùng proxy lưu trong cache",
                    "error": str(e)
                }
            return False, None, {"error": f"Lỗi kết nối API ProxyXoay: {e}"}

        status = data.get("status")
        message = data.get("message", "")

        # Status 100: Successfully rotated / retrieved active proxy
        if status == 100:
            raw_http = data.get("proxyhttp", "").strip().rstrip(":")
            raw_socks = data.get("proxysocks5", "").strip().rstrip(":")

            if raw_http:
                self.last_proxy_http = f"http://{raw_http}"
            if raw_socks:
                self.last_proxy_socks5 = f"socks5://{raw_socks}"

            self.last_ip = data.get("ip") or (raw_http.split(":")[0] if raw_http else None)
            self.last_data = data
            self.last_rotate_timestamp = time.time()
            self._save_cache()
            return True, self.last_proxy_http, data

        # Status 101 / 102: Cooldown (Proxy is still alive on port, wait before rotating to next IP)
        elif status in (101, 102):
            wait_sec = 0
            m = re.search(r"(\d+)s", message)
            if m:
                wait_sec = int(m.group(1))

            data["wait_seconds"] = wait_sec

            # If we have an active proxy from current session or disk cache, reuse it!
            if self.last_proxy_http:
                data["ip"] = self.last_ip or self.last_data.get("ip")
                data["Nha Mang"] = self.last_data.get("Nha Mang")
                data["Vi Tri"] = self.last_data.get("Vi Tri")
                return True, self.last_proxy_http, {
                    "reused": True,
                    "status": status,
                    "message": message,
                    "wait_seconds": wait_sec,
                    "proxyhttp": self.last_proxy_http,
                    "ip": self.last_ip,
                    "Nha Mang": self.last_data.get("Nha Mang"),
                    "Vi Tri": self.last_data.get("Vi Tri"),
                    "details": self.last_data
                }

            return False, None, data

        # Other error statuses
        else:
            return False, None, data
