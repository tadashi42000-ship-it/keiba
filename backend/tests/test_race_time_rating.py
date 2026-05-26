from __future__ import annotations

import pytest

from app.services import race_time_rating


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1:38.3", 98.3),
        ("2:00.5", 120.5),
        ("37.2", 37.2),
        ("32.48", 32.48),
        ("-", None),
        ("NA", None),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_parse_race_time_to_seconds(value: str | None, expected: float | None) -> None:
    assert race_time_rating.parse_race_time_to_seconds(value) == expected


def test_load_course_records_reads_tokyo_turf_2000() -> None:
    records = race_time_rating.load_course_records()
    record = records["Tokyo|Turf|2000"]
    assert record["recordTimeSec"] == 115.2
    assert record["horseName"] == "Equinox"


def test_load_last3f_records_prefers_fastest_and_supports_outer() -> None:
    records = race_time_rating.load_last3f_records()
    assert records["Tokyo|Turf|1600"]["record3fSec"] == 32.6
    assert records["Niigata|Turf|1600-Outer"]["record3fSec"] == 31.4


@pytest.mark.parametrize(
    ("raw_time", "expected"),
    [
        ("1:40.0", "S"),
        ("1:40.5", "S"),
        ("1:41.2", "A"),
        ("1:42.0", "B"),
        ("1:43.0", "C"),
        ("1:43.1", "D"),
    ],
)
def test_evaluate_race_time_grade_boundaries(monkeypatch: pytest.MonkeyPatch, raw_time: str, expected: str) -> None:
    monkeypatch.setattr(
        race_time_rating,
        "load_course_records",
        lambda: {"Tokyo|Turf|1600": {"recordTimeSec": 100.0, "horseName": "R", "jockey": "J", "date": "D"}},
    )
    result = race_time_rating.evaluate_race_time(raw_time, "東京", "芝", 1600, "良", 57.0)
    assert result["grade"] == expected


def test_evaluate_race_time_minus_diff_is_s(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        race_time_rating,
        "load_course_records",
        lambda: {"Tokyo|Turf|1600": {"recordTimeSec": 100.0, "horseName": "R", "jockey": "J", "date": "D"}},
    )
    result = race_time_rating.evaluate_race_time("1:39.8", "東京", "芝", 1600, "良", 57.0)
    assert result["grade"] == "S"


def test_evaluate_race_time_handles_missing_record_and_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(race_time_rating, "load_course_records", lambda: {})
    no_record = race_time_rating.evaluate_race_time("1:40.0", "札幌", "芝", 1500, "良", 57.0)
    no_time = race_time_rating.evaluate_race_time(None, "東京", "芝", 1600, "良", 57.0)
    assert no_record["grade"] == "-"
    assert no_record["reason"] == "レコード未収録"
    assert no_time["grade"] == "-"


def test_evaluate_race_time_applies_track_and_weight_adjustments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        race_time_rating,
        "load_course_records",
        lambda: {"Tokyo|Dirt|1600": {"recordTimeSec": 100.0, "horseName": "R", "jockey": "J", "date": "D"}},
    )
    dirt_soft = race_time_rating.evaluate_race_time("1:40.0", "東京", "ダ", 1600, "重", 57.0)
    heavy_weight = race_time_rating.evaluate_race_time("1:40.0", "東京", "ダ", 1600, "良", 58.0)
    assert dirt_soft["adjustments"]["trackAdjustmentSec"] == -0.4
    assert dirt_soft["correctedRaceTimeSec"] == 100.4
    assert heavy_weight["adjustments"]["weightAdjustmentSec"] == 0.15
    assert heavy_weight["correctedRaceTimeSec"] == 99.85


@pytest.mark.parametrize(
    ("last3f", "expected"),
    [
        ("32.7", "S"),
        ("33.0", "S"),
        ("33.5", "A"),
        ("34.2", "B"),
        ("35.2", "C"),
        ("35.3", "D"),
    ],
)
def test_evaluate_last3f_grade_boundaries(monkeypatch: pytest.MonkeyPatch, last3f: str, expected: str) -> None:
    monkeypatch.setattr(
        race_time_rating,
        "load_last3f_records",
        lambda: {"Tokyo|Turf|1600": {"record3fSec": 32.7, "horseName": "R", "jockey": "J", "date": "D"}},
    )
    result = race_time_rating.evaluate_last3f(last3f, "東京", "芝", 1600, None)
    assert result["grade"] == expected
    assert "last3fRank" not in result


def test_evaluate_last3f_handles_missing_record_time_and_outer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        race_time_rating,
        "load_last3f_records",
        lambda: {"Niigata|Turf|1600-Outer": {"record3fSec": 31.4, "horseName": "R", "jockey": "J", "date": "D"}},
    )
    outer = race_time_rating.evaluate_last3f("31.6", "新潟", "芝", 1600, "Outer")
    no_record = race_time_rating.evaluate_last3f("34.0", "札幌", "芝", 1500, None)
    no_time = race_time_rating.evaluate_last3f(None, "東京", "芝", 1600, None)
    assert outer["grade"] == "S"
    assert no_record["grade"] == "-"
    assert no_record["reason"] == "レコード未収録"
    assert no_time["grade"] == "-"


def test_evaluate_last3f_specification_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        race_time_rating,
        "load_last3f_records",
        lambda: {"Tokyo|Turf|1600": {"record3fSec": 32.7, "horseName": "R", "jockey": "J", "date": "D"}},
    )
    result = race_time_rating.evaluate_last3f("33.0", "東京", "芝", 1600)
    assert result["grade"] == "S"
