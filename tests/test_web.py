from fastapi.testclient import TestClient
from web.server import app


client = TestClient(app)


def test_get_accounts():
    response = client.get("/api/accounts")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_static_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "Grok & x.ai" in response.text
