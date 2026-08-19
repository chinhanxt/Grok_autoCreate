from fastapi.testclient import TestClient
from types import SimpleNamespace
from web.server import SESSIONS, SignupRequest, _run_account_creation_worker, app
from core.mailbox_pool import MailboxEntry


client = TestClient(app)


def test_get_accounts():
    response = client.get("/api/accounts")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_static_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "Grok & x.ai" in response.text


def _make_session(count=3):
    return {
        "id": "test-task",
        "status": "pending",
        "stage": "starting",
        "logs": [],
        "total_count": count,
        "current_index": 0,
        "success_count": 0,
        "failed_count": 0,
        "created_accounts": [],
        "stopped": False,
        "email": None,
        "error": None,
        "account": None,
    }


class _ShortfallPool:
    created = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _ShortfallPool.created.append(kwargs)

    def prepare(self):
        return 0

    def acquire(self, timeout=None):
        return None


def test_shortfall_warning_logged_when_pool_cannot_cover_count(monkeypatch):
    """When MailboxPool.prepare() returns fewer mailboxes than needed, the
    worker logs the serialized progress line and a shortfall warning, keeps
    dispatching every requested thread, and the excess threads fail cleanly
    via the `if mailbox is None` path instead of being silently dropped."""
    monkeypatch.setattr("web.server.MailboxPool", _ShortfallPool)
    _ShortfallPool.created = []
    req = SignupRequest(
        use_tempmail=True,
        count=3,
        threads=2,
        proxy_mode="rotating",
        rotating_proxy_key=None,
    )
    sess = _make_session(count=3)
    SESSIONS["test-task"] = sess
    try:
        _run_account_creation_worker("test-task", req)
    finally:
        SESSIONS.pop("test-task", None)

    assert len(_ShortfallPool.created) == 1
    pool_kwargs = _ShortfallPool.created[0]
    assert pool_kwargs["count"] == 3
    assert pool_kwargs["proxy_mgr"] is None
    assert pool_kwargs["stopped"]() is False
    logs = "\n".join(sess["logs"])
    assert "Đang tạo hòm thư Temp-Mail #1/3 (serialized)..." in logs
    assert "Bắt đầu tiến trình tạo 3 tài khoản Grok / x.ai..." in logs
    assert "Cảnh báo" in logs
    assert "0/3" in logs
    assert "không đủ hòm thư Temp-Mail" in logs
    assert sess["total_count"] == 3
    assert sess["failed_count"] == 3
    assert sess["success_count"] == 0
    assert sess["status"] == "failed"
    assert sess["error"] == "Tất cả các lượt tạo đều thất bại."


class _PartialPool:
    def __init__(self, **kwargs):
        self.entries = [
            MailboxEntry(email="user1@tempmail.org", token="t1", proxy=None),
            MailboxEntry(email="user2@tempmail.org", token="t2", proxy=None),
        ]

    def prepare(self):
        return len(self.entries)

    def acquire(self, timeout=None):
        return self.entries.pop(0) if self.entries else None


class _FakeEngine:
    def __init__(self, **kwargs):
        pass

    def close(self):
        pass


class _FakeCreator:
    def __init__(self, engine=None, **kwargs):
        self.page = SimpleNamespace()

    def start_signup(self, **kwargs):
        pass

    def submit_otp(self, **kwargs):
        pass

    def complete_registration(self, **kwargs):
        return SimpleNamespace(
            sso_cookie="c",
            user_id="u-1",
            to_dict=lambda: {"email": "user1@tempmail.org", "user_id": "u-1"},
        )


class _FakeTempMail:
    provider = "tempmail.org"

    def __init__(self, **kwargs):
        self.token = None

    def set_token(self, token):
        self.token = token

    def fetch_otp_code(self, timeout_sec=120, page=None):
        return "123456"


def test_partial_shortfall_excess_thread_records_failure(monkeypatch):
    """prepare() returns 2 mailboxes for count=3: all 3 threads are dispatched,
    the 2 mailbox-backed threads succeed, and the excess thread fails with the
    'không đủ hòm thư' message instead of being silently dropped."""
    monkeypatch.setattr("web.server.MailboxPool", _PartialPool)
    monkeypatch.setattr("web.server.StealthEngine", _FakeEngine)
    monkeypatch.setattr("web.server.AccountCreator", _FakeCreator)
    monkeypatch.setattr("web.server.TempMailClient", _FakeTempMail)
    monkeypatch.setattr("web.server.save_account", lambda *a, **k: None)
    req = SignupRequest(
        use_tempmail=True,
        count=3,
        threads=2,
        proxy_mode="rotating",
        rotating_proxy_key=None,
    )
    sess = _make_session(count=3)
    SESSIONS["test-task"] = sess
    try:
        _run_account_creation_worker("test-task", req)
    finally:
        SESSIONS.pop("test-task", None)

    logs = "\n".join(sess["logs"])
    assert "Bắt đầu tiến trình tạo 3 tài khoản Grok / x.ai..." in logs
    assert "Cảnh báo: Chỉ tạo được 2/3 hòm thư Temp-Mail." in logs
    assert "Thất bại: không đủ hòm thư Temp-Mail." in logs
    assert sess["total_count"] == 3
    assert sess["success_count"] == 2
    assert sess["failed_count"] == 1
    assert sess["status"] == "success"


class _InlinePool:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.entries = [MailboxEntry(email="inline@tempmail.org", token="t-inline", proxy=None)]

    def prepare(self):
        return len(self.entries)

    def acquire(self, timeout=None):
        return self.entries.pop(0) if self.entries else None


def test_single_thread_tempmail_uses_inline_pool_no_precreate(monkeypatch):
    """For a single-thread web tempmail run, no mailbox pool is pre-created;
    the inline path creates exactly one MailboxPool(count=1)."""
    created = []

    def _recording_pool(**kwargs):
        created.append(kwargs)
        return _InlinePool(**kwargs)

    monkeypatch.setattr("web.server.MailboxPool", _recording_pool)
    monkeypatch.setattr("web.server.StealthEngine", _FakeEngine)
    monkeypatch.setattr("web.server.AccountCreator", _FakeCreator)
    monkeypatch.setattr("web.server.TempMailClient", _FakeTempMail)
    monkeypatch.setattr("web.server.save_account", lambda *a, **k: None)
    req = SignupRequest(
        use_tempmail=True,
        count=1,
        threads=1,
        proxy_mode="rotating",
        rotating_proxy_key=None,
    )
    sess = _make_session(count=1)
    SESSIONS["test-task"] = sess
    try:
        _run_account_creation_worker("test-task", req)
    finally:
        SESSIONS.pop("test-task", None)

    assert len(created) == 1
    assert created[0]["count"] == 1
    assert sess["success_count"] == 1
    assert sess["status"] == "success"
