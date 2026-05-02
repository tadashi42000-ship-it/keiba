from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

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


def test_get_upcoming_races_supports_days_back_window(monkeypatch, tmp_path) -> None:
    calls: list[dict] = []
    empty_legacy_cache = tmp_path / "legacy_cache"
    empty_root_cache = tmp_path / "root_cache"
    empty_legacy_cache.mkdir()
    empty_root_cache.mkdir()
    monkeypatch.setattr(race_service, "CACHE_DIR_LEGACY", empty_legacy_cache)
    monkeypatch.setattr(race_service, "CACHE_DIR_ROOT", empty_root_cache)

    sample_race = _DummyRace(
        race_name="桜花賞",
        grade="G1",
        date_str="2026/04/12(日)",
        date=date(2026, 4, 12),
        venue="阪神",
        distance="1600m",
        surface="芝",
        race_id=None,
        race_key="2026-04-12_阪神_桜花賞",
    )

    def _fake_get_upcoming_races(*args, **kwargs):
        calls.append(kwargs)
        return [sample_race]

    monkeypatch.setattr(race_service, "legacy_get_upcoming_races", _fake_get_upcoming_races)

    result = race_service.get_upcoming_races(months_ahead=2, days_ahead=14, days_back=7)

    assert len(result) == 1
    assert result[0]["race_name"] == "桜花賞"
    assert calls, "legacy_get_upcoming_races should be called"
    assert calls[0]["months_ahead"] == 2
    assert calls[0]["days_ahead"] == 21
    assert calls[0]["from_date"] == date.today() - timedelta(days=7)


def test_get_upcoming_races_adds_cached_races_for_past_window(monkeypatch, tmp_path) -> None:
    legacy_cache = tmp_path / "legacy_cache"
    root_cache = tmp_path / "root_cache"
    legacy_cache.mkdir()
    root_cache.mkdir()

    # one race from cache within the past window
    target_date = date.today() - timedelta(days=3)
    cache_name = f"{target_date.isoformat()}_阪神_桜花賞.json"
    (legacy_cache / cache_name).write_text('{"meta": {}}', encoding="utf-8")

    monkeypatch.setattr(race_service, "CACHE_DIR_LEGACY", legacy_cache)
    monkeypatch.setattr(race_service, "CACHE_DIR_ROOT", root_cache)
    monkeypatch.setattr(race_service, "legacy_get_upcoming_races", lambda **kwargs: [])

    result = race_service.get_upcoming_races(months_ahead=1, days_ahead=7, days_back=7)
    keys = {item["race_key"] for item in result}
    assert f"{target_date.isoformat()}_阪神_桜花賞" in keys
