"""
same-day モード向けの静的/軽量テスト。
"""

from __future__ import annotations

import importlib
import re
import sys
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).parent


def test_race_key_collision_guard() -> None:
    sys.path.insert(0, str(PROJECT))
    import race_catalog

    importlib.reload(race_catalog)

    k1 = race_catalog.build_race_key(date(2026, 4, 26), "東京", "3歳未勝利", "1R")
    k2 = race_catalog.build_race_key(date(2026, 4, 26), "東京", "3歳未勝利", "2R")
    assert k1 != k2, "[NG] race_key collision: race_number is not reflected"
    assert k1.endswith("_1R") and k2.endswith("_2R"), "[NG] race_key suffix must include race_number"
    print("T-SD-01 [OK]: race_key includes race_number")


def test_fetch_races_by_date_shape_parser() -> None:
    sys.path.insert(0, str(PROJECT))
    import race_catalog

    importlib.reload(race_catalog)

    sample_html = """
    <html><body>
      <ul>
        <li class="RaceList_DataItem">
          <a href="../race/shutuba.html?race_id=202605020201&rf=race_list">1R 3歳未勝利 10:05 ダ1400m 16頭</a>
          <a href="../race/movie.html?race_id=202605020201&rf=race_list"></a>
        </li>
        <li class="RaceList_DataItem">
          <a href="../race/shutuba.html?race_id=202605020202&rf=race_list">2R 3歳未勝利 10:35 ダ1600m 14頭</a>
          <a href="../race/movie.html?race_id=202605020202&rf=race_list"></a>
        </li>
      </ul>
    </body></html>
    """
    rows = race_catalog._parse_race_list_sub_page(sample_html, date(2026, 4, 26))
    assert len(rows) == 2, f"[NG] unexpected rows: {len(rows)}"
    assert rows[0].race_id and rows[1].race_id, "[NG] race_id must be populated in same-day parser"
    assert rows[0].race_number == "1R" and rows[1].race_number == "2R", "[NG] race_number parse failed"
    assert rows[0].race_key != rows[1].race_key, "[NG] parsed race_key must be unique"
    print("T-SD-01 [OK]: fetch_races_by_date parser shape")


def test_group_races_by_venue_sort() -> None:
    sys.path.insert(0, str(PROJECT))
    import race_catalog

    importlib.reload(race_catalog)
    RaceInfo = race_catalog.RaceInfo
    base_date = date(2026, 4, 26)
    rows = [
        RaceInfo("A", "平場", "2026/04/26(日)", base_date, "東京", "1400m", "ダート", "202605020202", "k2", race_number="2R"),
        RaceInfo("B", "平場", "2026/04/26(日)", base_date, "東京", "1400m", "ダート", "202605020201", "k1", race_number="1R"),
        RaceInfo("C", "平場", "2026/04/26(日)", base_date, "京都", "1200m", "芝", "202608020101", "k3", race_number="1R"),
    ]
    grouped = race_catalog.group_races_by_venue(rows)
    assert "東京" in grouped and "京都" in grouped, "[NG] group keys missing"
    tokyo_numbers = [r.race_number for r in grouped["東京"]]
    assert tokyo_numbers == ["1R", "2R"], f"[NG] race sort failed: {tokyo_numbers}"
    print("T-SD-01 [OK]: group_races_by_venue sort")


def test_widget_scope_static() -> None:
    src = (PROJECT / "app.py").read_text(encoding="utf-8")

    required_scoped_tokens = [
        "fetch_odds_btn::{race_widget_scope}",
        "combined_max_web::{race_widget_scope}",
        "combined_auto_youtube::{race_widget_scope}",
        "combined_max_youtube::{race_widget_scope}",
        "combined_search::{race_widget_scope}",
        "x_max_tweets::{race_widget_scope}",
        "x_search::{race_widget_scope}",
        "x_reset::{race_widget_scope}",
        "doc_uploader::{race_widget_scope}",
        "btn_doc_race::{race_widget_scope}",
        "btn_doc_horses::{race_widget_scope}",
        "btn_doc_horse_reset::{race_widget_scope}",
        "btn_race_refresh::{race_widget_scope}",
        "yt_detail_max::{race_widget_scope}",
        "yt_detail_search::{race_widget_scope}",
    ]
    for token in required_scoped_tokens:
        assert token in src, f"[NG] scoped key not found: {token}"

    forbidden_literals = [
        'key="fetch_odds_btn"',
        'key="combined_max_web"',
        'key="combined_auto_youtube"',
        'key="combined_max_youtube"',
        'key="combined_search"',
        'key="x_max_tweets"',
        'key="x_search"',
        'key="x_reset"',
        'key="doc_uploader"',
        'key="btn_doc_race"',
        'key="btn_doc_horses"',
        'key="btn_doc_horse_reset"',
        'key="btn_race_refresh"',
        'key="yt_detail_max"',
        'key="yt_detail_search"',
    ]
    for lit in forbidden_literals:
        assert lit not in src, f"[NG] unscoped key literal remains: {lit}"

    # _display_main_content 関数化されていること
    assert re.search(r"def\s+_display_main_content\(", src), "[NG] _display_main_content not found"
    print("T-SD-05 [OK]: widget keys are race-scoped")


def test_recent_runs_corners_contract() -> None:
    src = (PROJECT / "get_keiba_info.py").read_text(encoding="utf-8")
    assert '"corners"' in src, "[NG] fetch_recent_runs corners key not found"
    assert '"last3fs"' in src, "[NG] fetch_recent_runs last3fs key not found"
    assert '"field_sizes"' in src, "[NG] fetch_recent_runs field_sizes key not found"
    assert '"前走上り"' in src, "[NG] recent run last3f display column not found"
    assert "def _extract_corner_positions(" in src, "[NG] corner parser helper not found"
    assert "def _extract_field_size(" in src, "[NG] field size parser helper not found"
    assert "def _extract_last3f(" in src, "[NG] last3f parser helper not found"
    print("T-SD-12 [OK]: recent_runs corners/last3f contract")


def _load_app_module():
    sys.path.insert(0, str(PROJECT))
    import app

    return importlib.reload(app)


def test_classify_corner_style_with_field_size() -> None:
    app = _load_app_module()
    cases = [
        ("1-1-1-1", "14", "逃げ"),
        ("3-3-3-3", "14", "先行"),
        ("5-5-5-5", "14", "差し"),
        ("9-9-9-9", "14", "差し"),
        ("10-10-10-10", "14", "追込"),
        ("5-5-5-5", "18", "先行"),
        ("6-6-6-6", "18", "差し"),
        ("1-1-1-1", "", "逃げ"),
        ("5-5-5-5", "", "差し"),
        ("8-8-8-8", "", "追込"),
    ]
    for corners, field_size, expected in cases:
        actual = app._classify_corner_style(corners, field_size)
        assert actual == expected, f"[NG] {corners}/{field_size}: expected={expected}, actual={actual}"
    print("T-SD-15 [OK]: corner style classification uses 4th corner + field size")


def test_classify_running_style_integration() -> None:
    app = _load_app_module()

    def recent(labels: list[str]) -> dict:
        corner_by_label = {
            "逃げ": "1-1-1-1",
            "先行": "3-3-3-3",
            "差し": "6-6-6-6",
            "追込": "10-10-10-10",
        }
        return {
            "corners": [corner_by_label[label] for label in labels],
            "field_sizes": ["14"] * len(labels),
        }

    cases = [
        (["差し", "差し", "差し"], "差し"),
        (["差し", "差し", "追込"], "差し"),
        (["差し", "追込", "差し"], "差し"),
        (["差し", "追込", "先行"], "自在"),
        (["先行", "差し", "差し"], "先行"),
    ]
    for labels, expected in cases:
        actual = app.classify_running_style(recent(labels))
        assert actual == expected, f"[NG] {labels}: expected={expected}, actual={actual}"

    legacy_actual = app.classify_running_style({"corners": ["5-5-5-5", "8-8-8-8", "3-3-3-3"]})
    assert legacy_actual == "自在", f"[NG] legacy no-field_sizes fallback failed: {legacy_actual}"
    print("T-SD-15 [OK]: running style integration is previous-run-first")


def test_race_characteristics_frame_markdown_table() -> None:
    app = _load_app_module()
    info = app.get_race_characteristics_from_course_stats({
        "target": {"venue": "東京", "distance": "2400m", "surface": "芝"},
        "race_list_url": "https://example.test/course",
        "sample_race_count": 2,
        "frame_stats": [
            {"label": "1枠", "starts": 10, "wins": 2, "top3": 4, "outside_top3": 6, "win_rate": 20.0, "top3_rate": 40.0, "outside_top3_rate": 60.0},
            {"label": "2枠", "starts": 10, "wins": 1, "top3": 3, "outside_top3": 7, "win_rate": 10.0, "top3_rate": 30.0, "outside_top3_rate": 70.0},
        ],
        "style_stats": [{"label": "先行", "starts": 10, "top3": 5, "top3_rate": 50.0}],
        "popularity_stats": [{"label": "1-3人気", "starts": 10, "top3": 6, "top3_rate": 60.0}],
        "pace_tendency": "バランス",
    })
    table = info.get("枠別割合表", "")
    assert "| 枠 | 1着 | 複勝 | それ以外 | 出走数 |" in table, "[NG] frame markdown header missing"
    assert "| 1枠 | 20.0% (2) | 40.0% (4) | 60.0% (6) | 10 |" in table, "[NG] frame markdown row missing"
    assert info.get("schema_version") == "same_day_course_stats_v3", "[NG] course stats schema version not bumped"
    print("T-SD-16 [OK]: race characteristics include frame markdown ratio table")


def test_same_day_field_helpers_present() -> None:
    app_src = (PROJECT / "app.py").read_text(encoding="utf-8")
    info_src = (PROJECT / "get_keiba_info.py").read_text(encoding="utf-8")
    required_app = [
        "def _auto_fetch_initial_gates_and_odds(",
        "def _csv_needs_gate_values(",
        "def _ensure_same_day_initial_entry_fields(",
        "allow_playwright=False",
        "当日モードのWeb一括検索ではYouTube同時取得を行いません",
        "combined_auto_youtube = False",
        "provisional_only",
        "has_umaban_for_bet",
        "def _format_style_distribution(",
        "def _format_race_metadata_line(",
        "馬体重",
        "前走上り",
    ]
    for token in required_app:
        assert token in app_src, f"[NG] same-day field helper missing: {token}"
    required_info = [
        "def fetch_race_metadata(",
        "def _split_body_weight(",
        '"馬体重"',
        '"増減"',
    ]
    for token in required_info:
        assert token in info_src, f"[NG] get_keiba_info helper missing: {token}"
    print("T-SD-14 [OK]: same-day field helpers present")


def test_same_day_phase2_helpers_present() -> None:
    src = (PROJECT / "app.py").read_text(encoding="utf-8")
    required = [
        "def classify_running_style(",
        "def _fetch_course_stats_cached(",
        "def get_race_characteristics_from_course_stats(",
        "def search_x_tweets_broad(",
        "def fetch_and_analyze_x_tweets_broad(",
        "fetch_and_analyze_same_day_sources(",
    ]
    for token in required:
        assert token in src, f"[NG] helper/function missing: {token}"
    print("T-SD-09/10/11/12 [OK]: phase2 helpers present")


def main() -> int:
    tests = [
        test_race_key_collision_guard,
        test_fetch_races_by_date_shape_parser,
        test_group_races_by_venue_sort,
        test_widget_scope_static,
        test_recent_runs_corners_contract,
        test_classify_corner_style_with_field_size,
        test_classify_running_style_integration,
        test_race_characteristics_frame_markdown_table,
        test_same_day_field_helpers_present,
        test_same_day_phase2_helpers_present,
    ]

    print("=" * 60)
    print("Same-day Mode Static Verification")
    print("=" * 60)
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
        except AssertionError as e:
            failed += 1
            print(f"[NG] {test_fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"[NG] {test_fn.__name__}: {type(e).__name__}: {e}")
    total = len(tests)
    passed = total - failed
    print(f"{passed}/{total} passed")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
