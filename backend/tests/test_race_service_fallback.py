from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.services import race_service


@dataclass
class _DummyRace:
    race_name: str
    grade: str
    date_str: str
    date: date
    venue: str
    distance: str
    surface: str
    race_id: str | None
    race_key: str
    special_url: str = ""


def test_resolve_race_id_by_key_uses_date_fallback(monkeypatch) -> None:
    target_key = "2026-04-06_阪神_大阪杯"
    target_race = _DummyRace(
        race_name="大阪杯",
        grade="G1",
        date_str="2026/04/06(日)",
        date=date(2026, 4, 6),
        venue="阪神",
        distance="2000m",
        surface="芝",
        race_id="202609020411",
        race_key=target_key,
    )
    calls: list[dict] = []

    def _fake_get_upcoming_races(*args, **kwargs):
        calls.append(kwargs)
        if kwargs.get("from_date") is None:
            return []
        return [target_race]

    monkeypatch.setattr(race_service, "legacy_get_upcoming_races", _fake_get_upcoming_races)
    monkeypatch.setattr(race_service, "legacy_resolve_race_id", lambda race: race.race_id)

    result = race_service.resolve_race_id_by_key(target_key, months_ahead=2, days_ahead=30)

    assert result is not None
    assert result["race_key"] == target_key
    assert result["race_id"] == "202609020411"
    assert result["resolved"] is True
    assert any(call.get("from_date") is not None for call in calls)


def test_characteristics_by_key_uses_fallback_window(monkeypatch) -> None:
    target_key = "2026-04-06_阪神_大阪杯"
    target_race = _DummyRace(
        race_name="大阪杯",
        grade="G1",
        date_str="2026/04/06(日)",
        date=date(2026, 4, 6),
        venue="阪神",
        distance="2000m",
        surface="芝",
        race_id="202609020411",
        race_key=target_key,
    )
    calls: list[dict] = []

    def _fake_get_upcoming_races(*args, **kwargs):
        calls.append(kwargs)
        if kwargs.get("from_date") is None:
            return []
        return [target_race]

    monkeypatch.setattr(race_service, "legacy_get_upcoming_races", _fake_get_upcoming_races)

    result = race_service.get_minimal_race_characteristics_by_key(target_key)

    assert result is not None
    assert result["race_key"] == target_key
    assert result["characteristics"]["コース特徴"] == "阪神競馬場 芝2000m"
    assert any(call.get("from_date") is not None for call in calls)


def test_fetch_odds_for_race_detects_japanese_columns(monkeypatch, tmp_path) -> None:
    csv_path = tmp_path / "race_202600000001.csv"
    df = pd.DataFrame(
        [
            {"枠番": "1", "馬番": "1", "馬名": "テストホースA", "オッズ": "3.4"},
            {"枠番": "1", "馬番": "2", "馬名": "テストホースB", "オッズ": "5.1"},
        ]
    )
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    monkeypatch.setattr(race_service, "fetch_race_csv_file", lambda race_id: str(csv_path))

    result = race_service.fetch_odds_for_race("202600000001")
    assert result["race_id"] == "202600000001"
    assert len(result["horses"]) == 2
    assert result["horses"][0]["horse_name"] == "テストホースA"
    assert result["horses"][0]["umaban"] == "1"
    assert result["horses"][0]["waku"] == "1"
    assert result["horses"][0]["odds"] == 3.4


def test_fetch_odds_for_race_converts_nan_text_fields_to_none(monkeypatch, tmp_path) -> None:
    csv_path = tmp_path / "race_202600000002.csv"
    df = pd.DataFrame(
        [
            {"枠番": float("nan"), "馬番": float("nan"), "馬名": "テストホース", "オッズ": "---.-"},
        ]
    )
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    monkeypatch.setattr(race_service, "fetch_race_csv_file", lambda race_id: str(csv_path))

    result = race_service.fetch_odds_for_race("202600000002")
    assert len(result["horses"]) == 1
    assert result["horses"][0]["horse_name"] == "テストホース"
    assert result["horses"][0]["umaban"] is None
    assert result["horses"][0]["waku"] is None
    assert result["horses"][0]["odds"] is None
