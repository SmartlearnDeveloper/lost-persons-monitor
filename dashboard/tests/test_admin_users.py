import pytest
from fastapi.testclient import TestClient

from dashboard.main import app


@pytest.fixture(name="client")
def client_fixture():
    return TestClient(app)


def test_admin_users_page_loads(client):
    response = client.get("/admin/users")
    assert response.status_code == 200
    assert "Usuarios registrados" in response.text


def test_admin_users_api_returns_payload(client):
    response = client.get("/admin/api/users")
    assert response.status_code == 200
    assert "items" in response.json()
