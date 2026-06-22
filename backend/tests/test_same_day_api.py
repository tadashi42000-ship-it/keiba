from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from app.api.v1 import races as races_api
from app.main import app
from app.services import same_day_service
from app.services import shosho_signals
from app.services import sire_aptitude
from app.services.track_bias import compute_track_bias
import same_day_sources


client = TestClient(app)


@dataclass
class _Race:
    race_name: str
    grade: str
    date_str: str
    date: date
    venue: str
    distance: str
    surface: str
    race_id: str
    race_key: str
    race_number: str


def test_same_day_races_endpoint(monkeypatch) -> None:
    rows = [
        _Race("3歳未勝利", "平場", "2026/04/26(日)", date(2026, 4, 26), "東京", "2400m", "芝", "202605020204", "k4", "4R"),
        _Race("3歳未勝利", "平場", "2026/04/26(日)", date(2026, 4, 26), "京都", "1800m", "芝", "202608020205", "k5", "5R"),
    ]
    monkeypatch.setattr(same_day_service, "legacy_fetch_races_by_date", lambda target_date: rows)
    monkeypatch.setattr(
        same_day_service,
        "legacy_group_races_by_venue",
        lambda races: {"東京": [rows[0]], "京都": [rows[1]]},
    )

    response = client.get("/api/v1/races/same-day", params={"date": "2026-04-26", "venue": "東京"})
    assert response.status_code == 200
    data = response.json()
    assert data["races"][0]["race_number"] == "4R"
    assert data["races"][0]["race_id"] == "202605020204"


def test_same_day_venue_normalizes_mojibake(monkeypatch) -> None:
    rows = [
        _Race("3歳未勝利", "平場", "2026/04/26(日)", date(2026, 4, 26), "東京", "2400m", "芝", "202605020204", "k4", "4R"),
    ]
    monkeypatch.setattr(same_day_service, "legacy_fetch_races_by_date", lambda target_date: rows)
    monkeypatch.setattr(same_day_service, "legacy_group_races_by_venue", lambda races: {"東京": list(races)})
    mojibake = "東京".encode("utf-8").decode("latin1")

    response = client.get("/api/v1/races/same-day", params={"date": "2026-04-26", "venue": mojibake})

    assert response.status_code == 200
    data = response.json()
    assert data["venue"] == "東京"
    assert data["races"][0]["venue"] == "東京"


def test_entry_endpoint_style_distribution_and_field_size_fallback(monkeypatch, tmp_path) -> None:
    csv_path = tmp_path / "race_202605020204.csv"
    df = pd.DataFrame(
        [
            {"馬名": "先行馬", "馬番": "1", "枠番": "1", "騎手": "A", "斤量": "57.0", "オッズ": "3.0"},
            {"馬名": "差し馬", "馬番": "2", "枠番": "2", "騎手": "B", "斤量": "57.0", "オッズ": "5.0"},
            {"馬名": "追込馬", "馬番": "3", "枠番": "3", "騎手": "C", "斤量": "57.0", "オッズ": "9.0"},
        ]
    )
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    monkeypatch.setattr(same_day_service, "BACKEND_DATA_DIR", tmp_path)
    monkeypatch.setattr(same_day_service, "legacy_fetch_race_csv", lambda race_id, output_file: str(csv_path))
    monkeypatch.setattr(same_day_service, "legacy_fetch_race_metadata", lambda race_id: {"start_time": "11:35"})
    monkeypatch.setattr(
        same_day_service,
        "legacy_fetch_recent_runs",
        lambda race_id: {
            "先行馬": {"corners": ["3-3-3-3"], "field_sizes": ["14"], "last3fs": ["35.0"]},
            "差し馬": {"corners": ["6-6-6-6"], "field_sizes": ["14"], "last3fs": ["35.5"]},
            "追込馬": {"corners": ["8-8-8-8"], "last3fs": ["36.0"]},
        },
    )

    response = client.get("/api/v1/races/202605020204/entry")
    assert response.status_code == 200
    data = response.json()
    assert data["style_distribution"]["先行"] == 1
    assert data["style_distribution"]["差し"] == 1
    assert data["style_distribution"]["追込"] == 1
    assert data["horses"][0]["field_sizes"] == ["14", "", ""]


def test_course_stats_endpoint_frame_table(monkeypatch) -> None:
    monkeypatch.setattr(same_day_service, "build_requests_session", lambda: object())
    monkeypatch.setattr(
        same_day_service,
        "fetch_course_stats",
        lambda venue, distance, surface, session: {
            "race_list_url": "https://example.test",
            "sample_race_count": 2,
            "frame_stats": [
                {"label": "1枠", "starts": 10, "wins": 2, "top3": 4, "outside_top3": 6, "win_rate": 20.0, "top3_rate": 40.0, "outside_top3_rate": 60.0}
            ],
            "style_stats": [{"label": "先行", "starts": 10, "top3": 5, "top3_rate": 50.0}],
            "popularity_stats": [],
            "pace_tendency": "バランス",
        },
    )

    response = client.get(
        "/api/v1/races/202605020204/course-stats",
        params={"venue": "東京", "distance": "2400m", "surface": "芝"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["schema_version"] == "same_day_course_stats_v3"
    assert "| 枠 | 1着 | 複勝 | それ以外 | 出走数 |" in data["frame_markdown"]
    assert data["frame_stats"][0]["wins"] == 2


def test_bet_plan_provisional_when_umaban_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        same_day_service,
        "get_entry_snapshot",
        lambda race_id: {
            "race_id": race_id,
            "horses": [
                {"horse_name": "候補A", "umaban": "", "waku": "", "odds": 2.5, "style": "先行", "recent_runs": ["26/01/01 2 テスト"]},
                {"horse_name": "候補B", "umaban": "", "waku": "", "odds": 8.0, "style": "差し", "recent_runs": []},
            ],
            "warnings": [],
        },
    )

    response = client.post("/api/v1/races/202605020204/bet-plan", json={"budget_yen": 3000})
    assert response.status_code == 200
    data = response.json()
    assert data["provisional_only"] is True
    assert data["tickets"] == []
    assert data["ranking"][0]["horse_name"] == "候補A"



def test_same_day_sheet_endpoint(monkeypatch) -> None:
    race = {
        "race_name": "3????",
        "grade": "??",
        "date_str": "2026/04/26(?)",
        "date_iso": "2026-04-26",
        "venue": "??",
        "distance": "2400m",
        "surface": "?",
        "race_id": "202605020204",
        "race_key": "2026-04-26_??_3????_4R",
        "race_number": "4R",
    }
    monkeypatch.setattr(
        races_api,
        "build_same_day_sheet_snapshot",
        lambda target_date, venue, budget_yen=3000, refresh=False: {
            "generated_at": "2026-04-26T01:30:00",
            "date": target_date.isoformat(),
            "venue": venue,
            "race_count": 1,
            "races": [
                {
                    "race": race,
                    "entry": {
                        "race_id": "202605020204",
                        "source_csv": "race.csv",
                        "horses": [],
                        "style_distribution": {},
                        "style_distribution_label": "",
                        "warnings": [],
                    },
                    "course_stats": {
                        "race_id": "202605020204",
                        "schema_version": "same_day_course_stats_v3",
                        "frame_stats": [],
                        "style_stats": [],
                        "popularity_stats": [],
                    },
                    "bet_plan": {
                        "race_id": "202605020204",
                        "budget_yen": budget_yen,
                        "provisional_only": False,
                        "ranking": [],
                        "tickets": [],
                        "warnings": [],
                    },
                    "error": "",
                }
            ],
        },
    )

    response = client.get("/api/v1/races/same-day-sheet", params={"date": "2026-04-26", "venue": "??"})
    assert response.status_code == 200
    data = response.json()
    assert data["race_count"] == 1
    assert data["races"][0]["race"]["race_number"] == "4R"
    assert data["races"][0]["bet_plan"]["provisional_only"] is False


def test_same_day_sheet_volatile_refresh_endpoint(monkeypatch) -> None:
    race = {
        "race_name": "3????",
        "grade": "??",
        "date_str": "2026/04/26(?)",
        "date_iso": "2026-04-26",
        "venue": "??",
        "distance": "2400m",
        "surface": "?",
        "race_id": "202605020204",
        "race_key": "2026-04-26_??_3????_4R",
        "race_number": "4R",
    }
    captured = {}

    def fake_refresh(target_date, venue, budget_yen=3000, race_id=None, race_number=None):
        captured.update(
            {
                "target_date": target_date.isoformat(),
                "venue": venue,
                "budget_yen": budget_yen,
                "race_id": race_id,
                "race_number": race_number,
            }
        )
        return {
            "generated_at": "2026-04-26T01:31:00",
            "date": target_date.isoformat(),
            "venue": venue,
            "race_count": 1,
            "races": [
                {
                    "race": race,
                    "entry": {
                        "race_id": "202605020204",
                        "source_csv": "race.csv",
                        "odds_updated_at": "14:01",
                        "horses": [{"horse_name": "A", "umaban": "1", "odds": 3.2}],
                        "style_distribution": {},
                        "style_distribution_label": "",
                        "warnings": [],
                    },
                    "course_stats": None,
                    "bet_plan": {
                        "race_id": "202605020204",
                        "budget_yen": budget_yen,
                        "provisional_only": False,
                        "ranking": [],
                        "tickets": [],
                        "warnings": [],
                    },
                    "track_bias": None,
                    "error": "",
                }
            ],
        }

    monkeypatch.setattr(races_api, "refresh_same_day_sheet_volatile", fake_refresh)

    response = client.post(
        "/api/v1/races/same-day-sheet/refresh-volatile",
        params={"date": "2026-04-26", "venue": "??", "race_id": "202605020204", "race_number": "4R"},
        json={},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["generated_at"] == "2026-04-26T01:31:00"
    assert data["races"][0]["entry"]["odds_updated_at"] == "14:01"
    assert captured["race_id"] == "202605020204"
    assert captured["race_number"] == "4R"


def test_extract_netkeiba_api_odds_maps_horse_names() -> None:
    payload = {
        "status": "OK",
        "data": {
            "horse_list": {
                "7": {"Bamei": "フレンチブラッサム"},
                "13": {"Bamei": "ブルーサーマル"},
            },
            "odds": {
                "1": {
                    "1": ["3.4", "x", "x", "7"],
                    "2": ["8.1", "x", "x", "13"],
                }
            },
        },
    }

    result = same_day_service._extract_netkeiba_api_odds(payload)

    assert result == {"フレンチブラッサム": 3.4, "ブルーサーマル": 8.1}


def test_extract_netkeiba_api_odds_maps_umaban_when_horse_list_missing() -> None:
    payload = {
        "status": "middle",
        "data": {
            "official_datetime": "2026-05-02 20:36:36",
            "odds": {
                "1": {
                    "01": ["57.0", 0, 13],
                    "15": ["1.6", 0, 1],
                }
            },
        },
    }

    result = same_day_service._extract_netkeiba_api_odds(payload)

    assert result == {"__umaban__:1": 57.0, "__umaban__:15": 1.6}


def test_merge_odds_into_horses_by_umaban() -> None:
    horses = [
        {"horse_name": "スーパーガール", "umaban": "1", "odds": None},
        {"horse_name": "チームユートピア", "umaban": "15", "odds": None},
    ]

    same_day_service._merge_odds_into_horses(horses, {"__umaban__:1": 57.0, "__umaban__:15": 1.6})

    assert horses[0]["odds"] == 57.0
    assert horses[1]["odds"] == 1.6


def test_recent_run_details_are_added_without_replacing_legacy_fields() -> None:
    df = pd.DataFrame(
        [
            {
                "horse_name": "Sample Horse",
                "umaban": "7",
                "waku": "4",
                "jockey": "Tester",
                "weight": "57.0",
                "odds": "3.4",
            }
        ]
    )
    recent_runs = {
        "Sample Horse": {
            "前走": "26/04/01 1 3歳未勝利 ダ1400/良",
            "2走前": "26/03/01 4 3歳未勝利 ダ1400/稍",
            "3走前": "",
            "last3fs": ["36.8", "37.4", ""],
            "corners": ["3-3", "5-5", ""],
            "field_sizes": ["16", "16", ""],
        }
    }
    run_details = {
        "Sample Horse": [
            {"race_time": "1:26.4", "margin": "0.0", "time_index": 86.0},
            {"race_time": "1:27.6", "margin": "0.9", "time_index": 74.0},
        ]
    }

    horses = same_day_service._build_entry_horses(df, recent_runs, run_details)

    assert horses[0]["recent_runs"][0].startswith("26/04/01")
    assert horses[0]["last3fs"][0] == "36.8"
    assert horses[0]["recent_run_details"][0]["race_time"] == "1:26.4"
    assert horses[0]["recent_run_details"][0]["race_level"] == "A"
    assert "distance_m" in horses[0]["recent_run_details"][0]
    assert "carried_weight" in horses[0]["recent_run_details"][0]
    assert "race_time_grade" in horses[0]["recent_run_details"][0]
    assert "last3f_grade" in horses[0]["recent_run_details"][0]
    assert horses[0]["recent_run_details"][1]["race_level"] == "C"


def test_time_level_bonus_is_small_and_absent_when_no_index() -> None:
    bonus, reason = same_day_service._time_level_bonus(
        [
            {"time_index": 92.0},
            {"time_index": 82.0},
            {"time_index": 74.0},
        ]
    )
    assert 0 < bonus <= 0.12
    assert reason == "指数A"

    empty_bonus, empty_reason = same_day_service._time_level_bonus([{"time_index": None}])
    assert empty_bonus == 0
    assert empty_reason == ""


def test_body_weight_bucket_boundaries() -> None:
    cases = [
        (439, "~439"),
        (440, "440-459"),
        (459, "440-459"),
        (460, "460-479"),
        (479, "460-479"),
        (480, "480-499"),
        (499, "480-499"),
        (500, "500-519"),
        (519, "500-519"),
        (520, "520+"),
    ]
    for weight, expected in cases:
        assert same_day_service._classify_body_weight_bucket(weight) == expected


def test_parse_result_table_stats_collects_body_weight_buckets() -> None:
    rows = []
    weights = ["438(+2)", "445(-2)", "462(+0)", "481(+4)", "506(-6)", "522(+8)", "468(+2)", "489(-4)"]
    finishes = [1, 2, 3, 4, 5, 6, 1, 2]
    for idx, (weight, finish) in enumerate(zip(weights, finishes), start=1):
        rows.append(
            f"<tr><td>{finish}</td><td>{(idx % 8) + 1}</td><td>{idx}</td><td>3-3</td><td>{weight}</td></tr>"
        )
    html = (
        "<table class='race_table_01'>"
        "<tr><th>着順</th><th>枠番</th><th>人気</th><th>通過</th><th>馬体重</th></tr>"
        + "".join(rows)
        + "</table>"
    )

    parsed = same_day_sources._parse_result_table_stats(html)

    assert parsed["body_total"]["460-479"] == 2
    assert parsed["body_top3"]["460-479"] == 2
    assert parsed["body_wins"]["~439"] == 1


def test_parse_result_table_rows_include_bias_metadata() -> None:
    html = (
        "<table class='race_table_01'>"
        "<tr><th>着順</th><th>枠番</th><th>馬番</th><th>通過</th><th>人気</th><th>上り</th><th>馬体重</th></tr>"
        "<tr><td>1</td><td>1</td><td>2</td><td>1-1</td><td>3</td><td>34.1</td><td>468(+2)</td></tr>"
        "</table>"
    )
    rows = same_day_sources._parse_result_table_rows(
        html,
        race_id="202605021011",
        race_meta={
            "date": "2026-05-24",
            "venue": "東京",
            "surface": "芝",
            "distance_m": 2400,
            "race_number": "11R",
        },
    )

    assert rows == [
        {
            "race_id": "202605021011",
            "date": "2026-05-24",
            "venue": "東京",
            "surface": "芝",
            "distance_m": 2400,
            "race_number": "11R",
            "finish_pos": 1,
            "waku": 1,
            "umaban": 2,
            "style": "逃げ",
            "popularity": 3,
            "last3f": "34.1",
            "body_weight": "468(+2)",
        }
    ]


def test_compute_track_bias_high_low_and_fallback() -> None:
    today_rows = []
    for race_no in range(1, 6):
        race_id = f"r{race_no}"
        for waku in range(1, 9):
            today_rows.append(
                {
                    "race_id": race_id,
                    "date": "2026-05-24",
                    "venue": "東京",
                    "surface": "芝",
                    "distance_m": 1600,
                    "race_number": f"{race_no}R",
                    "finish_pos": 1 if waku == 1 else (2 if waku == 2 else (3 if waku == 3 else 8)),
                    "waku": waku,
                    "style": "先行" if waku <= 3 else "追込",
                }
            )

    high = compute_track_bias(today_rows, [], "芝", 1600, min_samples=5, target_race_number="6R")
    assert high["confidence"] in {"medium", "high"}
    assert high["frame_bias"]["inner"] > high["frame_bias"]["outer"]
    assert "内枠有利" in high["summary_label"]

    low = compute_track_bias(today_rows[:8], [], "芝", 1600, min_samples=5, target_race_number="2R")
    assert low["confidence"] == "low"
    assert low["summary_label"] == "サンプル不足（1R）"

    fallback = compute_track_bias(today_rows, [], "芝", 2400, min_samples=5, target_race_number="6R")
    assert fallback["fallback_used"] is True
    assert fallback["summary_label"]


def test_track_bias_bonus_and_rank_baseline_are_independent() -> None:
    horse = {"horse_name": "A", "umaban": "1", "waku": "1", "style": "先行", "odds": 5.0, "recent_runs": [], "recent_run_details": []}
    bias = {
        "frame_bias": {"inner": 0.55, "outer": 0.20},
        "style_bias": {"逃げ": 0.1, "先行": 0.55, "差し": 0.2, "追込": 0.1},
        "sample_size": 5,
        "fallback_used": False,
        "summary_label": "内枠有利 / 先行有利",
        "confidence": "high",
    }

    bonus, reason = same_day_service._track_bias_bonus(horse, bias)
    assert bonus > 0
    assert "内枠有利" in reason

    base = same_day_service._rank_horses([horse], track_bias=None)[0]
    current = same_day_service._rank_horses([horse], track_bias=bias)[0]
    assert base["bias_bonus"] == 0
    assert current["bias_bonus"] == bonus
    assert current["score"] > base["score"]
    assert "バイアス" in current["reason"]


def test_same_day_sheet_cache_requires_track_bias_layers() -> None:
    snapshot = {
        "track_bias_schema_version": same_day_service.TRACK_BIAS_SCHEMA_VERSION,
        "shosho_schema_version": shosho_signals.SHOSHO_SCHEMA_VERSION,
        "races": [
            {
                "track_bias": None,
                "entry": {
                    "horses": [
                        {
                            "recent_run_details": [],
                            "body_weight_bucket": "",
                            "body_weight_source": "",
                            "sire_name": "父",
                            "sire_aptitude_summary": "◎",
                            "broodmare_sire_name": "母父",
                            "sire_aptitude_notes": "",
                        }
                    ]
                },
                "bet_plan": {"ranking": [{"baseline_score": 0.1, "bias_bonus": 0.0, "value_score": 0.6, "is_value_top5": True, "danger_flags": []}]},
            }
        ],
    }
    assert same_day_service._same_day_sheet_has_recent_run_details(snapshot) is True

    missing_race_layer = json.loads(json.dumps(snapshot))
    del missing_race_layer["races"][0]["track_bias"]
    assert same_day_service._same_day_sheet_has_recent_run_details(missing_race_layer) is False

    missing_ranking_layer = json.loads(json.dumps(snapshot))
    del missing_ranking_layer["races"][0]["bet_plan"]["ranking"][0]["bias_bonus"]
    assert same_day_service._same_day_sheet_has_recent_run_details(missing_ranking_layer) is False

    stale_shosho_layer = json.loads(json.dumps(snapshot))
    stale_shosho_layer["shosho_schema_version"] = "old"
    assert same_day_service._same_day_sheet_has_recent_run_details(stale_shosho_layer) is False


def test_refresh_true_keeps_good_cache_when_rebuild_is_empty(monkeypatch, tmp_path) -> None:
    cached = {
        "generated_at": "2026-06-21T08:00:00",
        "date": "2026-06-21",
        "venue": "東京",
        "race_count": 1,
        "track_bias_schema_version": same_day_service.TRACK_BIAS_SCHEMA_VERSION,
        "shosho_schema_version": shosho_signals.SHOSHO_SCHEMA_VERSION,
        "races": [
            {
                "race": {
                    "race_name": "3歳未勝利",
                    "grade": "平場",
                    "date_str": "2026/06/21(日)",
                    "date_iso": "2026-06-21",
                    "venue": "東京",
                    "distance": "1600m",
                    "surface": "芝",
                    "race_id": "202605030101",
                    "race_key": "2026-06-21_東京_3歳未勝利_1R",
                    "race_number": "1R",
                },
                "entry": {
                    "race_id": "202605030101",
                    "source_csv": "race.csv",
                    "horses": [{"horse_name": "A", "umaban": "1", "odds": 3.0, "recent_run_details": []}],
                    "style_distribution": {},
                    "style_distribution_label": "",
                    "warnings": [],
                },
                "course_stats": None,
                "bet_plan": {"race_id": "202605030101", "budget_yen": 3000, "provisional_only": False, "ranking": [], "tickets": [], "warnings": []},
                "track_bias": None,
                "error": "",
            }
        ],
    }
    monkeypatch.setattr(same_day_service, "SAME_DAY_SHEET_DIR", tmp_path)
    same_day_service._save_same_day_sheet_cache(cached)
    monkeypatch.setattr(same_day_service, "get_same_day_races", lambda target_date, venue=None: {"date": target_date.isoformat(), "venue": venue or "", "venues": [], "races": []})
    monkeypatch.setattr(same_day_service, "_collect_track_bias_result_pools", lambda **kwargs: ([], []))
    monkeypatch.setattr(same_day_service, "_fetch_jra_entry_map", lambda *args, **kwargs: ({}, ""))

    result = same_day_service.build_same_day_sheet_snapshot(date(2026, 6, 21), "東京", refresh=True)
    saved = json.loads((tmp_path / "2026-06-21_東京_same_day_sheet.json").read_text(encoding="utf-8"))

    assert result["races"][0]["entry"]["horses"]
    assert result["refresh_skipped_reason"]
    assert saved["races"][0]["entry"]["horses"]


def test_shosho_ev_curve_boundaries() -> None:
    assert shosho_signals.ev_curve(None) == 0.0
    assert shosho_signals.ev_curve(1.8) == -0.20
    assert shosho_signals.ev_curve(3.9) == 0.20
    assert shosho_signals.ev_curve(9.9) == 0.60
    assert shosho_signals.ev_curve(10.0) == 0.35
    assert shosho_signals.ev_curve(30.0) == 0.08


def test_shosho_danger_penalty_applies_only_to_popular_horses() -> None:
    race = {
        "race_name": "テスト",
        "grade": "",
        "date_iso": "2026-05-03",
        "venue": "東京",
        "distance": "1600m",
        "surface": "芝",
    }
    front_run_detail = {
        "date": "26/04/01",
        "finish": "1",
        "corner": "1-1-1-1",
        "field_size": "16",
        "surface": "芝",
        "distance_m": 1600,
        "going": "良",
    }
    horses = [
        {"horse_name": "人気逃げ", "umaban": "1", "waku": "1", "odds": 3.0, "style": "逃げ", "recent_runs": [], "recent_run_details": [front_run_detail]},
        {"horse_name": "中位A", "umaban": "2", "waku": "2", "odds": 4.2, "style": "先行", "recent_runs": [], "recent_run_details": []},
        {"horse_name": "中位B", "umaban": "3", "waku": "3", "odds": 6.0, "style": "先行", "recent_runs": [], "recent_run_details": []},
        {"horse_name": "中位C", "umaban": "4", "waku": "4", "odds": 8.0, "style": "差し", "recent_runs": [], "recent_run_details": []},
        {"horse_name": "人気薄逃げ", "umaban": "5", "waku": "5", "odds": 20.0, "style": "逃げ", "recent_runs": [], "recent_run_details": [front_run_detail]},
    ]

    plan = same_day_service._build_bet_plan_from_entry({"race_id": "r1", "horses": horses, "warnings": []}, race=race)
    by_name = {item["horse_name"]: item for item in plan["ranking"]}

    assert by_name["人気逃げ"]["danger_flags"]
    assert by_name["人気逃げ"]["danger_penalty_applied"] is True
    assert by_name["人気薄逃げ"]["danger_flags"]
    assert by_name["人気薄逃げ"]["danger_penalty_applied"] is False
    assert by_name["人気薄逃げ"]["value_score"] == shosho_signals.ev_curve(20.0) + 0.05


def test_shosho_unpublished_odds_recommendations_degrade_to_note() -> None:
    plan = same_day_service._build_bet_plan_from_entry(
        {
            "race_id": "r1",
            "horses": [
                {"horse_name": "A", "umaban": "1", "waku": "1", "odds": None, "style": "先行", "recent_runs": [], "recent_run_details": []},
                {"horse_name": "B", "umaban": "2", "waku": "2", "odds": None, "style": "差し", "recent_runs": [], "recent_run_details": []},
            ],
            "warnings": [],
        },
        race={"race_name": "テスト", "date_iso": "2026-05-03", "venue": "東京", "distance": "1600m", "surface": "芝"},
    )

    assert plan["recommendations"]["tickets"] == []
    assert "オッズ未公開" in plan["recommendations"]["note"]


def test_shosho_axis_score_is_odds_independent_and_clamped() -> None:
    ranked = same_day_service._rank_horses(
        [
            {"horse_name": "低オッズ", "umaban": "1", "waku": "1", "odds": 2.0, "style": "先行", "recent_runs": [], "recent_run_details": []},
            {"horse_name": "高オッズ", "umaban": "2", "waku": "2", "odds": 30.0, "style": "先行", "recent_runs": [], "recent_run_details": []},
        ]
    )
    by_name = {item["horse_name"]: item for item in ranked}

    assert by_name["低オッズ"]["axis_score"] == by_name["高オッズ"]["axis_score"]
    assert shosho_signals.axis_score(0.1, -20) == -0.2


def test_bet_plan_schema_keeps_shosho_fields() -> None:
    from app.schemas.races import BetPlanResponse

    plan = same_day_service._build_bet_plan_from_entry(
        {
            "race_id": "r1",
            "horses": [{"horse_name": "妙味馬", "umaban": "1", "waku": "1", "odds": 6.0, "style": "先行", "recent_runs": ["26/01/01 5 テスト"], "recent_run_details": []}],
            "warnings": [],
        },
        race={"race_name": "テスト", "date_iso": "2026-05-03", "venue": "東京", "distance": "1600m", "surface": "芝"},
    )

    modeled = BetPlanResponse(**plan).model_dump()
    assert modeled["ranking"][0]["value_score"] is not None
    assert modeled["ranking"][0]["is_value_top5"] is True
    assert "danger_flags" in modeled["ranking"][0]
    assert "hatsuran_do" in modeled["recommendations"]["race_shape"]
    assert modeled["recommendations"]["tickets"]
    assert modeled["shosho_schema_version"] == shosho_signals.SHOSHO_SCHEMA_VERSION


def test_shosho_recommend_bets_point_limits() -> None:
    ctx = shosho_signals.ShoshoRaceContext(
        race_name="2歳ハンデ",
        is_handicap=True,
        is_two_year_old=True,
        odds_available=True,
    )
    ranked = [
        {"horse_name": "軸A", "umaban": "1", "odds": 3.0, "axis_score": 0.45, "value_score": 0.12, "axis_demerit_total": 0, "danger_flags": [], "value_flags": [], "danger_penalty_applied": False},
        {"horse_name": "妙味A", "umaban": "2", "odds": 6.0, "axis_score": 0.25, "value_score": 0.70, "axis_demerit_total": 0, "danger_flags": [], "value_flags": [{"code": "x", "label": "穴", "weight": 0.1}], "danger_penalty_applied": False},
        {"horse_name": "妙味B", "umaban": "3", "odds": 8.0, "axis_score": 0.22, "value_score": 0.68, "axis_demerit_total": 0, "danger_flags": [], "value_flags": [{"code": "x", "label": "穴", "weight": 0.1}], "danger_penalty_applied": False},
        {"horse_name": "妙味C", "umaban": "4", "odds": 12.0, "axis_score": 0.20, "value_score": 0.42, "axis_demerit_total": 0, "danger_flags": [], "value_flags": [{"code": "x", "label": "穴", "weight": 0.1}], "danger_penalty_applied": False},
        {"horse_name": "相手D", "umaban": "5", "odds": 18.0, "axis_score": 0.18, "value_score": 0.30, "axis_demerit_total": 0, "danger_flags": [], "value_flags": [], "danger_penalty_applied": False},
    ]

    recommendations = shosho_signals.recommend_bets(ranked, ctx, 3000)
    by_type = {ticket["type"]: ticket for ticket in recommendations["tickets"]}

    assert {"単勝", "ワイド", "馬連", "3連複"}.issubset(by_type)
    assert by_type["馬連"]["max_points"] == 6
    assert by_type["3連複"]["max_points"] <= 6
    assert recommendations["race_shape"]["trio_policy"] == "shrink"


def test_shosho_trio_18_point_formation() -> None:
    ranked = []
    odds = [2.1, 3.4, 4.2, 5.1, 6.2, 7.4, 11.0, 13.0, 16.0, 19.0, 22.0, 28.0]
    values = [0.1, 0.82, 0.66, 0.42, 0.78, 0.76, 0.50, 0.49, 0.48, 0.47, 0.20, 0.10]
    for idx, (odd, value) in enumerate(zip(odds, values), start=1):
        ranked.append(
            {
                "horse_name": f"馬{idx}",
                "umaban": str(idx),
                "odds": odd,
                "axis_score": 0.5 - idx * 0.01,
                "value_score": value,
                "axis_demerit_total": 0,
                "danger_flags": [],
                "value_flags": [{"code": "v", "label": "妙味", "weight": 0.02}],
                "danger_penalty_applied": False,
            }
        )
    ctx = shosho_signals.ShoshoRaceContext(
        race_name="テストハンデ",
        is_handicap=True,
        odds_available=True,
        odds_rank_by_key={shosho_signals.horse_key(item): rank for rank, item in enumerate(ranked, start=1)},
    )

    recommendations = shosho_signals.recommend_bets(ranked, ctx, 3000)
    trio = next(ticket for ticket in recommendations["tickets"] if ticket["type"] == "3連複")
    combos = [tuple(selection.split("-")) for selection in trio["selection"].split(",")]

    assert trio["strategy"] == "3連複18点鉄板"
    assert trio["point_note"] == "18点"
    assert len(combos) == 18
    assert len(set(combos)) == 18
    assert all(len(set(combo)) == 3 for combo in combos)
    assert all("2" in combo for combo in combos)
    assert not all("1" in combo for combo in combos)


def test_shosho_trio_falls_back_when_odds_rank_missing() -> None:
    ctx = shosho_signals.ShoshoRaceContext(race_name="テストハンデ", is_handicap=True, odds_available=True)
    ranked = [
        {
            "horse_name": f"馬{idx}",
            "umaban": str(idx),
            "odds": 4.0 + idx,
            "axis_score": 0.5 - idx * 0.01,
            "value_score": 0.58 - idx * 0.02,
            "axis_demerit_total": 0,
            "danger_flags": [],
            "value_flags": [{"code": "v", "label": "妙味", "weight": 0.02}],
            "danger_penalty_applied": False,
        }
        for idx in range(1, 9)
    ]

    recommendations = shosho_signals.recommend_bets(ranked, ctx, 3000)
    trio = next(ticket for ticket in recommendations["tickets"] if ticket["type"] == "3連複")

    assert trio["strategy"] == "3連複荒れ回収"
    assert len(trio["selection"].split(",")) <= 20


def test_shosho_trio_stops_when_hatsuran_is_extreme() -> None:
    ctx = shosho_signals.ShoshoRaceContext(
        race_name="2歳ハンデ",
        is_handicap=True,
        is_two_year_old=True,
        odds_available=True,
    )
    ranked = [
        {
            "horse_name": f"馬{idx}",
            "umaban": str(idx),
            "odds": 3.5 + idx,
            "axis_score": 0.4 - idx * 0.01,
            "value_score": 0.76 - idx * 0.01,
            "axis_demerit_total": 0,
            "danger_flags": [],
            "value_flags": [{"code": "v", "label": "妙味", "weight": 0.02}],
            "danger_penalty_applied": False,
        }
        for idx in range(1, 10)
    ]

    recommendations = shosho_signals.recommend_bets(ranked, ctx, 3000)

    assert recommendations["race_shape"]["hatsuran_do"] >= shosho_signals.TRIO_HATSURAN_STOP
    assert recommendations["race_shape"]["trio_policy"] == "stop"
    assert all(ticket["type"] != "3連複" for ticket in recommendations["tickets"])


def test_shosho_race_shape_metrics_and_pace_pattern() -> None:
    solid_ranked = [
        {"horse_name": "堅軸", "umaban": "1", "odds": 1.5, "axis_score": 0.5, "value_score": -0.2, "danger_flags": [], "value_flags": [], "danger_penalty_applied": False},
        {"horse_name": "相手", "umaban": "2", "odds": 4.0, "axis_score": 0.2, "value_score": 0.4, "danger_flags": [], "value_flags": [], "danger_penalty_applied": False},
    ]
    solid = shosho_signals.recommend_bets(
        solid_ranked,
        shosho_signals.ShoshoRaceContext(odds_available=True, style_distribution={"逃げ": 1, "先行": 1}, field_size=10),
        3000,
    )["race_shape"]

    rough_ranked = [
        {"horse_name": "危険人気", "umaban": "1", "odds": 2.8, "axis_score": 0.2, "value_score": 0.1, "danger_flags": [{"code": "d", "label": "危険", "weight": 0.08}], "value_flags": [], "danger_penalty_applied": True},
        {"horse_name": "妙味1", "umaban": "2", "odds": 5.0, "axis_score": 0.3, "value_score": 0.72, "danger_flags": [], "value_flags": [{"code": "v", "label": "妙味", "weight": 0.02}], "danger_penalty_applied": False},
        {"horse_name": "妙味2", "umaban": "3", "odds": 6.0, "axis_score": 0.2, "value_score": 0.70, "danger_flags": [], "value_flags": [{"code": "v", "label": "妙味", "weight": 0.02}], "danger_penalty_applied": False},
        {"horse_name": "妙味3", "umaban": "4", "odds": 8.0, "axis_score": 0.1, "value_score": 0.68, "danger_flags": [], "value_flags": [{"code": "v", "label": "妙味", "weight": 0.02}], "danger_penalty_applied": False},
    ]
    rough = shosho_signals.recommend_bets(
        rough_ranked,
        shosho_signals.ShoshoRaceContext(
            odds_available=True,
            style_distribution={"逃げ": 3, "先行": 4, "差し": 2},
            field_size=9,
        ),
        3000,
    )["race_shape"]
    biased = shosho_signals.recommend_bets(
        rough_ranked,
        shosho_signals.ShoshoRaceContext(
            odds_available=True,
            style_distribution={"逃げ": 1, "先行": 1, "差し": 6},
            field_size=8,
            track_bias={"summary_label": "内枠有利 / 先行有利", "confidence": "high"},
        ),
        3000,
    )["race_shape"]

    assert 0 <= solid["hatsuran_do"] <= 1
    assert 0 <= rough["hatsuran_do"] <= 1
    assert solid["hatsuran_do"] < rough["hatsuran_do"]
    assert 0 <= rough["axis_place_prob"] <= 1
    assert rough["aite_confidence"] in {"A", "B", "C"}
    assert rough["pace_pattern"] == "前潰れ"
    assert biased["pace_pattern"] == "TB重視"


def test_bet_plan_marks_value_top5() -> None:
    horses = [
        {"horse_name": f"馬{idx}", "umaban": str(idx), "waku": str((idx % 8) + 1), "odds": odd, "style": "先行", "recent_runs": [], "recent_run_details": []}
        for idx, odd in enumerate([1.8, 3.0, 4.5, 5.5, 7.0, 9.0, 12.0], start=1)
    ]
    plan = same_day_service._build_bet_plan_from_entry(
        {"race_id": "r-value", "horses": horses, "warnings": []},
        race={"race_name": "テスト", "date_iso": "2026-05-03", "venue": "東京", "distance": "1600m", "surface": "芝"},
    )
    expected = {
        (item["umaban"], item["horse_name"])
        for item in sorted(plan["ranking"], key=lambda row: row["value_score"], reverse=True)[:5]
    }
    actual = {(item["umaban"], item["horse_name"]) for item in plan["ranking"] if item["is_value_top5"]}

    assert actual == expected


def test_body_weight_bonus_is_small_and_sample_guarded() -> None:
    course_stats = {
        "body_weight_stats": [
            {"label": "440-459", "starts": 8, "top3_rate": 12.5},
            {"label": "460-479", "starts": 12, "top3_rate": 42.0},
            {"label": "480-499", "starts": 10, "top3_rate": 30.0},
        ]
    }
    plus, reason = same_day_service._body_weight_bonus(
        {"body_weight_bucket": "460-479", "body_weight_source": "current"},
        course_stats,
    )
    minus, low_reason = same_day_service._body_weight_bonus(
        {"body_weight_bucket": "440-459", "body_weight_source": "previous"},
        course_stats,
    )
    guarded, guarded_reason = same_day_service._body_weight_bonus(
        {"body_weight_bucket": "520+", "body_weight_source": "current"},
        {"body_weight_stats": [{"label": "520+", "starts": 3, "top3_rate": 80.0}]},
    )

    assert plus == 0.04
    assert "馬体重460-479" in reason
    assert minus == -0.02
    assert "前走" in low_reason
    assert guarded == 0
    assert guarded_reason == ""


def test_sire_context_reads_generic_track_condition_from_race_data() -> None:
    context = same_day_service._sire_context_from_metadata(
        {"race_data01": "11:30発走 / 芝1600m (左 B) / 天候:曇 / 馬場:重"},
        venue="東京",
        surface="芝",
        distance="1600m",
    )

    assert context["going"] == "重"


def test_sire_aptitude_bonus_affects_bet_ranking_reason() -> None:
    ranked = same_day_service._rank_horses(
        [
            {
                "horse_name": "血統良",
                "umaban": "1",
                "waku": "1",
                "odds": 10.0,
                "style": "",
                "recent_runs": [],
                "recent_run_details": [],
                "sire_data_available": True,
                "sire_aptitude_summary": "◎",
                "sire_aptitude_score": 9,
                "sire_aptitude_max_score": 9,
                "broodmare_sire_data_available": True,
                "broodmare_sire_aptitude_summary": "◎",
                "broodmare_sire_aptitude_score": 9,
                "broodmare_sire_aptitude_max_score": 9,
            },
            {
                "horse_name": "血統弱",
                "umaban": "2",
                "waku": "2",
                "odds": 10.0,
                "style": "",
                "recent_runs": [],
                "recent_run_details": [],
                "sire_data_available": True,
                "sire_aptitude_summary": "×",
                "sire_aptitude_score": 0,
                "sire_aptitude_max_score": 9,
                "broodmare_sire_data_available": True,
                "broodmare_sire_aptitude_summary": "×",
                "broodmare_sire_aptitude_score": 0,
                "broodmare_sire_aptitude_max_score": 9,
            },
        ]
    )

    assert ranked[0]["horse_name"] == "血統良"
    assert "血統◎ 9/9" in ranked[0]["reason"]
    assert "母父◎ 9/9" in ranked[0]["reason"]


def test_sire_aptitude_bonus_is_conservative() -> None:
    full_strength = {
        "sire_data_available": True,
        "sire_aptitude_summary": "◎",
        "sire_aptitude_score": 9,
        "sire_aptitude_max_score": 9,
        "broodmare_sire_data_available": True,
        "broodmare_sire_aptitude_summary": "◎",
        "broodmare_sire_aptitude_score": 9,
        "broodmare_sire_aptitude_max_score": 9,
    }
    sire_bonus, _ = same_day_service._sire_aptitude_bonus(full_strength)
    broodmare_bonus, _ = same_day_service._broodmare_sire_aptitude_bonus(full_strength)

    assert sire_bonus == 0.084
    assert broodmare_bonus == 0.03
    assert broodmare_bonus < sire_bonus / 2


def test_sire_aptitude_bonus_penalizes_weak_and_low_confidence() -> None:
    weak = {
        "sire_data_available": True,
        "sire_aptitude_summary": "×",
        "sire_aptitude_score": 0,
        "sire_aptitude_max_score": 9,
        "broodmare_sire_data_available": True,
        "broodmare_sire_aptitude_summary": "×",
        "broodmare_sire_aptitude_score": 0,
        "broodmare_sire_aptitude_max_score": 9,
    }
    shallow = {
        "sire_data_available": True,
        "sire_aptitude_summary": "◎",
        "sire_aptitude_score": 3,
        "sire_aptitude_max_score": 3,
    }
    neutralish = {
        "sire_data_available": True,
        "sire_aptitude_summary": "△",
        "sire_aptitude_score": 3,
        "sire_aptitude_max_score": 9,
    }

    assert same_day_service._sire_aptitude_bonus(weak)[0] == -0.048
    assert same_day_service._broodmare_sire_aptitude_bonus(weak)[0] == -0.022
    assert same_day_service._sire_aptitude_bonus(shallow)[0] == 0.042
    assert same_day_service._sire_aptitude_bonus(neutralish)[0] == -0.004


def test_sire_aptitude_bonus_uses_more_weight_when_recent_evidence_is_thin() -> None:
    strong = {
        "sire_data_available": True,
        "sire_aptitude_summary": "◎",
        "sire_aptitude_score": 9,
        "sire_aptitude_max_score": 9,
    }
    with_history = {
        **strong,
        "recent_runs": ["1 3 東京 芝1600", "2 5 東京 芝1600", "3 7 中山 芝1600"],
        "recent_run_details": [{"finish": "3"}, {"finish": "5"}, {"finish": "7"}],
    }
    one_run = {
        **strong,
        "recent_runs": ["1 3 東京 芝1600"],
        "recent_run_details": [{"finish": "3"}],
    }

    assert same_day_service._sire_aptitude_bonus(with_history)[0] == 0.07
    assert same_day_service._sire_aptitude_bonus(one_run)[0] == 0.077
    assert same_day_service._sire_aptitude_bonus(strong)[0] == 0.084


def test_apply_body_weight_stats_keeps_small_sample_for_display_only() -> None:
    horses = [{"horse_name": "大型馬", "body_weight": "528", "recent_run_details": []}]
    course_stats = {"body_weight_stats": [{"label": "520+", "starts": 3, "top3_rate": 66.7}]}

    same_day_service._apply_body_weight_stats_to_horses(horses, course_stats)
    bonus, reason = same_day_service._body_weight_bonus(horses[0], course_stats)

    assert horses[0]["body_weight_bucket"] == "520+"
    assert horses[0]["body_weight_top3_rate"] == 66.7
    assert bonus == 0
    assert reason == ""


def test_evaluate_sire_aptitude_excludes_going_on_firm() -> None:
    result = sire_aptitude.evaluate_sire_aptitude("キタサンブラック", "芝", 2400, "東京", "良")

    assert result["sire_data_available"] is True
    assert result["marks"]["surface"] == "◎"
    assert result["marks"]["distance"] == "◎"
    assert result["marks"]["course_shape"] == "◎"
    assert "going" not in result["marks"]
    assert result["summary_mark"] == "◎"


def test_evaluate_sire_aptitude_includes_going_on_soft() -> None:
    result = sire_aptitude.evaluate_sire_aptitude("キタサンブラック", "芝", 2400, "東京", "重")

    assert result["sire_data_available"] is True
    assert result["marks"]["going"] == "○"
    assert result["max_score"] == 12


def test_evaluate_sire_aptitude_matches_netkeiba_name_with_english_suffix() -> None:
    result = sire_aptitude.evaluate_sire_aptitude("ドレフォン Drefong(米)", "ダ", 1600, "東京", "良")

    assert result["sire_data_available"] is True
    assert result["marks"]["surface"] == "◎"


def test_evaluate_sire_aptitude_matches_english_only_alias() -> None:
    result = sire_aptitude.evaluate_sire_aptitude("Frankel", "芝", 1600, "東京", "良")

    assert result["sire_data_available"] is True
    assert result["marks"]["surface"] == "◎"
    assert result["marks"]["distance"] == "◎"


def test_horse_sire_persistent_cache_avoids_second_fetch(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "horse_sires_cache.json"
    calls = {"count": 0}

    def fake_fetch(horse_id: str, session=None):
        calls["count"] += 1
        return {"sire_name": "キタサンブラック", "broodmare_sire_name": "キングヘイロー"}

    monkeypatch.setattr(same_day_service, "HORSE_SIRES_CACHE_PATH", cache_path)
    monkeypatch.setattr(same_day_service, "legacy_fetch_horse_pedigree", fake_fetch)
    monkeypatch.setattr(same_day_service, "legacy_fetch_horse_sire", lambda horse_id, session=None: "")
    same_day_service._fetch_horse_pedigree_cached.cache_clear()
    same_day_service._fetch_horse_sire_cached.cache_clear()

    assert same_day_service.get_horse_sire("2020104567") == "キタサンブラック"
    assert same_day_service.get_horse_sire("2020104567") == "キタサンブラック"
    assert same_day_service.get_horse_pedigree("2020104567")["broodmare_sire_name"] == "キングヘイロー"
    assert calls["count"] == 1


def test_horse_pedigree_cache_keeps_legacy_sire_only_entry(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "horse_sires_cache.json"
    cache_path.write_text(
        json.dumps({"version": 1, "horses": {"2020104567": {"sire_name": "キタサンブラック"}}}, ensure_ascii=False),
        encoding="utf-8",
    )

    def fake_fetch(horse_id: str, session=None):
        return {"sire_name": "", "broodmare_sire_name": ""}

    monkeypatch.setattr(same_day_service, "HORSE_SIRES_CACHE_PATH", cache_path)
    monkeypatch.setattr(same_day_service, "legacy_fetch_horse_pedigree", fake_fetch)
    monkeypatch.setattr(same_day_service, "legacy_fetch_horse_sire", lambda horse_id, session=None: "")
    same_day_service._fetch_horse_pedigree_cached.cache_clear()
    same_day_service._fetch_horse_sire_cached.cache_clear()

    assert same_day_service.get_horse_pedigree("2020104567") == {
        "sire_name": "キタサンブラック",
        "broodmare_sire_name": "",
    }


def test_fetch_horse_sire_uses_pedigree_page_when_profile_has_no_blood_table(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_request_html(url: str, timeout: int = 12, session=None) -> str:
        requested_urls.append(url)
        if "/horse/ped/" in url:
            return """
            <table class="blood_table">
              <tr><td><a href="/horse/2015104961/">キタサンブラック</a></td></tr>
            </table>
            """
        return "<html><body>profile</body></html>"

    monkeypatch.setattr(same_day_sources, "_request_html", fake_request_html)

    assert same_day_sources.fetch_horse_sire("2020104567") == "キタサンブラック"
    assert requested_urls == [
        "https://db.netkeiba.com/horse/2020104567/",
        "https://db.netkeiba.com/horse/ped/2020104567/",
    ]


def test_fetch_horse_pedigree_reads_sire_and_broodmare_sire(monkeypatch) -> None:
    def fake_request_html(url: str, timeout: int = 12, session=None) -> str:
        return """
        <table class="blood_table">
          <tr><td rowspan="16"><a href="/horse/2015104961/">キタサンブラック 2012 鹿毛 [ 血統 ]</a></td></tr>
          <tr></tr><tr></tr><tr></tr><tr></tr><tr></tr><tr></tr><tr></tr>
          <tr></tr><tr></tr><tr></tr><tr></tr><tr></tr><tr></tr><tr></tr><tr></tr>
          <tr>
            <td rowspan="16"><a href="/horse/2015100000/">母馬</a></td>
            <td rowspan="8"><a href="/horse/1998101516/">キングヘイロー 1995 鹿毛 [ 血統 ][ 産駒 ]</a></td>
          </tr>
        </table>
        """

    monkeypatch.setattr(same_day_sources, "_request_html", fake_request_html)

    assert same_day_sources.fetch_horse_pedigree("2020104567") == {
        "sire_name": "キタサンブラック",
        "broodmare_sire_name": "キングヘイロー",
    }


def test_same_day_sheet_refresh_updates_only_odds_from_cache(monkeypatch, tmp_path) -> None:
    cached = {
        "generated_at": "2026-05-02T18:00:00",
        "date": "2026-05-03",
        "venue": "東京",
        "race_count": 1,
        "races": [
            {
                "race": {
                    "race_name": "3歳未勝利",
                    "grade": "平場",
                    "date_str": "2026/05/03(日)",
                    "date_iso": "2026-05-03",
                    "venue": "東京",
                    "distance": "1600m",
                    "surface": "ダ",
                    "race_id": "202605020401",
                    "race_key": "2026-05-03_東京_3歳未勝利_1R",
                    "race_number": "1R",
                },
                "entry": {
                    "race_id": "202605020401",
                    "source_csv": "race.csv",
                    "horses": [
                        {
                            "horse_name": "フレンチブラッサム",
                            "waku": "4",
                            "umaban": "7",
                            "sex_age": "",
                            "weight": "",
                            "body_weight": "",
                            "body_delta": "",
                            "body_weight_bucket": "",
                            "body_weight_source": "",
                            "body_weight_top3_rate": None,
                            "sire_name": "キタサンブラック",
                            "sire_data_available": True,
                            "sire_aptitude_marks": {"surface": "◎"},
                            "sire_aptitude_summary": "◎",
                            "sire_aptitude_score": 3,
                            "sire_aptitude_max_score": 3,
                            "sire_aptitude_notes": "東京向き",
                            "broodmare_sire_name": "キングヘイロー",
                            "broodmare_sire_data_available": True,
                            "broodmare_sire_aptitude_summary": "○",
                            "broodmare_sire_aptitude_score": 2,
                            "broodmare_sire_aptitude_max_score": 3,
                            "jockey": "",
                            "style": "先行",
                            "odds": None,
                            "recent_runs": [],
                            "last3fs": [],
                            "corners": [],
                            "field_sizes": [],
                            "recent_run_details": [],
                        }
                    ],
                    "style_distribution": {"先行": 1},
                    "style_distribution_label": "先行1",
                    "warnings": ["単勝オッズは未公開または取得できませんでした。当日公開後に手動更新してください。"],
                },
                "course_stats": None,
                "bet_plan": {"race_id": "202605020401", "budget_yen": 3000, "provisional_only": False, "ranking": [], "tickets": [], "warnings": []},
                "track_bias": None,
                "error": "",
            }
        ],
    }

    monkeypatch.setattr(same_day_service, "SAME_DAY_SHEET_DIR", tmp_path)
    same_day_service._save_same_day_sheet_cache(cached)
    monkeypatch.setattr(same_day_service, "_same_day_sheet_has_recent_run_details", lambda snapshot: True)
    monkeypatch.setattr(same_day_service, "_collect_track_bias_result_pools", lambda **kwargs: ([], []))
    monkeypatch.setattr(
        same_day_service,
        "_fetch_win_odds_map",
        lambda race_id, **kwargs: ({"フレンチブラッサム": 3.4}, "netkeiba odds API"),
    )
    monkeypatch.setattr(same_day_service, "_fetch_body_weight_map", lambda race_id: ({}, ""))
    monkeypatch.setattr(same_day_service, "_fetch_jra_entry_map", lambda *args, **kwargs: ({}, ""))
    monkeypatch.setattr(
        same_day_service,
        "legacy_fetch_race_metadata",
        lambda race_id: {"race_data01": "10:05発走 / ダ1600m / 馬場:良", "track_conditions": {"ダート": "良"}},
    )

    result = same_day_service.refresh_same_day_sheet_volatile(date(2026, 5, 3), "東京")

    entry = result["races"][0]["entry"]
    assert entry["horses"][0]["odds"] == 3.4
    assert entry["race_data01"] == "10:05発走 / ダ1600m / 馬場:良"
    assert entry["track_conditions"] == {"ダート": "良"}
    assert result["volatile_updated_count"] == 1
    assert not any("単勝オッズは未公開" in warning for warning in entry["warnings"])
    assert result["races"][0]["bet_plan"]["ranking"][0]["horse_name"] == "フレンチブラッサム"


def test_refresh_recalculates_body_weight_bucket_and_bet_reason(monkeypatch, tmp_path) -> None:
    cached = {
        "generated_at": "2026-05-02T18:00:00",
        "date": "2026-05-03",
        "venue": "東京",
        "race_count": 1,
        "races": [
            {
                "race": {
                    "race_name": "3歳未勝利",
                    "grade": "平場",
                    "date_str": "2026/05/03(日)",
                    "date_iso": "2026-05-03",
                    "venue": "東京",
                    "distance": "1600m",
                    "surface": "ダ",
                    "race_id": "202605020401",
                    "race_key": "2026-05-03_東京_3歳未勝利_1R",
                    "race_number": "1R",
                },
                "entry": {
                    "race_id": "202605020401",
                    "source_csv": "race.csv",
                    "horses": [
                        {
                            "horse_name": "フレンチブラッサム",
                            "waku": "4",
                            "umaban": "7",
                            "sex_age": "",
                            "weight": "",
                            "body_weight": "",
                            "body_delta": "",
                            "body_weight_bucket": "",
                            "body_weight_source": "",
                            "body_weight_top3_rate": None,
                            "sire_name": "キタサンブラック",
                            "sire_data_available": True,
                            "sire_aptitude_marks": {"surface": "◎"},
                            "sire_aptitude_summary": "◎",
                            "sire_aptitude_score": 3,
                            "sire_aptitude_max_score": 3,
                            "sire_aptitude_notes": "東京向き",
                            "broodmare_sire_name": "キングヘイロー",
                            "broodmare_sire_data_available": True,
                            "broodmare_sire_aptitude_summary": "○",
                            "broodmare_sire_aptitude_score": 2,
                            "broodmare_sire_aptitude_max_score": 3,
                            "jockey": "",
                            "style": "先行",
                            "odds": 3.4,
                            "recent_runs": [],
                            "last3fs": [],
                            "corners": [],
                            "field_sizes": [],
                            "recent_run_details": [],
                        }
                    ],
                    "style_distribution": {"先行": 1},
                    "style_distribution_label": "先行1",
                    "warnings": [],
                },
                "course_stats": {
                    "body_weight_stats": [
                        {"label": "460-479", "starts": 10, "top3_rate": 45.0},
                        {"label": "500-519", "starts": 10, "top3_rate": 10.0},
                    ]
                },
                "bet_plan": {"race_id": "202605020401", "budget_yen": 3000, "provisional_only": False, "ranking": [], "tickets": [], "warnings": []},
                "track_bias": None,
                "error": "",
            }
        ],
    }
    monkeypatch.setattr(same_day_service, "SAME_DAY_SHEET_DIR", tmp_path)
    same_day_service._save_same_day_sheet_cache(cached)
    monkeypatch.setattr(same_day_service, "_same_day_sheet_has_recent_run_details", lambda snapshot: True)
    monkeypatch.setattr(same_day_service, "_collect_track_bias_result_pools", lambda **kwargs: ([], []))
    monkeypatch.setattr(same_day_service, "_fetch_win_odds_map", lambda race_id, **kwargs: ({}, ""))
    monkeypatch.setattr(same_day_service, "_fetch_body_weight_map", lambda race_id: ({"フレンチブラッサム": ("468", "+2")}, ""))
    monkeypatch.setattr(same_day_service, "_fetch_jra_entry_map", lambda *args, **kwargs: ({}, ""))
    monkeypatch.setattr(
        same_day_service,
        "legacy_fetch_race_metadata",
        lambda race_id: {"race_data01": "10:05発走 / ダ1600m / 馬場:良", "track_conditions": {"ダート": "良"}},
    )

    result = same_day_service.refresh_same_day_sheet_volatile(date(2026, 5, 3), "東京")

    horse = result["races"][0]["entry"]["horses"][0]
    reason = result["races"][0]["bet_plan"]["ranking"][0]["reason"]
    assert horse["body_weight_bucket"] == "460-479"
    assert horse["body_weight_source"] == "current"
    assert horse["body_weight_top3_rate"] == 45.0
    assert "馬体重460-479複45%" in reason


def test_bet_plan_recommendations_change_when_odds_rank_changes() -> None:
    def make_plan(odds_values: list[float]) -> dict:
        styles = ["先行", "差し", "逃げ", "追込", "先行", "差し", "先行", "追込"]
        horses = [
            {
                "horse_name": f"Horse{i}",
                "umaban": str(i),
                "waku": str((i - 1) // 2 + 1),
                "odds": odds,
                "style": styles[i - 1],
                "recent_runs": ["26/01/01 3 テスト"],
                "recent_run_details": [],
            }
            for i, odds in enumerate(odds_values, start=1)
        ]
        return same_day_service._build_bet_plan_from_entry(
            {"race_id": "odds-change", "horses": horses, "warnings": []},
            race={"race_name": "テスト", "date_iso": "2026-05-03", "venue": "東京", "distance": "1600m", "surface": "芝"},
        )

    before = make_plan([2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 20.0, 30.0])
    after = make_plan([2.0, 20.0, 6.0, 8.0, 10.0, 12.0, 4.0, 30.0])

    before_selection = [ticket["selection"] for ticket in before["recommendations"]["tickets"]]
    after_selection = [ticket["selection"] for ticket in after["recommendations"]["tickets"]]
    assert before_selection != after_selection


def test_cache_entry_is_fresh_retries_past_empty_results_after_backoff() -> None:
    race_meta = {"date": (date.today() - timedelta(days=1)).isoformat()}
    old_empty = {
        "rows": [],
        "has_result": False,
        "fetched_at": (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds"),
    }
    recent_empty = {
        "rows": [],
        "has_result": False,
        "fetched_at": (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds"),
    }
    completed = {
        "rows": [{"finish_pos": 1}],
        "has_result": True,
        "fetched_at": (datetime.now() - timedelta(days=5)).isoformat(timespec="seconds"),
    }

    assert same_day_service._cache_entry_is_fresh(old_empty, race_meta, refresh=False) is False
    assert same_day_service._cache_entry_is_fresh(recent_empty, race_meta, refresh=False) is True
    assert same_day_service._cache_entry_is_fresh(completed, race_meta, refresh=False) is True


def test_win_odds_uses_jra_fallback_after_netkeiba_http_error(monkeypatch) -> None:
    class Response:
        status_code = 400
        encoding = "utf-8"
        text = ""

        def json(self) -> dict:
            return {}

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(same_day_service, "build_requests_session", lambda: Session())
    monkeypatch.setattr(
        same_day_service,
        "_fetch_jra_win_odds_map",
        lambda race_id, **kwargs: ({"Horse A": 4.2}, "JRA odds"),
    )

    odds, note = same_day_service._fetch_win_odds_map("202605030601", allow_jra_fallback=True)

    assert odds == {"Horse A": 4.2}
    assert note == "JRA odds"


def test_merge_jra_entry_into_horses_fills_numbers_odds_body_and_jockey() -> None:
    horses = [
        {
            "horse_name": "Horse A",
            "waku": "",
            "umaban": "",
            "odds": None,
            "body_weight": "",
            "body_delta": "",
            "jockey": "",
        }
    ]
    counts = same_day_service._merge_jra_entry_into_horses(
        horses,
        {
            "Horse A": {
                "waku": "3",
                "umaban": "5",
                "odds": 12.4,
                "body_weight": "476",
                "body_delta": "-6",
                "jockey": "Test Rider",
            }
        },
    )

    assert horses[0]["waku"] == "3"
    assert horses[0]["umaban"] == "5"
    assert horses[0]["odds"] == 12.4
    assert horses[0]["body_weight"] == "476"
    assert horses[0]["body_weight_source"] == "jra"
    assert horses[0]["body_delta"] == "-6"
    assert horses[0]["jockey"] == "Test Rider"
    assert counts == {"numbers": 2, "odds": 1, "body": 1, "jockey": 1}


def test_prune_resolved_entry_warnings_removes_stale_messages() -> None:
    entry = {
        "warnings": [
            "馬番/枠番が未確定です。正式な買い目番号は生成できません。",
            "単勝オッズは未公開または取得できませんでした。",
            "馬体重更新: RuntimeError",
            "keep this warning",
        ]
    }
    horses = [{"waku": "1", "umaban": "1", "odds": 3.5, "body_weight": "476"}]

    same_day_service._prune_resolved_entry_warnings(entry, horses)

    assert entry["warnings"] == ["keep this warning"]


def test_get_race_result_rows_uses_en_netkeiba_fallback(monkeypatch, tmp_path) -> None:
    class FakeResponse:
        status_code = 200
        text = """
        <html>
          <body>
            <table class="ResultRefund">
              <tr><th>Finish</th><th>Bracket</th><th>Horse No.</th><th>Horse</th><th>Sex/Age</th><th>Weight</th><th>Jockey</th><th>Time</th><th>Odds</th></tr>
              <tr><td>1</td><td>1</td><td>3</td><td>Alpha</td><td></td><td></td><td></td><td>1:35.0</td><td>12.3</td></tr>
              <tr><td>2</td><td>4</td><td>7</td><td>Beta</td><td></td><td></td><td></td><td>1:35.1</td><td>3.4</td></tr>
              <tr><td>3</td><td>8</td><td>15</td><td>Gamma</td><td></td><td></td><td></td><td>1:35.2</td><td>22.0</td></tr>
            </table>
            <table class="Corner_Num"><tr><td>4 Corner</td><td>3 7 15</td></tr></table>
          </body>
        </html>
        """

    class FakeSession:
        def get(self, url: str, **kwargs) -> FakeResponse:
            assert "en.netkeiba.com/race/race_result.html" in url
            return FakeResponse()

    monkeypatch.setattr(same_day_service, "TRACK_BIAS_RESULTS_CACHE_PATH", tmp_path / "track_bias_results_cache.json")
    monkeypatch.setattr(same_day_service, "build_requests_session", lambda: FakeSession())
    monkeypatch.setattr(same_day_service, "legacy_fetch_race_result_rows", lambda *args, **kwargs: [])

    rows = same_day_service.get_race_result_rows(
        "202605020401",
        {"date": "2026-05-03", "venue": "東京", "surface": "芝", "distance_m": 1600, "race_number": "1R"},
        refresh=True,
    )

    assert len(rows) == 3
    assert rows[0]["horse_name"] == "Alpha"
    assert rows[0]["style"] == "逃げ"
    assert rows[1]["popularity"] == 1
    assert rows[0]["odds"] == 12.3


def test_compute_track_bias_provisional_confidence() -> None:
    def race_rows(race_no: int) -> list[dict]:
        return [
            {
                "race_id": f"race-{race_no}",
                "race_number": f"{race_no}R",
                "surface": "芝",
                "distance_m": 1600,
                "finish_pos": finish,
                "waku": waku,
                "style": "先行" if waku <= 4 else "追込",
            }
            for finish, waku in enumerate([1, 2, 3, 5, 6, 7, 8, 4], start=1)
        ]

    three_races = [row for race_no in range(1, 4) for row in race_rows(race_no)]
    five_races = [row for race_no in range(1, 6) for row in race_rows(race_no)]

    provisional = compute_track_bias(three_races, [], "芝", 1600, min_samples=5, target_race_number="4R")
    medium = compute_track_bias(five_races, [], "芝", 1600, min_samples=5, target_race_number="6R")
    low = compute_track_bias(three_races[:16], [], "芝", 1600, min_samples=5, target_race_number="3R")

    assert provisional["confidence"] == "provisional"
    assert provisional["summary_label"].startswith("暫定（3R）")
    assert medium["confidence"] in {"medium", "high"}
    assert low["confidence"] == "low"


def test_track_bias_bonus_provisional_is_small_but_active() -> None:
    horse = {"horse_name": "A", "umaban": "1", "waku": "1", "style": "先行", "odds": 5.0, "recent_runs": [], "recent_run_details": []}
    base_bias = {
        "frame_bias": {"inner": 0.55, "outer": 0.20},
        "style_bias": {"逃げ": 0.1, "先行": 0.55, "差し": 0.2, "追込": 0.1},
        "sample_size": 5,
        "fallback_used": False,
        "summary_label": "内枠有利 / 先行有利",
    }

    high_bonus, _ = same_day_service._track_bias_bonus(horse, {**base_bias, "confidence": "high"})
    provisional_bonus, _ = same_day_service._track_bias_bonus(horse, {**base_bias, "confidence": "provisional"})
    low_bonus, _ = same_day_service._track_bias_bonus(horse, {**base_bias, "confidence": "low"})

    assert high_bonus > provisional_bonus > low_bonus


def test_refresh_same_day_sheet_volatile_recomputes_track_bias_and_bet_plan(monkeypatch, tmp_path) -> None:
    target_date = date(2026, 5, 3)
    cached = {
        "generated_at": "2026-05-03T09:00:00",
        "date": target_date.isoformat(),
        "venue": "東京",
        "race_count": 1,
        "races": [
            {
                "race": {
                    "race_name": "3歳未勝利",
                    "grade": "平場",
                    "date_str": "2026/05/03(日)",
                    "date_iso": target_date.isoformat(),
                    "venue": "東京",
                    "distance": "1600m",
                    "surface": "芝",
                    "race_id": "202605020404",
                    "race_key": "2026-05-03_東京_3歳未勝利_4R",
                    "race_number": "4R",
                    "start_time": "11:35",
                },
                "entry": {
                    "race_id": "202605020404",
                    "source_csv": "race.csv",
                    "horses": [
                        {
                            "horse_name": "内先行",
                            "waku": "1",
                            "umaban": "1",
                            "sex_age": "",
                            "weight": "",
                            "body_weight": "",
                            "body_delta": "",
                            "body_weight_bucket": "",
                            "body_weight_source": "",
                            "body_weight_top3_rate": None,
                            "jockey": "",
                            "style": "先行",
                            "odds": 5.0,
                            "recent_runs": [],
                            "last3fs": [],
                            "corners": [],
                            "field_sizes": [],
                            "recent_run_details": [],
                        },
                        {
                            "horse_name": "外追込",
                            "waku": "8",
                            "umaban": "15",
                            "sex_age": "",
                            "weight": "",
                            "body_weight": "",
                            "body_delta": "",
                            "body_weight_bucket": "",
                            "body_weight_source": "",
                            "body_weight_top3_rate": None,
                            "jockey": "",
                            "style": "追込",
                            "odds": 6.0,
                            "recent_runs": [],
                            "last3fs": [],
                            "corners": [],
                            "field_sizes": [],
                            "recent_run_details": [],
                        },
                    ],
                    "style_distribution": {"先行": 1, "追込": 1},
                    "style_distribution_label": "先行1 / 追込1",
                    "warnings": [],
                },
                "course_stats": None,
                "bet_plan": {"race_id": "202605020404", "budget_yen": 3000, "provisional_only": False, "ranking": [], "tickets": [], "warnings": []},
                "track_bias": None,
                "error": "",
            }
        ],
    }
    today_results = []
    for race_no in range(1, 4):
        for finish, waku in enumerate([1, 2, 3, 5, 6, 7, 8, 4], start=1):
            today_results.append(
                {
                    "race_id": f"race-{race_no}",
                    "race_number": f"{race_no}R",
                    "surface": "芝",
                    "distance_m": 1600,
                    "finish_pos": finish,
                    "waku": waku,
                    "style": "先行" if waku <= 4 else "追込",
                }
            )

    monkeypatch.setattr(same_day_service, "SAME_DAY_SHEET_DIR", tmp_path)
    monkeypatch.setattr(same_day_service, "_same_day_sheet_has_recent_run_details", lambda snapshot: True)
    monkeypatch.setattr(same_day_service, "_collect_track_bias_result_pools", lambda **kwargs: (today_results, []))
    monkeypatch.setattr(same_day_service, "_fetch_body_weight_map", lambda race_id: ({}, ""))
    monkeypatch.setattr(same_day_service, "_fetch_win_odds_map", lambda race_id, **kwargs: ({}, ""))
    monkeypatch.setattr(same_day_service, "_fetch_jra_entry_map", lambda *args, **kwargs: ({}, ""))
    same_day_service._save_same_day_sheet_cache(cached)

    result = same_day_service.refresh_same_day_sheet_volatile(target_date, "東京")
    race_item = result["races"][0]

    assert race_item["track_bias"]["confidence"] == "provisional"
    assert race_item["bet_plan"]["ranking"]
    assert race_item["bet_plan"]["ranking"][0]["bias_bonus"] > 0


def test_track_bias_uses_entry_start_time_when_race_start_time_missing() -> None:
    snapshot = {
        "races": [
            {
                "race": {"race_id": "race-1", "race_number": "1R"},
                "entry": {"start_time": "10:05", "horses": []},
            }
        ]
    }

    races = same_day_service._track_bias_races_from_snapshot(snapshot)

    assert races[0]["start_time"] == "10:05"


def test_going_bucket_treats_all_off_going_as_soft() -> None:
    assert sire_aptitude._going_bucket("稍") == "soft"
    assert sire_aptitude._going_bucket("稍重") == "soft"
    assert sire_aptitude._going_bucket("重") == "soft"
    assert sire_aptitude._going_bucket("不良") == "soft"
    assert sire_aptitude._going_bucket("不") == "soft"
    assert sire_aptitude._going_bucket("良") == "firm"


def test_shosho_going_fit_matches_slightly_different_off_going_labels() -> None:
    horse = {
        "horse_name": "A",
        "umaban": "1",
        "odds": 8.0,
        "recent_run_details": [{"finish": 2, "going": "稍重"}],
    }
    ctx = shosho_signals.ShoshoRaceContext(going="稍")

    signals = shosho_signals.evaluate_shosho_signals(horse, ctx)

    assert any(flag["code"] == "going_fit" for flag in signals["value_flags"])
