from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "keiba-api"


def test_v1_health() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) >= {"status", "service", "version"}


def test_sample() -> None:
    response = client.get("/api/v1/sample")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) >= {"message", "generated_at", "sample_items"}
    assert isinstance(data["sample_items"], list)
