# Router OAuth 2.0 Standard & Grok Health-Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement standard 5-field JSON output format, verify OAuth 2.0 device flow parameters, and integrate pre-save `grok-4.6` health-checks to guarantee 100% active Router accounts.

**Architecture:** A standalone `core/healthcheck.py` module performs lightweight validation against `https://cli-chat-proxy.grok.com/v1/chat/completions`. `core/exporter.py` is updated to output all 5 required Router fields (`email`, `access_token`, `refresh_token`, `sso_cookie`, `sso_rw_cookie`). The health-check is integrated into `core/auth.py`, `core/oauth.py`, `cli.py`, `web/server.py`, and batch scripts.

**Tech Stack:** Python 3.10+, Requests, Playwright/Scrapling, FastAPI, Pytest.

## Global Constraints
- Router JSON Output must strictly include 5 keys: `email`, `access_token`, `refresh_token`, `sso_cookie`, `sso_rw_cookie`.
- Client ID: `b1a00492-073a-47ea-816f-4c329264a828`.
- Scopes: `openid profile email offline_access grok-cli:access api:access conversations:read conversations:write workspaces:read workspaces:write`.
- Health Check URL: `POST https://cli-chat-proxy.grok.com/v1/chat/completions` with header `x-grok-client-version: 1.0.0`, `User-Agent: grok-cli/1.0.0`, body `{"model": "grok-4.6", "messages": [{"role": "user", "content": "ping"}]}`.
- HTTP 200 indicates healthy account; accounts failing health check must not be marked as active in Router exports.

---

### Task 1: Create Health-Check Module (`core/healthcheck.py`) & Tests

**Files:**
- Create: `core/healthcheck.py`
- Test: `tests/test_healthcheck.py`

**Interfaces:**
- Produces: `verify_grok_cli_health(access_token: str, proxy: Optional[str] = None, timeout: int = 15) -> Tuple[bool, int, str]`

- [ ] **Step 1: Write test for health check in `tests/test_healthcheck.py`**

```python
import pytest
from unittest.mock import patch, MagicMock
from core.healthcheck import verify_grok_cli_health

def test_verify_grok_cli_health_success():
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"choices": [{"message": {"content": "pong"}}]}'
        mock_resp.json.return_value = {"choices": [{"message": {"content": "pong"}}]}
        mock_post.return_value = mock_resp

        ok, status_code, msg = verify_grok_cli_health("test_access_token")
        assert ok is True
        assert status_code == 200
        assert "OK" in msg
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test_access_token"
        assert kwargs["headers"]["x-grok-client-version"] == "1.0.0"
        assert kwargs["headers"]["User-Agent"] == "grok-cli/1.0.0"
        assert kwargs["json"]["model"] == "grok-4.6"

def test_verify_grok_cli_health_failure_401():
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = '{"error": "Unauthorized"}'
        mock_post.return_value = mock_resp

        ok, status_code, msg = verify_grok_cli_health("invalid_token")
        assert ok is False
        assert status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_healthcheck.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'core.healthcheck')

- [ ] **Step 3: Implement `core/healthcheck.py`**

```python
"""
Health-check module for Grok / xAI accounts and tokens.
Sends ping requests to https://cli-chat-proxy.grok.com/v1/chat/completions using grok-4.6.
"""
import logging
import requests
from typing import Optional, Tuple, Dict, Any

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
    Sends a test ping to Grok CLI completions API to verify token validity.
    Returns (is_healthy, status_code, response_message).
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
            return False, resp.status_code, f"Failed HTTP {resp.status_code}: {err_msg}"
    except Exception as e:
        logger.warning(f"Health check network exception: {e}")
        return False, 0, f"Exception: {e}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_healthcheck.py -v`
Expected: PASS

---

### Task 2: Update `core/exporter.py` for 5-Field Router Output

**Files:**
- Modify: `core/exporter.py`
- Modify: `tests/test_exporter.py`

**Interfaces:**
- Consumes: `AccountRecord`
- Produces: `AccountRecord.to_oauth_dict()`, `load_oauth_accounts()`, `save_oauth_router_accounts()`

- [ ] **Step 1: Write test in `tests/test_exporter.py` for 5-field Router schema**

Update `test_load_oauth_accounts` in `tests/test_exporter.py` to assert all 5 fields (`email`, `access_token`, `refresh_token`, `sso_cookie`, `sso_rw_cookie`).

- [ ] **Step 2: Update `core/exporter.py`**

Ensure `to_oauth_dict()` returns:
```python
return {
    "email": self.email,
    "access_token": self.access_token or self.sso_cookie,
    "refresh_token": self.refresh_token or self.sso_rw_cookie or self.sso_cookie,
    "sso_cookie": self.sso_cookie,
    "sso_rw_cookie": self.sso_rw_cookie or self.sso_cookie
}
```
And update `load_oauth_accounts()` and add `save_oauth_router_accounts()`.

- [ ] **Step 3: Run pytest on `tests/test_exporter.py`**

Run: `pytest tests/test_exporter.py -v`
Expected: PASS

---

### Task 3: Integrate Health-Check into `core/auth.py` and `core/oauth.py`

**Files:**
- Modify: `core/auth.py`
- Modify: `core/oauth.py`

- [ ] **Step 1: Update `core/auth.py` `complete_registration`**
Call `verify_grok_cli_health(access_token, proxy=self.engine.proxy)` after minting OAuth tokens.
If healthy: set `record.status = "active"` and `record.extra["health_verified"] = True`.
If unhealthy: log warning and mark `record.extra["health_verified"] = False`.

- [ ] **Step 2: Update `core/oauth.py` AutoOAuthDaemon**
Before saving newly minted tokens in daemon, verify health with `verify_grok_cli_health`.

- [ ] **Step 3: Run pytest on test suite**

---

### Task 4: Update `cli.py` and `web/server.py`

**Files:**
- Modify: `cli.py`
- Modify: `web/server.py`

- [ ] **Step 1: Update `cli.py`**
Add `--export-router [PATH]` argument to export formatted Router JSON with only verified healthy accounts.
Add `--check-health` flag to scan and print health status table of all existing accounts.
In `create_single_account`, perform health check and display badge in Rich Panel.

- [ ] **Step 2: Update `web/server.py`**
Update `/api/export-oauth-json` to export full 5-field schema.
Add `/api/accounts/check-health` endpoint.

- [ ] **Step 3: Update batch scripts (`batch_create_100_oauth.py`, `sync_all_oauth.py`, `run_sync_and_create_100.py`)**
Add health check validation before printing success / saving.

---

### Task 5: Verification & Full Test Suite

- [ ] **Step 1: Run full unit test suite**
- [ ] **Step 2: Validate 5-field JSON output format and CLI commands**
