import pytest
from fastapi.testclient import TestClient

from dashboard.main import app


@pytest.fixture(name="client")
def client_fixture():
    return TestClient(app)


def test_admin_users_requires_login(client):
    response = client.get("/admin/users", follow_redirects=False)
    assert response.status_code == 303
    assert "/login" in response.headers.get("location", "")
