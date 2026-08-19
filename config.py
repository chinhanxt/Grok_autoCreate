"""
Configuration settings for Grok & x.ai Account Creator.
"""
import os
import random
import string

# Target URLs
XAI_SIGNUP_URL = "https://accounts.x.ai/sign-up?redirect=grok-com&return_to=%2F"
GROK_SESSION_URL = "https://grok.com/api/auth/session"
GROK_MAIN_URL = "https://grok.com/"

# Timeout settings (in milliseconds / seconds)
DEFAULT_TIMEOUT_MS = 25000
CLOUDFLARE_SOLVE_TIMEOUT_SEC = 25
OTP_POLL_TIMEOUT_SEC = 120

# Default Output Paths
DEFAULT_JSON_OUTPUT = "accounts.json"
DEFAULT_TXT_OUTPUT = "accounts.txt"

# Default Tor Proxy Settings
DEFAULT_TOR_SOCKS_PORT = 9050
DEFAULT_TOR_CONTROL_PORT = 9051
DEFAULT_TOR_PROXY_URL = "socks5://127.0.0.1:9050"

# Default Residential Rotating Proxy (proxyxoay.shop)
DEFAULT_PROXYXOAY_KEY = "HVnSXrEVXRSrUYBkwYzuId"
DEFAULT_PROXYXOAY_NHAMANG = "random"
DEFAULT_PROXYXOAY_TINHTHANH = "0"

# Default Name Generation Formula: User_<2-digits><2-letters> (vd: User_01AI)
DEFAULT_NAME_PREFIX = "User_"
DEFAULT_PASSWORD = "taikhoanAI123"


def generate_random_name(prefix: str = DEFAULT_NAME_PREFIX) -> tuple[str, str]:
    """
    Generates a random name according to formula: User_<2-digits><2-letters> (e.g. User_01AI, User_84QK).
    Returns: (first_name, last_name) -> ('User_01AI', 'AI')
    """
    num = f"{random.randint(1, 99):02d}"
    suffix = "".join(random.choices(string.ascii_uppercase, k=2))
    first_name = f"{prefix}{num}{suffix}"
    last_name = suffix
    return first_name, last_name


DEFAULT_FIRST_NAME = "User_01AI"
DEFAULT_LAST_NAME = "AI"

# Default Terms of Service Version
DEFAULT_TOS_VERSION = 5

# Common User Agents
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
