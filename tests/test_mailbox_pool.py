import threading
import time as time_module
import pytest
from core.mailbox_pool import MailboxPool, MailboxEntry, MAILBOX_CREATE_LOCK, MAX_CONSECUTIVE_CREATE_FAILURES
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


def fake_create_inbox_sequence(monkeypatch, exceptions, proxies_used=None):
    """Monkeypatch TempMailClient.create_inbox; each entry in `exceptions` is
    raised for the corresponding call (in order); once exhausted, creation
    succeeds."""
    state = {"n": 0}
    proxies_used = proxies_used if proxies_used is not None else []

    def fake_create(self):
        proxies_used.append(self.proxy)
        call_no = state["n"]
        state["n"] += 1
        if call_no < len(exceptions):
            raise exceptions[call_no]
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


def test_acquire_timeout_zero_returns_none_on_empty_pool():
    pool = MailboxPool(None, count=0)
    assert pool.acquire(timeout=0) is None


def test_acquire_timeout_zero_returns_entry_when_available(monkeypatch):
    record_sleeps(monkeypatch)
    fake_create_inbox(monkeypatch)

    pool = MailboxPool(FakeProxyMgr(), count=1, spacing=1.0, max_per_ip=10)
    pool.prepare()

    entry = pool.acquire(timeout=0)
    assert isinstance(entry, MailboxEntry)
    assert pool.acquire(timeout=0) is None


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


def test_proxy_mgr_none_with_initial_proxy_uses_proxy_without_rotation(monkeypatch):
    record_sleeps(monkeypatch)
    proxies_used = []
    fake_create_inbox(monkeypatch, proxies_used=proxies_used)

    pool = MailboxPool(None, count=10, spacing=1.0, max_per_ip=2, initial_proxy="http://p:8080")
    made = pool.prepare()

    assert made == 10
    assert proxies_used == ["http://p:8080"] * 10
    entries = [pool.acquire(timeout=0) for _ in range(10)]
    assert [e.proxy for e in entries] == ["http://p:8080"] * 10


def test_initial_proxy_seeds_proxy_mgr_current_proxy(monkeypatch):
    record_sleeps(monkeypatch)
    proxies_used = []
    fake_create_inbox(monkeypatch, proxies_used=proxies_used)
    proxy_mgr = FakeProxyMgr(
        initial_proxy="http://ip-a:8080",
        rotate_result=(True, "http://ip-b:8080", {"status": 100}),
    )

    pool = MailboxPool(proxy_mgr, count=5, spacing=1.0, max_per_ip=4, initial_proxy="http://seed:8080")
    made = pool.prepare()

    assert made == 5
    assert proxy_mgr.get_proxy_calls == 0
    assert len(proxy_mgr.rotate_calls) == 1
    entries = [pool.acquire(timeout=0) for _ in range(5)]
    assert [e.proxy for e in entries] == ["http://seed:8080"] * 4 + ["http://ip-b:8080"]


def test_max_per_ip_zero_raises_value_error():
    with pytest.raises(ValueError):
        MailboxPool(FakeProxyMgr(), count=3, max_per_ip=0)


def test_non_rate_limit_failure_retries_with_rotation(monkeypatch):
    """A generic (non-429) failure such as a 403 Cloudflare block is treated as
    retryable-with-rotation: bounded retries each rotate to a fresh proxy."""
    record_sleeps(monkeypatch)
    proxies_used = []
    fake_create_inbox_sequence(monkeypatch, [RuntimeError("HTTP 403 blocked")], proxies_used)
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


def test_non_rate_limit_failure_gives_up_after_bounded_retries(monkeypatch):
    """Persistent non-429 failures exhaust the bounded retries and return None
    for that mailbox (rotation still attempted each retry)."""
    record_sleeps(monkeypatch)
    proxies_used = []
    fake_create_inbox_sequence(monkeypatch, [RuntimeError("boom")] * 9, proxies_used)
    proxy_mgr = FakeProxyMgr(rotate_result=(True, "http://ip-b:8080", {"status": 100}))

    pool = MailboxPool(proxy_mgr, count=100, spacing=0.0, max_per_ip=10)
    made = pool.prepare()

    assert made == 0
    assert pool._queue.qsize() == 0
    assert pool._consecutive_failures == MAX_CONSECUTIVE_CREATE_FAILURES
    # 3 failed mailboxes * RATE_LIMIT_MAX_ATTEMPTS create attempts each.
    assert len(proxies_used) == 9


def test_prepare_continues_after_failed_mailbox(monkeypatch):
    """A single failed mailbox must not discard the remaining ones: pre-create
    keeps going and still covers the full count."""
    record_sleeps(monkeypatch)
    fake_create_inbox_sequence(
        monkeypatch,
        [RuntimeError("boom"), RuntimeError("boom"), RuntimeError("boom")],
    )
    proxy_mgr = FakeProxyMgr(rotate_result=(True, "http://ip-b:8080", {"status": 100}))

    pool = MailboxPool(proxy_mgr, count=2, spacing=1.0, max_per_ip=4)
    made = pool.prepare()

    assert made == 2
    assert pool._queue.qsize() == 2
    assert pool._consecutive_failures == 0


def test_prepare_stops_after_bounded_consecutive_failures(monkeypatch):
    """After MAX_CONSECUTIVE_CREATE_FAILURES consecutive failures prepare()
    stops instead of looping forever."""
    record_sleeps(monkeypatch)
    fake_create_inbox_sequence(monkeypatch, [RuntimeError("boom")] * 9)
    proxy_mgr = FakeProxyMgr(rotate_result=(True, "http://ip-b:8080", {"status": 100}))

    pool = MailboxPool(proxy_mgr, count=100, spacing=0.0, max_per_ip=10)
    made = pool.prepare()

    assert made == 0
    assert pool._queue.qsize() == 0
    assert pool._consecutive_failures == MAX_CONSECUTIVE_CREATE_FAILURES


def test_global_create_lock_serializes_across_pools(monkeypatch):
    """Two pools prepared concurrently on separate threads must never create
    mailboxes at the same instant (module-level MAILBOX_CREATE_LOCK)."""
    active = {"n": 0, "max": 0}
    guard = threading.Lock()

    def fake_create(self):
        with guard:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time_module.sleep(0.01)
        with guard:
            active["n"] -= 1
        return ("user@tempmail.org", "token")

    monkeypatch.setattr(TempMailClient, "create_inbox", fake_create)
    monkeypatch.setattr("core.mailbox_pool.time.sleep", lambda s: None)

    results = []

    def run():
        pool = MailboxPool(FakeProxyMgr(), count=2, spacing=0.0, max_per_ip=10)
        results.append(pool.prepare())

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == [2, 2]
    assert active["max"] == 1
