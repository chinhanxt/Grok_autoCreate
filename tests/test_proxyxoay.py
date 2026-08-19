import time as time_module
import pytest
from core.proxyxoay import ProxyXoayManager


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(time_module, "time", clock.time)
    monkeypatch.setattr(time_module, "sleep", clock.sleep)
    return clock


def _make_mgr():
    return ProxyXoayManager(api_key="TEST_KEY")


def test_proxyxoay_initialization():
    mgr = ProxyXoayManager(api_key="TEST_KEY", nhamang="viettel", tinhthanh="1")
    assert mgr.api_key == "TEST_KEY"
    assert mgr.nhamang == "viettel"
    assert mgr.tinhthanh == "1"


def test_proxyxoay_empty_key():
    mgr = ProxyXoayManager(api_key="")
    ok, proxy_url, data = mgr.get_proxy()
    assert ok is False
    assert proxy_url is None


def test_rotate_to_new_ip_returns_fresh_proxy_immediately(monkeypatch, fake_clock):
    mgr = _make_mgr()
    fresh = {"status": 100, "proxyhttp": "5.6.7.8:8080", "ip": "5.6.7.8"}
    calls = []

    def fake_get_proxy(force_rotate=False, timeout_sec=10):
        calls.append({"force_rotate": force_rotate, "timeout_sec": timeout_sec})
        return True, "http://5.6.7.8:8080", fresh

    monkeypatch.setattr(mgr, "get_proxy", fake_get_proxy)

    ok, proxy_url, data = mgr.rotate_to_new_ip(timeout_sec=30)

    assert ok is True
    assert proxy_url == "http://5.6.7.8:8080"
    assert data == fresh
    assert len(calls) == 1
    assert calls[0] == {"force_rotate": True, "timeout_sec": 10}
    assert fake_clock.now == 1000.0


def test_rotate_to_new_ip_waits_cooldown_then_rotates(monkeypatch, fake_clock):
    mgr = _make_mgr()
    cooldown = {"status": 101, "message": "Vui lòng chờ 37s", "wait_seconds": 37}
    fresh = {"status": 100, "proxyhttp": "5.6.7.8:8080", "ip": "5.6.7.8"}
    call_times = []

    def fake_get_proxy(force_rotate=False, timeout_sec=10):
        call_times.append(fake_clock.now)
        if len(call_times) == 1:
            return False, None, cooldown
        return True, "http://5.6.7.8:8080", fresh

    monkeypatch.setattr(mgr, "get_proxy", fake_get_proxy)

    ok, proxy_url, data = mgr.rotate_to_new_ip(timeout_sec=60)

    assert ok is True
    assert proxy_url == "http://5.6.7.8:8080"
    assert data["status"] == 100
    assert len(call_times) == 2
    assert call_times[1] - call_times[0] == 37


def test_rotate_to_new_ip_loops_through_repeated_cooldowns_until_timeout(monkeypatch, fake_clock):
    mgr = _make_mgr()
    cooldown = {"status": 102, "message": "chờ 5s", "wait_seconds": 5}
    calls = []

    def fake_get_proxy(force_rotate=False, timeout_sec=10):
        calls.append(fake_clock.now)
        return False, None, dict(cooldown)

    monkeypatch.setattr(mgr, "get_proxy", fake_get_proxy)

    ok, proxy_url, data = mgr.rotate_to_new_ip(timeout_sec=30)

    assert ok is False
    assert proxy_url is None
    assert data["status"] == 102
    assert len(calls) == 6
    assert fake_clock.now - 1000.0 == 30
    assert calls == [1000.0, 1005.0, 1010.0, 1015.0, 1020.0, 1025.0]


def test_rotate_to_new_ip_sleeps_at_most_remaining_budget(monkeypatch, fake_clock):
    mgr = _make_mgr()
    cooldown = {"status": 101, "message": "chờ 9999s", "wait_seconds": 9999}

    def fake_get_proxy(force_rotate=False, timeout_sec=10):
        return False, None, dict(cooldown)

    monkeypatch.setattr(mgr, "get_proxy", fake_get_proxy)

    ok, proxy_url, data = mgr.rotate_to_new_ip(timeout_sec=30)

    assert ok is False
    assert proxy_url is None
    assert data["status"] == 101
    assert fake_clock.now - 1000.0 == 30


def test_rotate_to_new_ip_keeps_retrying_on_error_until_timeout(monkeypatch, fake_clock):
    mgr = _make_mgr()
    err = {"status": 500, "message": "server error"}
    calls = []

    def fake_get_proxy(force_rotate=False, timeout_sec=10):
        calls.append(fake_clock.now)
        return False, None, dict(err)

    monkeypatch.setattr(mgr, "get_proxy", fake_get_proxy)

    ok, proxy_url, data = mgr.rotate_to_new_ip(timeout_sec=30)

    assert ok is False
    assert proxy_url is None
    assert data["status"] == 500
    assert fake_clock.now - 1000.0 == 30
    assert len(calls) == 30
