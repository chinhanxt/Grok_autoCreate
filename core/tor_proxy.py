"""
Tor Proxy Manager Module.
Integrates Tor SOCKS5 proxy and Tor Control Port (NEWNYM) to rotate IP addresses across multiple locations.
"""
import time
import socket
import logging
import requests
from typing import Optional, Dict, Any, Tuple

try:
    from stem import Signal
    from stem.control import Controller
    USE_STEM = True
except ImportError:
    USE_STEM = False

logger = logging.getLogger("xai_tor")


class TorProxyManager:
    """
    Manages Tor SOCKS5 proxy connection, IP geolocation checking, and automatic circuit/IP rotation.
    """

    def __init__(
        self,
        socks_host: str = "127.0.0.1",
        socks_port: int = 9050,
        control_host: str = "127.0.0.1",
        control_port: int = 9051,
        control_password: Optional[str] = None
    ):
        self.socks_host = socks_host
        self.socks_port = socks_port
        self.control_host = control_host
        self.control_port = control_port
        self.control_password = control_password
        self.last_ip: Optional[str] = None

    @property
    def proxy_url(self) -> str:
        """Returns standard SOCKS5 proxy URL format."""
        return f"socks5://{self.socks_host}:{self.socks_port}"

    def get_isolated_proxy_url(self, stream_id: Optional[str] = None) -> str:
        """
        Returns SOCKS5 proxy URL with stream isolation credentials.
        Tor uses SOCKS authentication credentials (IsolateSOCKSAuth) to route
        each stream through an independent circuit and exit node IP.
        """
        if stream_id:
            return f"socks5://{stream_id}:tor@{self.socks_host}:{self.socks_port}"
        return self.proxy_url

    def get_proxy(
        self,
        force_rotate: bool = False,
        timeout_sec: int = 10,
        stream_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Retrieves a proxy URL, optionally with Tor stream isolation or circuit renewal.
        Matches the ProxyManager interface expected by MailboxPool.
        """
        if stream_id:
            url = self.get_isolated_proxy_url(stream_id)
            return True, url, {"proxy": url, "stream_id": stream_id, "type": "tor_isolated"}
        
        if force_rotate:
            ok, new_ip = self.renew_ip(wait_sec=2.0)
            return ok, self.proxy_url, {"ip": new_ip, "proxy": self.proxy_url, "type": "tor"}

        return True, self.proxy_url, {"ip": self.last_ip, "proxy": self.proxy_url, "type": "tor"}

    def rotate_to_new_ip(self, timeout_sec: int = 30) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Rotates to a new Tor circuit / exit IP (matches MailboxPool rotation interface).
        Generates a fresh isolated stream ID for instant rotation without blocking cooldowns.
        """
        import random
        stream_id = f"tor_rot_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        url = self.get_isolated_proxy_url(stream_id)
        return True, url, {"proxy": url, "stream_id": stream_id, "type": "tor_isolated"}

    def check_connection(self, timeout_sec: int = 6) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Checks if Tor SOCKS5 proxy is online and retrieves the current exit node IP & country.
        Returns (is_connected, ip_address, details_dict).
        """
        proxies = {
            "http": self.proxy_url,
            "https": self.proxy_url
        }
        # 1. Try ipinfo.io
        try:
            resp = requests.get("https://ipinfo.io/json", proxies=proxies, timeout=timeout_sec)
            if resp.status_code == 200:
                data = resp.json()
                ip = data.get("ip")
                self.last_ip = ip
                return True, ip, data
        except Exception:
            pass

        # 2. Fallback to api.ipify.org
        try:
            resp = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=timeout_sec)
            if resp.status_code == 200:
                ip = resp.json().get("ip")
                self.last_ip = ip
                return True, ip, {"ip": ip}
        except Exception as e:
            logger.debug(f"Tor connection check failed: {e}")

        return False, None, None

    def renew_ip(self, wait_sec: float = 3.0) -> Tuple[bool, Optional[str]]:
        """
        Signals Tor Control port (SIGNAL NEWNYM) to switch to a new circuit and exit node IP.
        Returns (success, new_ip).
        """
        logger.info("Requesting new Tor identity (NEWNYM)...")
        signaled = False

        # 1. Try using Stem Controller
        if USE_STEM:
            try:
                with Controller.from_port(address=self.control_host, port=self.control_port) as controller:
                    if self.control_password:
                        controller.authenticate(password=self.control_password)
                    else:
                        controller.authenticate()
                    controller.signal(Signal.NEWNYM)
                    signaled = True
                    logger.info("✔ Sent SIGNAL NEWNYM via Stem Controller.")
            except Exception as e:
                logger.debug(f"Stem controller error: {e}, attempting raw socket...")

        # 2. Fallback using raw TCP socket to control port
        if not signaled:
            try:
                with socket.create_connection((self.control_host, self.control_port), timeout=4) as s:
                    auth_cmd = f'AUTHENTICATE "{self.control_password}"\r\n' if self.control_password else 'AUTHENTICATE ""\r\n'
                    s.sendall(auth_cmd.encode("utf-8"))
                    res = s.recv(1024).decode("utf-8", errors="ignore")
                    if "250" in res:
                        s.sendall(b"SIGNAL NEWNYM\r\n")
                        res2 = s.recv(1024).decode("utf-8", errors="ignore")
                        if "250" in res2:
                            signaled = True
                            logger.info("✔ Sent SIGNAL NEWNYM via raw socket.")
            except Exception as e:
                logger.debug(f"Raw socket Tor control error: {e}")

        # Wait for new circuit establishment
        time.sleep(wait_sec)

        # Verify new IP
        ok, current_ip, _ = self.check_connection(timeout_sec=8)
        if ok and current_ip:
            if current_ip != self.last_ip:
                logger.info(f"✔ Tor IP rotated successfully: {self.last_ip} -> {current_ip}")
            else:
                logger.info(f"✔ Tor circuit refreshed (Exit IP: {current_ip})")
            self.last_ip = current_ip
            return True, current_ip

        return signaled, self.last_ip
