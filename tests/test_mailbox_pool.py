import pytest
from core.mailbox_pool import MailboxPool, MailboxEntry
from core.tempmail import TempMailClient, TempMailRateLimitError


class FakeProxyMgr:
    def __init__(self, initial_proxy="http://ip-a:8080", rotate_result=(True, "http://ip-b:8080", {"status": 100})):
        self.initial_proxy = initial_proxy
        self.rotate_result = rotate_result
        self.get_proxy_calls = 0
        self.rotate_calls = []

    def get_proxy(self, **kwargs):
        self.get_proxy_calls += 1
        return (True, self.initial_proxy, {"status": 100})

    def rotate_to_new_ip(self, **kwargs):
        self.rotate_calls.append(kwargs)
        return self.rotate_result


def record_sleeps(monkeypatch):
    sleeps = []
    monkeypatch.setattr("core.mailbox_pool.time.sleep", lambda s: sleeps.append(s))
    return sleeps


def fake_create_inbox(monkeypatch, proxies_used=None, fail_first_n=0):
    """Monkeypatch TempMailClient.create_inbox; returns the proxy used per call."""
    state = {"n": 0}
    proxies_used = proxies_used if proxies_used is not None else []

    def fake_create(self):
        proxies_used.append(self.proxy)
        call_no = state["n"]
        state["n"] += 1
        if call_no < fail_first_n:
            raise TempMailRateLimitError("Temp-Mail rate limited (HTTP 429)")
        return (f"user{call_no}@tempmail.org", f"token-{call_no}")

    monkeypatch.setattr(TempMailClient, "create_inbox", fake_create)
    return proxies_used


def test_prepare_creates_count_mailboxes_spaced(monkeypatch):
    sleeps = record_sleeps(monkeypatch)
    proxies_used = []
    fake_create_inbox(monkeypatch, proxies_used=proxies_used)
    proxy_mgr = FakeProxyMgr()

    pool = MailboxPool(proxy_mgr, count=3, spacing=12.0, max_per_ip=4)
    made = pool.prepare()

    assert made == 3
    assert sleeps == [12.0, 12.0]
    assert proxies_used == ["http://ip-a:8080"] * 3
    assert proxy_mgr.get_proxy_calls == 1
    assert proxy_mgr.rotate_calls == []


def test_rotates_after_max_per_ip(monkeypatch):
    record_sleeps(monkeypatch)
    fake_create_inbox(monkeypatch)
    proxy_mgr = FakeProxyMgr(
        initial_proxy="http://ip-a:8080",
        rotate_result=(True, "http://ip-b:8080", {"status": 100}),
    )

    pool = MailboxPool(proxy_mgr, count=5, spacing=1.0, max_per_ip=4)
    made = pool.prepare()

    assert made == 5
    assert len(proxy_mgr.rotate_calls) == 1
    assert proxy_mgr.rotate_calls[0]["timeout_sec"] == 90
    entries = [pool.acquire() for _ in range(5)]
    assert [e.proxy for e in entries] == ["http://ip-a:8080"] * 4 + ["http://ip-b:8080"]


def test_acquire_fifo_order(monkeypatch):
    record_sleeps(monkeypatch)
    fake_create_inbox(monkeypatch)

    pool = MailboxPool(FakeProxyMgr(), count=3, spacing=1.0, max_per_ip=10)
    pool.prepare()

    emails = [pool.acquire().email for _ in range(3)]
    assert emails == ["user0@tempmail.org", "user1@tempmail.org", "user2@tempmail.org"]


def test_release_returns_mailbox_to_pool(monkeypatch):
    record_sleeps(monkeypatch)
    fake_create_inbox(monkeypatch)

    pool = MailboxPool(FakeProxyMgr(), count=1, spacing=1.0, max_per_ip=10)
    pool.prepare()

    entry = pool.acquire()
    assert isinstance(entry, MailboxEntry)
    pool.release(entry)
    again = pool.acquire()
    assert again == entry


def test_stopped_stops_prepare(monkeypatch):
    record_sleeps(monkeypatch)
    fake_create_inbox(monkeypatch)
    state = {"calls": 0}

    def stopped():
        state["calls"] += 1
        return state["calls"] > 2

    pool = MailboxPool(FakeProxyMgr(), count=5, spacing=1.0, max_per_ip=10, stopped=stopped)
    made = pool.prepare()

    assert made == 2
    assert pool._queue.qsize() == 2
    assert state["calls"] == 3


def test_rate_limit_rotates_and_retries(monkeypatch):
    record_sleeps(monkeypatch)
    proxies_used = []
    fake_create_inbox(monkeypatch, proxies_used=proxies_used, fail_first_n=1)
    proxy_mgr = FakeProxyMgr(
        initial_proxy="http://ip-a:8080",
        rotate_result=(True, "http://ip-b:8080", {"status": 100}),
    )

    pool = MailboxPool(proxy_mgr, count=1, spacing=1.0, max_per_ip=4)
    made = pool.prepare()

    assert made == 1
    assert proxies_used == ["http://ip-a:8080", "http://ip-b:8080"]
    assert len(proxy_mgr.rotate_calls) == 1
    entry = pool.acquire()
    assert entry.email == "user1@tempmail.org"
    assert entry.proxy == "http://ip-b:8080"


def test_rotation_failure_stops_without_infinite_loop(monkeypatch):
    sleeps = record_sleeps(monkeypatch)
    fake_create_inbox(monkeypatch)
    proxy_mgr = FakeProxyMgr(rotate_result=(False, None, {"error": "cooldown"}))

    pool = MailboxPool(proxy_mgr, count=10, spacing=1.0, max_per_ip=2)
    made = pool.prepare()

    assert made == 2
    assert pool._queue.qsize() == 2
    assert len(proxy_mgr.rotate_calls) == 3
    assert sleeps == [1.0, 1.0, 1.0, 1.0]


def test_proxy_mgr_none_uses_direct_and_stops(monkeypatch):
    record_sleeps(monkeypatch)
    proxies_used = []
    fake_create_inbox(monkeypatch, proxies_used=proxies_used)

    pool = MailboxPool(None, count=10, spacing=1.0, max_per_ip=2)
    made = pool.prepare()

    assert made == 2
    assert proxies_used == [None, None]
