import re
import pytest
from core.tempmail import TempMailClient, TempMailRateLimitError


def test_otp_regex_extraction():
    sample_texts = [
        "Your xAI verification code is 806901. Valid for 10 minutes.",
        "Mã xác thực của bạn là: 112466",
        "Use 982341 to complete your signup on Grok."
    ]
    for text in sample_texts:
        match = re.search(r"\b(\d{6})\b", text)
        assert match is not None
        assert len(match.group(1)) == 6


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("No JSON body")
        return self._json


def record_sleeps(monkeypatch):
    sleeps = []
    monkeypatch.setattr("core.tempmail.time.sleep", lambda s: sleeps.append(s))
    return sleeps


def fake_request_with(monkeypatch, handler):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(kwargs.get("proxies"))
        return handler(method, url, kwargs)

    monkeypatch.setattr("core.tempmail.requests.request", fake_request)
    return calls


def test_429_retries_3_times_keeping_proxy_then_raises_rate_limit(monkeypatch):
    def handler(method, url, kwargs):
        return FakeResponse(status_code=429, text="Too many requests body")

    calls = fake_request_with(monkeypatch, handler)
    record_sleeps(monkeypatch)

    client = TempMailClient(proxy="http://proxy.example:8080")
    with pytest.raises(TempMailRateLimitError) as excinfo:
        client._request("GET", "https://web2.temp-mail.org/messages")

    assert len(calls) == 4
    assert all(proxies == client.proxies for proxies in calls)
    assert "Temp-Mail rate limited (HTTP 429: Too many requests body)" == str(excinfo.value)


def test_429_with_retry_after_waits_exact_seconds(monkeypatch):
    def handler(method, url, kwargs):
        return FakeResponse(status_code=429, text="slow down", headers={"Retry-After": "7"})

    fake_request_with(monkeypatch, handler)
    sleeps = record_sleeps(monkeypatch)

    client = TempMailClient(proxy="http://proxy.example:8080")
    with pytest.raises(TempMailRateLimitError):
        client._request("GET", "https://web2.temp-mail.org/messages")

    assert sleeps == [7, 7, 7]


def test_429_without_retry_after_waits_30_seconds(monkeypatch):
    def handler(method, url, kwargs):
        return FakeResponse(status_code=429, text="rate limited")

    fake_request_with(monkeypatch, handler)
    sleeps = record_sleeps(monkeypatch)

    client = TempMailClient(proxy="http://proxy.example:8080")
    with pytest.raises(TempMailRateLimitError):
        client._request("GET", "https://web2.temp-mail.org/messages")

    assert sleeps == [30, 30, 30]


def test_network_error_retries_twice_without_dropping_proxy(monkeypatch):
    def handler(method, url, kwargs):
        raise ConnectionError("connection reset")

    calls = fake_request_with(monkeypatch, handler)
    record_sleeps(monkeypatch)

    client = TempMailClient(proxy="http://proxy.example:8080")
    with pytest.raises(RuntimeError) as excinfo:
        client._request("GET", "https://web2.temp-mail.org/messages")

    assert len(calls) == 2
    assert all(proxies == client.proxies for proxies in calls)
    assert "connection reset" in str(excinfo.value)


def test_network_error_without_proxy_retries_twice(monkeypatch):
    def handler(method, url, kwargs):
        raise ConnectionError("connection reset")

    calls = fake_request_with(monkeypatch, handler)
    record_sleeps(monkeypatch)

    client = TempMailClient()
    with pytest.raises(RuntimeError):
        client._request("GET", "https://web2.temp-mail.org/messages")

    assert len(calls) == 2
    assert all(proxies is None for proxies in calls)


def test_create_mailbox_propagates_rate_limit_error(monkeypatch):
    def handler(method, url, kwargs):
        return FakeResponse(status_code=429, text="rate limited")

    fake_request_with(monkeypatch, handler)
    record_sleeps(monkeypatch)

    client = TempMailClient(proxy="http://proxy.example:8080")
    with pytest.raises(TempMailRateLimitError):
        client.create_mailbox()
