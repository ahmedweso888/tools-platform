from fastapi.testclient import TestClient

from src.server.app import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_tools_health():
    response = client.get("/health/tools")
    assert response.status_code == 200
    assert "sprix_financial_literacy" in response.json()
    assert "qureo_auto_solver" in response.json()

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["name"] == "tools-platform"
