from fastapi.testclient import TestClient
from web.server import SESSIONS, SignupRequest, _run_account_creation_worker, app


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


def test_shortfall_warning_logged_when_pool_cannot_cover_count(monkeypatch):
    """When MailboxPool.prepare() returns fewer mailboxes than needed, the
    worker logs the serialized progress line and a shortfall warning, then
    bails out before dispatching any threads."""
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
    assert "Cảnh báo" in logs
    assert "0/3" in logs
    assert "không đủ hòm thư" in logs
    assert sess["status"] == "failed"
    assert sess["error"] == "Không đủ hòm thư Temp-Mail."
