import pytest
from unittest.mock import patch, MagicMock
from core.reviver import revive_single_account


def test_revive_already_healthy():
    acc = {
        "email": "healthy@test.com",
        "access_token": "valid_token",
        "sso_cookie": "sso_val"
    }
    with patch("core.reviver.verify_grok_cli_health", return_value=(True, 200, "Healthy (HTTP 200 OK)")):
        ok, msg, updated = revive_single_account(acc)
        assert ok is True
        assert "Already alive" in msg
        assert updated["email"] == "healthy@test.com"


def test_revive_via_refresh_token():
    acc = {
        "email": "refresh@test.com",
        "access_token": "expired_token",
        "refresh_token": "valid_refresh_token",
        "sso_cookie": "sso_val"
    }
    
    # 1st call fails (expired token), 2nd call after refresh succeeds (new token)
    health_calls = [
        (False, 401, "Expired"),
        (True, 200, "Healthy (HTTP 200 OK)")
    ]
    with patch("core.reviver.verify_grok_cli_health", side_effect=health_calls), \
         patch("requests.post") as mock_post:
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token"
        }
        mock_post.return_value = mock_resp

        ok, msg, updated = revive_single_account(acc)
        assert ok is True
        assert "Revived via OAuth Refresh" in msg
        assert updated["access_token"] == "new_access_token"
        assert updated["refresh_token"] == "new_refresh_token"


def test_revive_via_browser_sso():
    acc = {
        "email": "browser_sso@test.com",
        "password": "pass",
        "access_token": "dead_token",
        "refresh_token": "dead_refresh",
        "sso_cookie": "valid_sso_cookie",
        "sso_rw_cookie": "valid_sso_rw"
    }

    # Health check: 1st fails (dead_token), refresh fails, then browser mints fresh token, 2nd health check passes
    health_calls = [
        (False, 401, "Expired"),
        (True, 200, "Healthy (HTTP 200 OK)")
    ]

    mock_engine = MagicMock()
    mock_page = MagicMock()
    mock_engine.start.return_value = mock_page

    mock_oauth_mgr = MagicMock()
    mock_oauth_mgr.mint_tokens_for_page.return_value = {
        "access_token": "fresh_browser_access_token",
        "refresh_token": "fresh_browser_refresh_token"
    }

    with patch("core.reviver.verify_grok_cli_health", side_effect=health_calls), \
         patch("core.reviver.StealthEngine", return_value=mock_engine), \
         patch("core.reviver.OAuthTokenManager", return_value=mock_oauth_mgr), \
         patch("requests.post") as mock_post:
        
        # Refresh token request returns 400
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_post.return_value = mock_resp

        ok, msg, updated = revive_single_account(acc)
        assert ok is True
        assert "Revived via SSO Browser Minting" in msg
        assert updated["access_token"] == "fresh_browser_access_token"
