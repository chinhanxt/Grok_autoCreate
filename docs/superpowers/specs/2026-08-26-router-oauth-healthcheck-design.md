# Design Spec: xAI / Grok Router OAuth Standard & Health-Check Validation

## Overview
This specification outlines improvements to `/home/chinhan/xai-grok-account-creator` to ensure 100% of accounts generated and exported for Router integrations remain alive, avoid HTTP 401 errors, and follow exact Router token specifications with automated pre-save health-checks.

---

## 1. Standard Router JSON Output Specification

All exported accounts for Router and API Gateway use must conform to a 5-field JSON array schema:

```json
[
  {
    "email": "xai_user01@domain.com",
    "access_token": "eyJ0eXAiOiJhdCtqd3Qi...",
    "refresh_token": "rt_abc123xyz...",
    "sso_cookie": "sso_session_cookie_value...",
    "sso_rw_cookie": "sso_rw_cookie_value..."
  }
]
```

### Field Roles & Fallback Logic
- `email`: User account identifier.
- `access_token`: Official xAI OAuth 2.0 JWT token (`at+jwt`) used for direct inference calls (valid ~a few hours).
- `refresh_token`: OAuth refresh token used by Router to exchange for a new `access_token` when expired.
- `sso_cookie`: xAI SSO session cookie (`sso`). Used as a lifeline by Router / background headless browser to mint brand-new OAuth tokens if tokens are revoked.
- `sso_rw_cookie`: Read-write SSO cookie (`sso-rw`).

### Methods Updated in `core/exporter.py`:
- `AccountRecord.to_oauth_dict()`: Exports all 5 fields (`email`, `access_token`, `refresh_token`, `sso_cookie`, `sso_rw_cookie`).
- `load_oauth_accounts(json_path)`: Returns a list of dictionaries with all 5 fields.
- `save_oauth_router_accounts(output_path, json_path, only_healthy=True)`: Utility to export only healthy, valid Router accounts to a target file (e.g., `grok_router_accounts.json`).

---

## 2. OAuth Technical Specification

The tool uses the RFC 8628 OAuth 2.0 Device Authorization Grant flow against xAI identity services:

- **Device Code Endpoint**: `POST https://auth.x.ai/oauth2/device/code`
- **Client ID**: `b1a00492-073a-47ea-816f-4c329264a828`
- **Mandatory Scopes**:
  `openid profile email offline_access grok-cli:access api:access conversations:read conversations:write workspaces:read workspaces:write`
- **Token Exchange Endpoint**: `POST https://auth.x.ai/oauth2/token`
- **Grant Type**: `urn:ietf:params:oauth:grant-type:device_code`

---

## 3. Pre-Save Health-Check Mechanism (Gatekeeper)

To guarantee that 100% of accounts written to output are alive and working, every account must pass an automated inference ping before being committed or exported as active:

### Health-Check Request Details:
- **Method & URL**: `POST https://cli-chat-proxy.grok.com/v1/chat/completions`
- **Headers**:
  - `Authorization: Bearer <access_token>`
  - `x-grok-client-version: 1.0.0`
  - `User-Agent: grok-cli/1.0.0`
  - `Content-Type: application/json`
- **Payload**:
  ```json
  {
    "model": "grok-4.6",
    "messages": [
      {
        "role": "user",
        "content": "ping"
      }
    ]
  }
  ```
- **Validation Criteria**:
  - `HTTP 200 OK`: Account is 100% alive. Record marked with `status="active"`, `extra["health_verified"]=True`.
  - `HTTP 401 / 403 / other`: Account is not alive. If a valid `sso_cookie` exists, the tool attempts 1 token re-mint. If still failing, marked as `status="invalid"` / `extra["health_verified"]=False` and excluded from router export.

### Implementation Locations:
1. `core/healthcheck.py`: Dedicated helper `verify_grok_cli_health(access_token, proxy=None, timeout=15) -> Tuple[bool, int, str]`.
2. `core/auth.py`: In `complete_registration()`, verifies token before returning `AccountRecord`.
3. `core/oauth.py`: In `AutoOAuthDaemon`, runs health-check before updating account record.
4. `cli.py`: Displays health-check status in terminal and adds `--export-router` option.
5. `web/server.py`: Updates `/api/export-oauth-json` and adds `/api/accounts/check-health`.
6. Batch scripts (`batch_create_100_oauth.py`, `sync_all_oauth.py`, `run_sync_and_create_100.py`).

---

## 4. Testing Strategy

1. Unit tests in `tests/test_healthcheck.py` mocking success (HTTP 200) and failure (HTTP 401) responses.
2. Unit tests in `tests/test_exporter.py` verifying 5-field schema output (`email`, `access_token`, `refresh_token`, `sso_cookie`, `sso_rw_cookie`).
3. Integration tests for CLI & Web export endpoints.
