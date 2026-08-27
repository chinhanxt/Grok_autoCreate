import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from web.server import app


client = TestClient(app)


def test_export_oauth_json_5_fields(monkeypatch, tmp_path):
    mock_accounts = [
        {
            "email": "user1@xai.com",
            "access_token": "at_jwt_val",
            "refresh_token": "rt_val",
            "sso_cookie": "sso_cookie_val",
            "sso_rw_cookie": "sso_rw_cookie_val",
            "status": "active"
        }
    ]
    monkeypatch.setattr("core.exporter.load_accounts", lambda *args, **kwargs: mock_accounts)

    resp = client.get("/api/export-oauth-json")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0] == {
        "email": "user1@xai.com",
        "access_token": "at_jwt_val",
        "refresh_token": "rt_val",
        "sso_cookie": "sso_cookie_val",
        "sso_rw_cookie": "sso_rw_cookie_val"
    }


def test_accounts_health_check_endpoint(monkeypatch):
    mock_accounts = [
        {
            "email": "live@xai.com",
            "access_token": "at_live",
            "refresh_token": "rt_live",
            "sso_cookie": "sso_live",
            "status": "active"
        },
        {
            "email": "dead@xai.com",
            "access_token": "at_dead",
            "refresh_token": "rt_dead",
            "sso_cookie": "sso_dead",
            "status": "active"
        }
    ]
    monkeypatch.setattr("web.server.load_accounts", lambda *args, **kwargs: mock_accounts)

    def fake_health(acc, proxy=None):
        if acc["email"] == "live@xai.com":
            return True, 200, "Healthy (HTTP 200 OK)", None
        return False, 401, "Failed HTTP 401: Unauthorized", None

    monkeypatch.setattr("core.healthcheck.check_account_health_with_auto_refresh", fake_health)

    resp = client.get("/api/accounts/health-check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["live_count"] == 1
    assert data["dead_count"] == 1
    assert data["results"][0]["status"] == "healthy"
    assert data["results"][1]["status"] == "dead"
