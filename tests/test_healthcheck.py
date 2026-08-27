import pytest
from unittest.mock import patch, MagicMock
from core.healthcheck import (
    verify_grok_cli_health,
    GROK_CLI_CHAT_URL,
    GROK_CLIENT_VERSION,
    GROK_USER_AGENT,
    GROK_TEST_MODEL
)


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
        assert "200" in msg

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == GROK_CLI_CHAT_URL
        assert kwargs["headers"]["Authorization"] == "Bearer test_access_token"
        assert kwargs["headers"]["x-grok-client-version"] == GROK_CLIENT_VERSION
        assert kwargs["headers"]["User-Agent"] == GROK_USER_AGENT
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert kwargs["json"]["model"] == GROK_TEST_MODEL
        assert kwargs["json"]["messages"] == [{"role": "user", "content": "ping"}]


def test_verify_grok_cli_health_failure_401():
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = '{"error": "Unauthorized"}'
        mock_post.return_value = mock_resp

        ok, status_code, msg = verify_grok_cli_health("invalid_token")
        assert ok is False
        assert status_code == 401
        assert "401" in msg


def test_verify_grok_cli_health_empty_token():
    ok, status_code, msg = verify_grok_cli_health("")
    assert ok is False
    assert status_code == 0
    assert "No access token" in msg


def test_verify_grok_cli_health_with_proxy():
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        ok, status_code, msg = verify_grok_cli_health("tok_abc", proxy="http://1.2.3.4:8080")
        assert ok is True
        args, kwargs = mock_post.call_args
        assert kwargs["proxies"] == {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}
