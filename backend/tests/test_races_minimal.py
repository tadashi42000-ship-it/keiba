from fastapi.testclient import TestClient

from app.api.v1 import races as races_api
from app.main import app


client = TestClient(app)


def test_upcoming_races_minimal(monkeypatch) -> None:
    observed: dict[str, int] = {}

    def _mock_get_upcoming_races(months_ahead, days_ahead, days_back):
        observed["months_ahead"] = months_ahead
        observed["days_ahead"] = days_ahead
        observed["days_back"] = days_back
        return [
            {
                "race_name": "桜花賞",
                "grade": "G1",
                "date_str": "2026/04/12(日)",
                "date_iso": "2026-04-12",
                "venue": "阪神",
                "distance": "1600m",
                "surface": "芝",
                "race_id": "202609020611",
                "race_key": "2026-04-12_阪神_桜花賞",
            }
        ]

    monkeypatch.setattr(
        races_api,
        "get_upcoming_races",
        _mock_get_upcoming_races,
    )

    response = client.get(
        "/api/v1/races/upcoming",
        params={"months_ahead": 2, "days_ahead": 14, "days_back": 7},
    )
    assert response.status_code == 200
    data = response.json()
    assert "races" in data
    assert data["races"][0]["race_name"] == "桜花賞"
    assert observed == {"months_ahead": 2, "days_ahead": 14, "days_back": 7}


def test_resolve_race_id_not_found(monkeypatch) -> None:
    monkeypatch.setattr(races_api, "resolve_race_id_by_key", lambda **kwargs: None)
    response = client.get("/api/v1/races/resolve-id", params={"race_key": "missing"})
    assert response.status_code == 404


def test_fetch_csv_minimal(monkeypatch) -> None:
    monkeypatch.setattr(races_api, "fetch_race_csv_file", lambda **kwargs: "backend/data/race_202605010811.csv")
    response = client.post("/api/v1/races/fetch-csv", json={"race_id": "202605010811"})
    assert response.status_code == 200
    data = response.json()
    assert data["race_id"] == "202605010811"
    assert "csv_path" in data


def test_odds_minimal(monkeypatch) -> None:
    monkeypatch.setattr(
        races_api,
        "fetch_odds_for_race",
        lambda **kwargs: {
            "race_id": "202605010811",
            "source_csv": "backend/data/race_202605010811.csv",
            "horses": [{"horse_name": "テストホース", "umaban": "1", "odds": 3.2}],
        },
    )
    response = client.get("/api/v1/races/202605010811/odds")
    assert response.status_code == 200
    data = response.json()
    assert data["race_id"] == "202605010811"
    assert len(data["horses"]) == 1


def test_characteristics_minimal(monkeypatch) -> None:
    monkeypatch.setattr(
        races_api,
        "get_minimal_race_characteristics_by_key",
        lambda **kwargs: {
            "race_key": "2026-04-20_中山_皐月賞",
            "race_id": "202606030811",
            "race_name": "皐月賞",
            "grade": "G1",
            "venue": "中山",
            "distance": "2000m",
            "surface": "芝",
            "characteristics": {
                "コース特徴": "中山競馬場 芝2000m",
                "注目ポイント": "G1レース",
            },
        },
    )

    response = client.get("/api/v1/races/characteristics", params={"race_key": "2026-04-20_中山_皐月賞"})
    assert response.status_code == 200
    data = response.json()
    assert data["race_name"] == "皐月賞"
    assert data["characteristics"]["コース特徴"] == "中山競馬場 芝2000m"


def test_characteristics_not_found(monkeypatch) -> None:
    monkeypatch.setattr(races_api, "get_minimal_race_characteristics_by_key", lambda **kwargs: None)
    response = client.get("/api/v1/races/characteristics", params={"race_key": "missing"})
    assert response.status_code == 404


def test_cache_get_minimal(monkeypatch) -> None:
    monkeypatch.setattr(
        races_api,
        "get_race_cache_by_key",
        lambda race_key: {
            "race_key": race_key,
            "cache_path": "legacy/streamlit_app/data/search_cache/test.json",
            "exists": True,
            "meta": {"race_key": race_key},
            "data": {"meta": {"race_key": race_key}, "web_raw": []},
        },
    )
    response = client.get("/api/v1/races/cache", params={"race_key": "2026-04-20_中山_皐月賞"})
    assert response.status_code == 200
    data = response.json()
    assert data["exists"] is True
    assert data["meta"]["race_key"] == "2026-04-20_中山_皐月賞"


def test_cache_put_minimal(monkeypatch) -> None:
    monkeypatch.setattr(
        races_api,
        "save_race_cache_by_key",
        lambda race_key, payload: {
            "race_key": race_key,
            "cache_path": "legacy/streamlit_app/data/search_cache/test.json",
            "saved_at": "2026-04-15T12:00:00",
        },
    )
    response = client.put(
        "/api/v1/races/cache",
        params={"race_key": "2026-04-20_中山_皐月賞"},
        json={"payload": {"meta": {"race_key": "2026-04-20_中山_皐月賞"}, "web_raw": []}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["race_key"] == "2026-04-20_中山_皐月賞"
    assert data["saved_at"] == "2026-04-15T12:00:00"


def test_cache_put_validation_error(monkeypatch) -> None:
    def _raise_validation_error(race_key, payload):
        raise ValueError("cache payload has unsupported top-level keys: debug")

    monkeypatch.setattr(races_api, "save_race_cache_by_key", _raise_validation_error)
    response = client.put(
        "/api/v1/races/cache",
        params={"race_key": "2026-04-20_中山_皐月賞"},
        json={"payload": {"meta": {}, "debug": {"raw": "x"}}},
    )
    assert response.status_code == 422
    assert "unsupported top-level keys" in response.json()["detail"]
