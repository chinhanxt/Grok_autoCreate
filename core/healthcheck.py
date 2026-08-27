"""
Health-check module for Grok / xAI accounts and tokens.
Sends lightweight ping requests to https://cli-chat-proxy.grok.com/v1/chat/completions using grok-4.6.
"""
import logging
import requests
from typing import Optional, Tuple, Dict, Any, Union

logger = logging.getLogger("xai_healthcheck")

GROK_CLI_CHAT_URL = "https://cli-chat-proxy.grok.com/v1/chat/completions"
GROK_CLIENT_VERSION = "1.0.0"
GROK_USER_AGENT = "grok-cli/1.0.0"
GROK_TEST_MODEL = "grok-4.6"


def verify_grok_cli_health(
    access_token: str,
    proxy: Optional[str] = None,
    timeout: int = 15
) -> Tuple[bool, int, str]:
    """
    Sends a test ping request to Grok CLI completions API to verify token validity.
    Returns (is_healthy, status_code, message).
    """
    if not access_token:
        return False, 0, "No access token provided"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-grok-client-version": GROK_CLIENT_VERSION,
        "User-Agent": GROK_USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": GROK_TEST_MODEL,
        "messages": [
            {"role": "user", "content": "ping"}
        ]
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None

    try:
        resp = requests.post(
            GROK_CLI_CHAT_URL,
            headers=headers,
            json=payload,
            proxies=proxies,
            timeout=timeout
        )
        if resp.status_code == 200:
            return True, 200, "Healthy (HTTP 200 OK)"
        else:
            err_msg = resp.text[:200]
            logger.warning(f"Health check failed (HTTP {resp.status_code}): {err_msg}")
            return False, resp.status_code, f"Failed (HTTP {resp.status_code})"
    except Exception as e:
        logger.warning(f"Health check request exception: {e}")
        return False, 0, f"Exception: {e}"


def check_account_health_with_auto_refresh(
    account: Dict[str, Any],
    proxy: Optional[str] = None
) -> Tuple[bool, int, str, Optional[Dict[str, str]]]:
    """
    Checks health of an account dict.
    If access_token fails with 401 and refresh_token or sso_cookie is present,
    attempts refresh / re-mint.
    Returns (is_healthy, status_code, message, updated_tokens_if_refreshed).
    """
    access_token = account.get("access_token", "")
    ok, code, msg = verify_grok_cli_health(access_token, proxy=proxy)
    if ok:
        return True, code, msg, None

    # If 401 or invalid token, try refresh token if present
    refresh_token = account.get("refresh_token", "")
    if refresh_token and refresh_token != access_token:
        try:
            from core.oauth import XAI_TOKEN_URL, XAI_OAUTH_CLIENT_ID
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
            resp = requests.post(XAI_TOKEN_URL, data=data, headers=headers, proxies=proxies, timeout=15)
            if resp.status_code == 200:
                res_data = resp.json()
                new_acc_tok = res_data.get("access_token")
                new_ref_tok = res_data.get("refresh_token", refresh_token)
                if new_acc_tok:
                    ok2, code2, msg2 = verify_grok_cli_health(new_acc_tok, proxy=proxy)
                    if ok2:
                        return True, 200, "Healthy (Refreshed via OAuth)", {
                            "access_token": new_acc_tok,
                            "refresh_token": new_ref_tok
                        }
        except Exception as e:
            logger.debug(f"Refresh token attempt error: {e}")

    return False, code, msg, None
