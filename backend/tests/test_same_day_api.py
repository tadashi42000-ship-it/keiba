from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from fastapi.testclient import TestClient

from app.api.v1 import races as races_api
from app.main import app
from app.services import same_day_service


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
                "error": "",
            }
        ],
    }

    monkeypatch.setattr(same_day_service, "SAME_DAY_SHEET_DIR", tmp_path)
    same_day_service._save_same_day_sheet_cache(cached)
    monkeypatch.setattr(same_day_service, "_fetch_win_odds_map", lambda race_id: ({"フレンチブラッサム": 3.4}, "netkeiba odds API"))

    result = same_day_service.build_same_day_sheet_snapshot(date(2026, 5, 3), "東京", refresh=True)

    entry = result["races"][0]["entry"]
    assert entry["horses"][0]["odds"] == 3.4
    assert not any("単勝オッズは未公開" in warning for warning in entry["warnings"])
    assert result["races"][0]["bet_plan"]["ranking"][0]["horse_name"] == "フレンチブラッサム"
