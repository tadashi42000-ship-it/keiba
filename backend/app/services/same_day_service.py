from __future__ import annotations

import math
import base64
import json
import re
import sys
import zlib
from functools import lru_cache
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).resolve().parents[3]
LEGACY_DIR = ROOT_DIR / "legacy" / "streamlit_app"
if str(LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_DIR))

from get_keiba_info import (  # type: ignore  # noqa: E402
    fetch_race_csv as legacy_fetch_race_csv,
    fetch_race_metadata as legacy_fetch_race_metadata,
    fetch_recent_runs as legacy_fetch_recent_runs,
)
from race_catalog import fetch_races_by_date as legacy_fetch_races_by_date  # type: ignore  # noqa: E402
from race_catalog import group_races_by_venue as legacy_group_races_by_venue  # type: ignore  # noqa: E402
from same_day_sources import build_requests_session, fetch_course_stats  # type: ignore  # noqa: E402

from app.services.race_service import BACKEND_DATA_DIR

SAME_DAY_COURSE_STATS_SCHEMA_VERSION = "same_day_course_stats_v3"
STYLE_ORDER = ("逃げ", "先行", "差し", "追込", "自在")
SAME_DAY_SHEET_DIR = ROOT_DIR / "data" / "same_day_sheets"


def _to_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def _to_float(value: object) -> float | None:
    text = _to_text(value).replace(",", "")
    if not text or text in {"-", "---", "---.-"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _normalize_key(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _first_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    by_normalized = {_normalize_key(col): col for col in df.columns}
    for candidate in candidates:
        found = by_normalized.get(_normalize_key(candidate))
        if found is not None:
            return found
    return None


def _horse_token(value: object) -> str:
    return re.sub(r"[\s\u3000]+", "", str(value or "")).lower()


def classify_corner_style(corner_text: str, field_size: str = "") -> str:
    values = [int(x) for x in re.findall(r"\d{1,2}", _to_text(corner_text))]
    if not values:
        return ""
    pos_4 = values[-1]
    try:
        field_count = int(_to_text(field_size))
    except (TypeError, ValueError):
        field_count = 0

    if pos_4 <= 1:
        return "逃げ"
    if field_count > 0:
        pos_ratio = pos_4 / field_count
        if pos_ratio <= 0.30:
            return "先行"
        if pos_ratio <= 0.65:
            return "差し"
        return "追込"
    if pos_4 <= 3:
        return "先行"
    if pos_4 <= 7:
        return "差し"
    return "追込"


def classify_running_style(recent_runs: dict | None) -> str:
    if not isinstance(recent_runs, dict):
        return ""
    corners = recent_runs.get("corners")
    if isinstance(corners, str):
        corner_values = [x.strip() for x in re.split(r"[,\s/]+", corners) if x.strip()]
    elif isinstance(corners, list):
        corner_values = [_to_text(x) for x in corners]
    else:
        corner_values = []

    field_sizes = recent_runs.get("field_sizes")
    if isinstance(field_sizes, str):
        field_size_values = [x.strip() for x in re.split(r"[,\s/]+", field_sizes)]
    elif isinstance(field_sizes, list):
        field_size_values = [_to_text(x) for x in field_sizes]
    else:
        field_size_values = []

    while len(field_size_values) < len(corner_values):
        field_size_values.append("")

    styles: list[str] = []
    for corner, field_size in zip(corner_values[:3], field_size_values[:3]):
        style = classify_corner_style(corner, field_size)
        if style:
            styles.append(style)

    if not styles:
        return ""
    if len(styles) >= 3 and styles[0] == styles[1] == styles[2]:
        return styles[0]
    if len(styles) >= 2 and styles[0] == styles[1]:
        return styles[0]
    if len(styles) >= 3 and styles[0] == styles[2]:
        return styles[0]
    if len(styles) >= 3 and len(set(styles[:3])) == 3:
        return "自在"
    return styles[0]


def get_same_day_races(target_date: date, venue: str | None = None) -> dict[str, Any]:
    races = legacy_fetch_races_by_date(target_date)
    if venue:
        races = [race for race in races if _to_text(getattr(race, "venue", "")) == venue]
    grouped = legacy_group_races_by_venue(races)
    return {
        "date": target_date.isoformat(),
        "venue": venue or "",
        "venues": sorted(grouped.keys()),
        "races": [_race_to_dict(race) for race in races],
    }


def build_same_day_sheet_snapshot(
    target_date: date,
    venue: str,
    budget_yen: int = 3000,
    refresh: bool = False,
) -> dict[str, Any]:
    cached = _load_same_day_sheet_cache(target_date, venue)
    cached_has_run_details = _same_day_sheet_has_recent_run_details(cached) if cached else False
    if cached and cached_has_run_details and not refresh:
        return cached
    if cached and cached_has_run_details and refresh:
        refreshed = _refresh_same_day_sheet_odds(cached, budget_yen=budget_yen)
        _save_same_day_sheet_cache(refreshed)
        return refreshed

    races_response = get_same_day_races(target_date=target_date, venue=venue)
    snapshots: list[dict[str, Any]] = []
    for race in races_response.get("races", []):
        race_id = race.get("race_id")
        if not race_id:
            snapshots.append({"race": race, "error": "race_id???"})
            continue
        try:
            entry = get_entry_snapshot(str(race_id))
            course_stats = get_course_stats_snapshot(
                race_id=str(race_id),
                venue=str(race.get("venue") or venue),
                distance=str(race.get("distance") or ""),
                surface=str(race.get("surface") or ""),
            )
            bet_plan = _build_bet_plan_from_entry(entry, budget_yen=budget_yen)
            snapshots.append(
                {
                    "race": race,
                    "entry": entry,
                    "course_stats": course_stats,
                    "bet_plan": bet_plan,
                    "error": "",
                }
            )
        except Exception as exc:
            snapshots.append({"race": race, "error": str(exc)})
    snapshot = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date": target_date.isoformat(),
        "venue": venue,
        "race_count": len(races_response.get("races", [])),
        "races": snapshots,
    }
    _save_same_day_sheet_cache(snapshot)
    return snapshot


def _refresh_same_day_sheet_odds(snapshot: dict[str, Any], budget_yen: int = 3000) -> dict[str, Any]:
    """Refresh volatile win odds/body weight while keeping expensive static race data cached."""
    updated_snapshot = dict(snapshot)
    races: list[dict[str, Any]] = []
    for item in snapshot.get("races", []):
        if not isinstance(item, dict):
            continue
        updated_item = dict(item)
        race = updated_item.get("race") if isinstance(updated_item.get("race"), dict) else {}
        race_id = _to_text(race.get("race_id"))
        entry = updated_item.get("entry") if isinstance(updated_item.get("entry"), dict) else None
        if race_id and entry:
            horses = entry.get("horses") if isinstance(entry.get("horses"), list) else []
            body_map, body_note = _fetch_body_weight_map(race_id)
            if body_map and horses:
                _merge_body_weight_into_horses(horses, body_map, overwrite=True)
                entry["body_updated_at"] = _now_time_label()
            elif body_note:
                warnings = list(entry.get("warnings") or [])
                if body_note not in warnings:
                    warnings.append(body_note)
                entry["warnings"] = warnings

            odds_map, odds_note = _fetch_win_odds_map(race_id)
            if odds_map:
                _merge_odds_into_horses(horses, odds_map, overwrite=True)
                entry["odds_updated_at"] = _now_time_label()
                entry["warnings"] = [
                    warning
                    for warning in entry.get("warnings", [])
                    if "単勝オッズ" not in _to_text(warning) and "odds" not in _to_text(warning).lower()
                ]
            elif odds_note:
                warnings = list(entry.get("warnings") or [])
                if odds_note not in warnings:
                    warnings.append(odds_note)
                entry["warnings"] = warnings
            if body_map or odds_map:
                updated_item["bet_plan"] = _build_bet_plan_from_entry(entry, budget_yen=budget_yen)
        races.append(updated_item)
    updated_snapshot["races"] = races
    updated_snapshot["generated_at"] = datetime.now().isoformat(timespec="seconds")
    return updated_snapshot


def _same_day_sheet_cache_paths(target_date: date, venue: str) -> list[Path]:
    date_text = target_date.isoformat()
    venue_token = _safe_path_token(venue)
    return [
        SAME_DAY_SHEET_DIR / f"{date_text}_{venue_token}_same_day_sheet.json",
        SAME_DAY_SHEET_DIR / f"{date_text}_{_ascii_venue_alias(venue)}_same_day_sheet.json",
    ]


def _safe_path_token(value: str) -> str:
    return re.sub(r'[<>:"/\\\\|?*\\x00-\\x1f]+', "_", value).strip(" ._") or "venue"


def _ascii_venue_alias(venue: str) -> str:
    aliases = {"東京": "tokyo", "京都": "kyoto", "福島": "fukushima", "中山": "nakayama", "阪神": "hanshin"}
    return aliases.get(venue, re.sub(r"[^A-Za-z0-9_-]+", "_", venue).strip("_") or "venue")


def _load_same_day_sheet_cache(target_date: date, venue: str) -> dict[str, Any] | None:
    for path in _same_day_sheet_cache_paths(target_date, venue):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("date") == target_date.isoformat() and payload.get("venue") == venue:
            payload["cache_path"] = str(path)
            return payload
    return None


def _same_day_sheet_has_recent_run_details(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    races = snapshot.get("races")
    if not isinstance(races, list):
        return False
    for item in races:
        if not isinstance(item, dict):
            continue
        entry = item.get("entry")
        if not isinstance(entry, dict):
            continue
        horses = entry.get("horses")
        if not isinstance(horses, list) or not horses:
            continue
        return all(
            isinstance(horse, dict)
            and isinstance(horse.get("recent_run_details"), list)
            and all(isinstance(detail, dict) and "venue" in detail for detail in horse.get("recent_run_details") or [])
            for horse in horses
        )
    return False


def _save_same_day_sheet_cache(snapshot: dict[str, Any]) -> None:
    try:
        target_date = date.fromisoformat(str(snapshot.get("date")))
    except ValueError:
        return
    venue = _to_text(snapshot.get("venue"))
    if not venue:
        return
    SAME_DAY_SHEET_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    for path in _same_day_sheet_cache_paths(target_date, venue):
        path.write_text(text, encoding="utf-8")


def get_entry_snapshot(race_id: str) -> dict[str, Any]:
    csv_path = BACKEND_DATA_DIR / f"race_{race_id}.csv"
    legacy_fetch_race_csv(race_id, str(csv_path))
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    metadata = legacy_fetch_race_metadata(race_id) or {}
    recent_runs = legacy_fetch_recent_runs(race_id) or {}
    horse_id_map = {
        name: _to_text(payload.get("horse_id"))
        for name, payload in recent_runs.items()
        if isinstance(payload, dict) and _to_text(payload.get("horse_id"))
    }
    run_details_map = _fetch_run_details_for_race(horse_id_map) if horse_id_map else {}
    horses = _build_entry_horses(df, recent_runs, run_details_map)
    odds_map, odds_note = _fetch_win_odds_map(race_id)
    if odds_map:
        _merge_odds_into_horses(horses, odds_map)
        _write_odds_to_csv(csv_path, odds_map)
    odds_updated_at = _now_time_label() if any(horse.get("odds") is not None for horse in horses) else ""
    body_updated_at = _now_time_label() if any(horse.get("body_weight") for horse in horses) else ""
    style_distribution = _style_distribution(horses)
    warnings: list[str] = []
    if not any(horse.get("umaban") for horse in horses):
        warnings.append("馬番/枠番が未確定です。正式な買い目番号は生成できません。")
    if horses and not any(horse.get("odds") is not None for horse in horses):
        warnings.append("単勝オッズは未公開または取得できませんでした。当日公開後に手動更新してください。")
        if odds_note:
            warnings.append(odds_note)
    if not recent_runs:
        warnings.append("近3走データを取得できませんでした。")
    return {
        "race_id": race_id,
        "source_csv": str(csv_path),
        "start_time": _to_text(metadata.get("start_time")),
        "weather": _to_text(metadata.get("weather")),
        "track_conditions": metadata.get("track_conditions") if isinstance(metadata.get("track_conditions"), dict) else {},
        "race_data01": _to_text(metadata.get("race_data01")),
        "race_data02": _to_text(metadata.get("race_data02")),
        "odds_updated_at": odds_updated_at,
        "body_updated_at": body_updated_at,
        "horses": horses,
        "style_distribution": style_distribution,
        "style_distribution_label": " / ".join(
            f"{style}{style_distribution[style]}" for style in STYLE_ORDER if style_distribution.get(style)
        ),
        "warnings": warnings,
    }


def get_course_stats_snapshot(*, race_id: str, venue: str, distance: str, surface: str) -> dict[str, Any]:
    session = build_requests_session()
    raw = fetch_course_stats(venue, distance, surface, session=session) or {}
    frame_stats = [row for row in raw.get("frame_stats", []) if isinstance(row, dict)]
    style_stats = [row for row in raw.get("style_stats", []) if isinstance(row, dict)]
    popularity_stats = [row for row in raw.get("popularity_stats", []) if isinstance(row, dict)]
    style_top = sorted(style_stats, key=lambda row: float(row.get("top3_rate") or 0), reverse=True)[:2]
    pace_tendency = _to_text(raw.get("pace_tendency"))
    favored_styles = [str(row.get("label")) for row in style_top if row.get("label")]
    return {
        "race_id": race_id,
        "schema_version": SAME_DAY_COURSE_STATS_SCHEMA_VERSION,
        "source_url": _to_text(raw.get("race_list_url")),
        "sample_race_count": int(raw.get("sample_race_count") or 0),
        "target": raw.get("target") if isinstance(raw.get("target"), dict) else {
            "venue": venue,
            "distance": distance,
            "surface": surface,
        },
        "frame_stats": frame_stats,
        "style_stats": style_stats,
        "popularity_stats": popularity_stats,
        "pace_tendency": pace_tendency,
        "frame_markdown": build_frame_rate_markdown(frame_stats),
        "summary": {
            "course": f"{venue} {surface}{distance} の過去傾向を静的集計しました。",
            "winning_type": " / ".join(_format_stat_line(row) for row in style_top if _format_stat_line(row)),
            "pace_note": (
                f"複勝率ベースでは{'・'.join(favored_styles)}が安定。"
                + (f"勝ち切り傾向は{pace_tendency}のため、軸候補と相手候補を分けて評価してください。" if pace_tendency else "")
            ) if favored_styles else "脚質傾向はサンプル数の影響を受けるため、馬別情報と合わせて判断してください。",
        },
    }


def build_frame_rate_markdown(frame_rows: list[dict]) -> str:
    lines = ["| 枠 | 1着 | 複勝 | それ以外 | 出走数 |", "|---|---:|---:|---:|---:|"]
    added = 0
    for row in frame_rows or []:
        label = _to_text(row.get("label"))
        starts = int(row.get("starts") or 0)
        if not label or starts <= 0:
            continue
        wins = int(row.get("wins") or 0)
        top3 = int(row.get("top3") or 0)
        other = int(row.get("outside_top3") or max(starts - top3, 0))
        win_rate = float(row.get("win_rate") or ((wins / starts) * 100))
        top3_rate = float(row.get("top3_rate") or ((top3 / starts) * 100))
        other_rate = float(row.get("outside_top3_rate") or ((other / starts) * 100))
        lines.append(f"| {label} | {win_rate:.1f}% ({wins}) | {top3_rate:.1f}% ({top3}) | {other_rate:.1f}% ({other}) | {starts} |")
        added += 1
    return "\n".join(lines) if added else ""


def build_bet_plan_snapshot(race_id: str, budget_yen: int = 3000) -> dict[str, Any]:
    entry = get_entry_snapshot(race_id)
    return _build_bet_plan_from_entry(entry, budget_yen=budget_yen)


def _build_bet_plan_from_entry(entry: dict[str, Any], budget_yen: int = 3000) -> dict[str, Any]:
    race_id = _to_text(entry.get("race_id"))
    horses = entry["horses"]
    ranked = _rank_horses(horses)
    has_numbers = any(_to_text(horse.get("umaban")) for horse in horses)
    warnings = list(entry.get("warnings") or [])
    if not has_numbers:
        warnings.append("馬番/枠番が未確定のため、正式な買い目ではなく候補馬ランキングを表示します。")
        return {
            "race_id": race_id,
            "budget_yen": budget_yen,
            "provisional_only": True,
            "ranking": ranked,
            "tickets": [],
            "warnings": warnings,
        }

    top = ranked[:3]
    unit = max(100, int(budget_yen / max(len(top), 1) / 100) * 100)
    tickets = [
        {
            "type": "単勝",
            "selection": item["umaban"],
            "horse_names": [item["horse_name"]],
            "amount_yen": unit,
            "reason": item["reason"],
        }
        for item in top
        if item.get("umaban")
    ]
    return {
        "race_id": race_id,
        "budget_yen": budget_yen,
        "provisional_only": False,
        "ranking": ranked,
        "tickets": tickets,
        "warnings": warnings,
    }


def _race_to_dict(race: Any) -> dict[str, Any]:
    return {
        "race_name": _to_text(getattr(race, "race_name", "")),
        "grade": _to_text(getattr(race, "grade", "")),
        "date_str": _to_text(getattr(race, "date_str", "")),
        "date_iso": getattr(race, "date", date.today()).isoformat(),
        "venue": _to_text(getattr(race, "venue", "")),
        "distance": _to_text(getattr(race, "distance", "")),
        "surface": _to_text(getattr(race, "surface", "")),
        "race_id": _to_text(getattr(race, "race_id", "")) or None,
        "race_key": _to_text(getattr(race, "race_key", "")),
        "race_number": _to_text(getattr(race, "race_number", "")),
    }


def _fetch_win_odds_map(race_id: str, allow_jra_fallback: bool = False) -> tuple[dict[str, float], str]:
    """
    出馬表CSVの単勝オッズが未更新の時に、netkeibaのオッズ専用ページ/APIを軽量確認する。
    取得元が空の場合も理由を返し、UIで「未公開」と「取得元が空」を区別できるようにする。
    """
    if not race_id:
        return {}, ""

    session = build_requests_session()
    headers = {"Referer": f"https://race.netkeiba.com/odds/index.html?race_id={race_id}"}
    api_reason = ""
    try:
        resp = session.get(
            "https://race.netkeiba.com/api/api_get_jra_odds.html",
            params={
                "pid": "api_get_jra_odds",
                "input": "UTF-8",
                "output": "json",
                "race_id": race_id,
                "type": "1",
                "action": "init",
                "sort": "odds",
                "compress": "1",
            },
            headers=headers,
            timeout=8,
        )
        if resp.status_code == 200:
            payload = resp.json()
            api_reason = _to_text(payload.get("reason")) if isinstance(payload, dict) else ""
            api_odds = _extract_netkeiba_api_odds(payload) or _extract_odds_from_any_payload(payload)
            if api_odds:
                return api_odds, "netkeiba odds API"
    except Exception as exc:
        api_reason = f"netkeiba odds API {type(exc).__name__}"

    try:
        resp = session.get(
            f"https://race.netkeiba.com/odds/index.html?type=b1&race_id={race_id}",
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            return {}, f"netkeiba odds page HTTP {resp.status_code}"
        if not resp.encoding or resp.encoding.lower() in {"iso-8859-1", "ascii"}:
            resp.encoding = "EUC-JP"
        html_odds = _extract_win_odds_from_html(resp.text)
        if html_odds:
            return html_odds, "netkeiba odds page"
    except Exception as exc:
        return {}, f"netkeiba odds page {type(exc).__name__}"

    jra_note = ""
    if allow_jra_fallback:
        jra_odds, jra_note = _fetch_jra_win_odds_map(race_id)
        if jra_odds:
            return jra_odds, jra_note

    suffix = f" ({api_reason})" if api_reason else ""
    if jra_note:
        suffix = f"{suffix}; {jra_note}"
    return {}, f"単勝オッズ取得元は空でした{suffix}"


def _extract_netkeiba_api_odds(payload: Any) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, str):
        data = _decode_netkeiba_compressed_data(data)
    if not isinstance(data, dict):
        return {}
    horse_list = data.get("horse_list") or data.get("horseList")
    odds_payload = data.get("odds")
    if not isinstance(odds_payload, dict):
        return {}
    win_rows = odds_payload.get("1") or odds_payload.get(1)
    if not isinstance(win_rows, dict):
        return {}
    result: dict[str, float] = {}
    for key, row in win_rows.items():
        if not isinstance(row, list) or len(row) < 1:
            continue
        value = _to_float(row[0])
        if value is None:
            continue
        horse = None
        if isinstance(horse_list, dict) and len(row) >= 4:
            horse = horse_list.get(_to_text(row[3]))
        name = _to_text(horse.get("Bamei") or horse.get("Bamei9")) if isinstance(horse, dict) else ""
        if name:
            result[name] = value
        else:
            umaban = _to_text(key).lstrip("0")
            if umaban:
                result[f"__umaban__:{umaban}"] = value
    return result


def _decode_netkeiba_compressed_data(data: str) -> dict[str, Any]:
    text = _to_text(data)
    if not text:
        return {}
    try:
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        pass
    try:
        raw = base64.b64decode(text)
        decoded = zlib.decompress(raw).decode("utf-8")
        loaded = json.loads(decoded)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _extract_odds_from_any_payload(payload: Any) -> dict[str, float]:
    odds: dict[str, float] = {}
    if isinstance(payload, dict):
        name = _to_text(
            payload.get("horse_name")
            or payload.get("Bamei")
            or payload.get("bamei")
            or payload.get("name")
        )
        value = _to_float(
            payload.get("odds")
            or payload.get("Odds")
            or payload.get("tan_odds")
            or payload.get("TanOdds")
            or payload.get("NinkiOdds")
        )
        if name and value is not None:
            odds[name] = value
        for child in payload.values():
            odds.update(_extract_odds_from_any_payload(child))
    elif isinstance(payload, list):
        for child in payload:
            odds.update(_extract_odds_from_any_payload(child))
    return odds


def _extract_win_odds_from_html(html_text: str) -> dict[str, float]:
    soup = BeautifulSoup(html_text, "html.parser")
    odds: dict[str, float] = {}
    for table in soup.select("table.RaceOdds_HorseList_Table"):
        for row in table.select("tr"):
            name_cell = row.select_one("td.Horse_Name")
            odds_cell = row.select_one("td.Odds, td.Popular")
            if not name_cell or not odds_cell:
                continue
            horse_name = _to_text(name_cell.get_text(" ", strip=True))
            value = _to_float(odds_cell.get_text(" ", strip=True))
            if horse_name and value is not None:
                odds[horse_name] = value
    return odds


def _fetch_jra_win_odds_map(race_id: str) -> tuple[dict[str, float], str]:
    try:
        dde_cname = _find_jra_dde_cname(race_id)
    except Exception as exc:
        return {}, f"JRA odds fallback {type(exc).__name__}"
    if not dde_cname:
        return {}, "JRA odds fallback: 出馬表CNAME未解決"

    try:
        base, cd_text = dde_cname.rsplit("/", 1)
        cd = int(cd_text, 16)
    except ValueError:
        return {}, "JRA odds fallback: CNAME形式不正"

    # 単勝・複勝オッズ（馬番順）。JRA内部URLの変換規則は既存調査値を利用。
    odds_base = base.replace("pw01dde01", "pw151ouS3", 1)
    odds_cname = f"{odds_base}Z/{(cd + 163) % 256:02X}"
    try:
        session = build_requests_session()
        resp = session.post(
            "https://www.jra.go.jp/JRADB/accessO.html",
            data=f"cname={odds_cname}",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"https://www.jra.go.jp/JRADB/accessD.html?CNAME={dde_cname}",
            },
            timeout=10,
        )
    except Exception as exc:
        return {}, f"JRA odds fallback {type(exc).__name__}"
    if resp.status_code != 200:
        return {}, f"JRA odds fallback HTTP {resp.status_code}"
    resp.encoding = "Shift_JIS"
    odds = _extract_jra_win_odds_from_html(resp.text)
    return odds, "JRA公式 単勝オッズ" if odds else "JRA odds fallback: 単勝オッズ空"


@lru_cache(maxsize=128)
def _find_jra_dde_cname(race_id: str) -> str:
    date_text = _fetch_netkeiba_race_date(race_id)
    if not date_text:
        return ""
    if not re.match(r"^\d{12}$", race_id):
        return ""
    year = race_id[:4]
    place = race_id[4:6]
    meeting = race_id[6:8]
    day = race_id[8:10]
    race_no = race_id[10:12]
    body = f"pw01dde01{place}{year}{meeting}{day}{race_no}{date_text}"

    session = build_requests_session()
    try:
        race_no_int = int(race_no)
    except ValueError:
        race_no_int = 0
    candidate_cds: list[int] = []
    if race_no_int > 0:
        # JRAのCNAME末尾は開催/場ごとのオフセット + レース番号ステップで推移する。
        # 既知の当日開催候補を先に当て、ダメなら総当たりへ落とす。
        for offset in (0x5E, 0x65, 0x6D, 0x6E):
            candidate_cds.append((offset + race_no_int * 0x35) % 256)
    candidate_cds.extend(range(256))

    seen: set[int] = set()
    for cd in candidate_cds:
        if cd in seen:
            continue
        seen.add(cd)
        cname = f"{body}/{cd:02X}"
        try:
            resp = session.get(
                f"https://www.jra.go.jp/JRADB/accessD.html?CNAME={cname}",
                timeout=5,
            )
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        resp.encoding = "Shift_JIS"
        title = BeautifulSoup(resp.text, "html.parser").find("title")
        title_text = _to_text(title.get_text(" ", strip=True) if title else "")
        if title_text and "出馬表" in title_text:
            return cname
    return ""


@lru_cache(maxsize=128)
def _fetch_netkeiba_race_date(race_id: str) -> str:
    try:
        session = build_requests_session()
        resp = session.get(
            f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}",
            timeout=8,
        )
    except Exception:
        return ""
    if resp.status_code != 200:
        return ""
    if not resp.encoding or resp.encoding.lower() in {"iso-8859-1", "ascii"}:
        resp.encoding = "EUC-JP"
    soup = BeautifulSoup(resp.text, "html.parser")
    source = " ".join(
        _to_text(part)
        for part in [
            soup.title.get_text(" ", strip=True) if soup.title else "",
            soup.select_one("meta[property='og:title']") and soup.select_one("meta[property='og:title']").get("content"),
        ]
    )
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", source)
    if not match:
        return ""
    return f"{int(match.group(1)):04d}{int(match.group(2)):02d}{int(match.group(3)):02d}"


def _extract_jra_win_odds_from_html(html_text: str) -> dict[str, float]:
    soup = BeautifulSoup(html_text, "html.parser")
    odds: dict[str, float] = {}
    for row in soup.select("tr"):
        name_cell = row.select_one("td.horse")
        odds_cell = row.select_one("td.odds_tan")
        if not name_cell or not odds_cell:
            continue
        horse_name = _to_text(name_cell.get_text(" ", strip=True))
        value = _to_float(odds_cell.get_text(" ", strip=True))
        if horse_name and value is not None:
            odds[horse_name] = value
    return odds


def _now_time_label() -> str:
    return datetime.now().strftime("%H:%M")


def _fetch_body_weight_map(race_id: str) -> tuple[dict[str, tuple[str, str]], str]:
    if not race_id:
        return {}, ""
    csv_path = BACKEND_DATA_DIR / f"race_{race_id}.csv"
    try:
        legacy_fetch_race_csv(race_id, str(csv_path))
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception as exc:
        return {}, f"馬体重更新: {type(exc).__name__}"

    rows = _build_entry_horses(df, {}, {})
    result: dict[str, tuple[str, str]] = {}
    for row in rows:
        body_weight = _to_text(row.get("body_weight"))
        body_delta = _to_text(row.get("body_delta"))
        if not body_weight:
            continue
        horse_name = _to_text(row.get("horse_name"))
        umaban = _to_text(row.get("umaban")).lstrip("0")
        if horse_name:
            result[horse_name] = (body_weight, body_delta)
        if umaban:
            result[f"__umaban__:{umaban}"] = (body_weight, body_delta)
    return result, ""


def _merge_odds_into_horses(horses: list[dict[str, Any]], odds_map: dict[str, float], overwrite: bool = False) -> None:
    normalized = {_horse_token(name): value for name, value in odds_map.items() if not str(name).startswith("__umaban__:")}
    by_umaban = {str(name).split(":", 1)[1].lstrip("0"): value for name, value in odds_map.items() if str(name).startswith("__umaban__:")}
    for horse in horses:
        if horse.get("odds") is not None and not overwrite:
            continue
        odds = normalized.get(_horse_token(horse.get("horse_name")))
        if odds is None:
            odds = by_umaban.get(_to_text(horse.get("umaban")).lstrip("0"))
        if odds is not None:
            horse["odds"] = odds


def _merge_body_weight_into_horses(
    horses: list[dict[str, Any]],
    body_map: dict[str, tuple[str, str]],
    overwrite: bool = False,
) -> None:
    normalized = {
        _horse_token(name): value
        for name, value in body_map.items()
        if not str(name).startswith("__umaban__:")
    }
    by_umaban = {
        str(name).split(":", 1)[1].lstrip("0"): value
        for name, value in body_map.items()
        if str(name).startswith("__umaban__:")
    }
    for horse in horses:
        if horse.get("body_weight") and not overwrite:
            continue
        body = normalized.get(_horse_token(horse.get("horse_name")))
        if body is None:
            body = by_umaban.get(_to_text(horse.get("umaban")).lstrip("0"))
        if body is None:
            continue
        horse["body_weight"], horse["body_delta"] = body


def _write_odds_to_csv(csv_path: Path, odds_map: dict[str, float]) -> None:
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception:
        return
    horse_col = _first_column(df, ["馬名", "鬥ｬ蜷・", "horse_name"])
    odds_col = _first_column(df, ["オッズ", "単勝オッズ", "繧ｪ繝・ぜ", "odds"])
    if not horse_col:
        return
    if not odds_col:
        odds_col = "オッズ"
        df[odds_col] = ""
    normalized = {_horse_token(name): value for name, value in odds_map.items() if not str(name).startswith("__umaban__:")}
    by_umaban = {str(name).split(":", 1)[1].lstrip("0"): value for name, value in odds_map.items() if str(name).startswith("__umaban__:")}
    updated = False
    for idx, row in df.iterrows():
        odds = normalized.get(_horse_token(row.get(horse_col)))
        if odds is None:
            umaban_col = _first_column(df, ["馬番", "逡ｪ", "umaban"])
            odds = by_umaban.get(_to_text(row.get(umaban_col)).lstrip("0")) if umaban_col else None
        if odds is None:
            continue
        if _to_float(row.get(odds_col)) != odds:
            df.at[idx, odds_col] = f"{odds:.1f}"
            updated = True
    if updated:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")


def _build_entry_horses(
    df: pd.DataFrame,
    recent_runs: dict[str, dict],
    run_details_map: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    cols = {
        "waku": _first_column(df, ["枠番", "枠", "譫逡ｪ", "waku"]),
        "umaban": _first_column(df, ["馬番", "番", "鬥ｬ逡ｪ", "umaban"]),
        "horse_name": _first_column(df, ["馬名", "鬥ｬ蜷・", "horse_name"]),
        "sex_age": _first_column(df, ["性齢", "諤ｧ鮨｢", "sex_age"]),
        "weight": _first_column(df, ["斤量", "譁､驥・", "weight"]),
        "body_weight": _first_column(df, ["馬体重", "鬥ｬ菴馴㍾", "body_weight"]),
        "body_delta": _first_column(df, ["増減", "蠅玲ｸ・", "body_delta"]),
        "jockey": _first_column(df, ["騎手", "鬨取焔", "jockey"]),
        "odds": _first_column(df, ["オッズ", "単勝オッズ", "繧ｪ繝・ぜ", "odds"]),
    }
    if not cols["horse_name"]:
        return []
    recent_by_horse = {_horse_token(name): payload for name, payload in recent_runs.items()}
    details_by_horse = {
        _horse_token(name): payload
        for name, payload in (run_details_map or {}).items()
        if isinstance(payload, list)
    }
    horses: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        horse_name = _to_text(row.get(cols["horse_name"]))
        if not horse_name:
            continue
        recent = recent_by_horse.get(_horse_token(horse_name), {})
        style = classify_running_style(recent) or _to_text(row.get("脚質"))
        last3fs = _recent_list(recent, "last3fs", ["前走上り", "2走前上り", "3走前上り"])
        corners = _recent_list(recent, "corners", [])
        field_sizes = _recent_list(recent, "field_sizes", [])
        recent_run_values = [
            _to_text(recent.get("前走") or row.get("前走")),
            _to_text(recent.get("2走前") or row.get("2走前")),
            _to_text(recent.get("3走前") or row.get("3走前")),
        ]
        recent_run_details = _build_recent_run_details(
            recent_run_values,
            last3fs,
            corners,
            field_sizes,
            details_by_horse.get(_horse_token(horse_name), []),
        )
        horses.append({
            "horse_name": horse_name,
            "waku": _to_text(row.get(cols["waku"])) if cols["waku"] else "",
            "umaban": _to_text(row.get(cols["umaban"])) if cols["umaban"] else "",
            "sex_age": _to_text(row.get(cols["sex_age"])) if cols["sex_age"] else "",
            "weight": _to_text(row.get(cols["weight"])) if cols["weight"] else "",
            "body_weight": _to_text(row.get(cols["body_weight"])) if cols["body_weight"] else "",
            "body_delta": _to_text(row.get(cols["body_delta"])) if cols["body_delta"] else "",
            "jockey": _to_text(row.get(cols["jockey"])) if cols["jockey"] else "",
            "style": style,
            "odds": _to_float(row.get(cols["odds"])) if cols["odds"] else None,
            "recent_runs": recent_run_values,
            "last3fs": last3fs,
            "corners": corners,
            "field_sizes": field_sizes,
            "recent_run_details": recent_run_details,
        })
    return horses


def _recent_list(recent: dict, key: str, fallback_keys: list[str]) -> list[str]:
    values = recent.get(key)
    if isinstance(values, list):
        result = [_to_text(x) for x in values]
    elif isinstance(values, str):
        result = [x.strip() for x in re.split(r"[,\s/]+", values) if x.strip()]
    else:
        result = [_to_text(recent.get(fk)) for fk in fallback_keys]
    while len(result) < 3:
        result.append("")
    return result[:3]


def _fetch_run_details_for_race(
    horse_id_map: dict[str, str],
    n_recent: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    details: dict[str, list[dict[str, Any]]] = {}
    for horse_name, horse_id in horse_id_map.items():
        fetched = _fetch_horse_run_details_cached(_to_text(horse_id), n_recent)
        if fetched:
            details[horse_name] = list(fetched)
    return details


@lru_cache(maxsize=512)
def _fetch_horse_run_details_cached(horse_id: str, n_recent: int = 3) -> tuple[dict[str, Any], ...]:
    if not horse_id:
        return tuple()
    try:
        session = build_requests_session()
        resp = session.get(f"https://db.netkeiba.com/horse/result/{horse_id}/", timeout=8)
    except Exception:
        return tuple()
    if resp.status_code != 200:
        return tuple()
    if not resp.encoding or resp.encoding.lower() in {"iso-8859-1", "ascii"}:
        resp.encoding = "EUC-JP"

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.select_one("table.db_h_race_results")
    if not table:
        return tuple()

    header_row = table.select_one("tr")
    headers = [_to_text(cell.get_text(" ", strip=True)) for cell in header_row.find_all(["th", "td"])] if header_row else []
    idx = {
        "date": _header_index(headers, ["日付"]),
        "venue": _header_index_any(headers, [(["開催"], None), (["場所"], None), (["競馬場"], None)]),
        "finish": _header_index(headers, ["着順"]),
        "race_name": _header_index(headers, ["レース名"]),
        "distance": _header_index(headers, ["距離"]),
        "track": _header_index(headers, ["馬場"]),
        "race_time": _header_index(headers, ["タイム"], exclude=["指数"]),
        "margin": _header_index(headers, ["着差"]),
        "time_index": _header_index_any(headers, [(["タイム指数"], None), (["指数"], ["PCI", "ペース"])]),
        "corner": _header_index(headers, ["通過"]),
        "last3f": _header_index(headers, ["上り", "上がり"]),
        "field_size": _header_index(headers, ["頭数"]),
    }

    details: list[dict[str, Any]] = []
    for row in table.select("tr")[1:]:
        cells = row.find_all("td")
        if not cells:
            continue
        date_text = _cell_text(cells, idx["date"])
        if not re.match(r"\d{4}/\d{1,2}/\d{1,2}", date_text):
            continue
        distance = _cell_text(cells, idx["distance"])
        track = _cell_text(cells, idx["track"])
        course = f"{distance}/{track}" if distance and track else distance
        time_index = _to_float(_cell_text(cells, idx["time_index"]))
        details.append(
            {
                "date": _short_date(date_text),
                "venue": _normalize_run_venue(_cell_text(cells, idx["venue"])),
                "finish": _cell_text(cells, idx["finish"]),
                "race_name": _cell_text(cells, idx["race_name"]),
                "course": course,
                "race_time": _cell_text(cells, idx["race_time"]),
                "margin": _cell_text(cells, idx["margin"]),
                "time_index": time_index,
                "race_level": _classify_race_level(time_index),
                "last3f": _cell_text(cells, idx["last3f"]),
                "corner": _cell_text(cells, idx["corner"]).replace(" ", ""),
                "field_size": _cell_text(cells, idx["field_size"]),
            }
        )
        if len(details) >= n_recent:
            break
    return tuple(details)


def _header_index_any(headers: list[str], rules: list[tuple[list[str], list[str] | None]]) -> int | None:
    for includes, exclude in rules:
        idx = _header_index(headers, includes, exclude=exclude)
        if idx is not None:
            return idx
    return None


def _header_index(headers: list[str], includes: list[str], exclude: list[str] | None = None) -> int | None:
    exclude = exclude or []
    for idx, header in enumerate(headers):
        normalized = re.sub(r"\s+", "", header)
        if all(word in normalized for word in includes) and not any(word in normalized for word in exclude):
            return idx
    return None


def _cell_text(cells: list[Any], idx: int | None) -> str:
    if idx is None or idx < 0 or idx >= len(cells):
        return ""
    return re.sub(r"\s+", " ", cells[idx].get_text(" ", strip=True)).strip()


def _normalize_run_venue(value: str) -> str:
    text = _to_text(value)
    for venue in ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"):
        if venue in text:
            return venue
    return text


def _short_date(date_text: str) -> str:
    match = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", _to_text(date_text))
    if not match:
        return _to_text(date_text)
    return f"{match.group(1)[2:]}/{int(match.group(2)):02d}/{int(match.group(3)):02d}"


def _build_recent_run_details(
    recent_runs: list[str],
    last3fs: list[str],
    corners: list[str],
    field_sizes: list[str],
    fetched_details: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for idx in range(3):
        summary = _parse_recent_run_summary(recent_runs[idx] if idx < len(recent_runs) else "")
        fetched = fetched_details[idx] if idx < len(fetched_details) and isinstance(fetched_details[idx], dict) else {}
        time_index = _to_float(fetched.get("time_index"))
        detail = {
            "date": _to_text(fetched.get("date")) or summary.get("date", ""),
            "venue": _to_text(fetched.get("venue")) or summary.get("venue", ""),
            "finish": _to_text(fetched.get("finish")) or summary.get("finish", ""),
            "race_name": _to_text(fetched.get("race_name")) or summary.get("race_name", ""),
            "course": _to_text(fetched.get("course")) or summary.get("course", ""),
            "race_time": _to_text(fetched.get("race_time")),
            "margin": _to_text(fetched.get("margin")),
            "time_index": time_index,
            "race_level": _classify_race_level(time_index),
            "last3f": _to_text(fetched.get("last3f")) or (last3fs[idx] if idx < len(last3fs) else ""),
            "corner": _to_text(fetched.get("corner")) or (corners[idx] if idx < len(corners) else ""),
            "field_size": _to_text(fetched.get("field_size")) or (field_sizes[idx] if idx < len(field_sizes) else ""),
        }
        details.append(detail)
    return details


def _parse_recent_run_summary(text: str) -> dict[str, str]:
    value = _to_text(text)
    match = re.match(r"^(\d{2}/\d{2}/\d{2})\s+(\S+)\s+(.+)$", value)
    if not match:
        return {}
    rest = match.group(3).strip()
    tokens = rest.split()
    course = tokens[-1] if tokens else ""
    race_name = " ".join(tokens[:-1]) if len(tokens) > 1 else rest
    return {
        "date": match.group(1),
        "venue": "",
        "finish": match.group(2),
        "race_name": race_name,
        "course": course,
    }


def _classify_race_level(time_index: float | None) -> str:
    if time_index is None:
        return "指数なし"
    if time_index >= 95:
        return "S"
    if time_index >= 85:
        return "A"
    if time_index >= 75:
        return "B"
    if time_index >= 65:
        return "C"
    return "D"


def _time_level_bonus(details: list[dict[str, Any]]) -> tuple[float, str]:
    weights = [0.5, 0.3, 0.2]
    valid: list[tuple[float, float]] = []
    for detail, weight in zip(details[:3], weights):
        time_index = _to_float(detail.get("time_index")) if isinstance(detail, dict) else None
        if time_index is not None:
            valid.append((time_index, weight))
    if not valid:
        return 0.0, ""
    weight_sum = sum(weight for _, weight in valid)
    weighted_index = sum(time_index * weight for time_index, weight in valid) / weight_sum
    bonus = max(-0.03, min(0.12, (weighted_index - 70.0) / 100.0))
    level = _classify_race_level(weighted_index)
    if level in {"S", "A"}:
        return bonus, f"指数{level}"
    if weighted_index >= 75:
        return bonus, "近走指数強め"
    return bonus, ""


def _style_distribution(horses: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(_to_text(horse.get("style")) for horse in horses)
    return {style: int(counts.get(style, 0)) for style in STYLE_ORDER if counts.get(style, 0)}


def _rank_horses(horses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for horse in horses:
        odds = horse.get("odds")
        odds_num = float(odds) if isinstance(odds, (int, float)) and math.isfinite(float(odds)) else 30.0
        odds_score = max(0.0, min(1.0, 1.0 / max(odds_num, 1.0)))
        style_bonus = {"逃げ": 0.08, "先行": 0.10, "差し": 0.07, "自在": 0.05, "追込": 0.02}.get(_to_text(horse.get("style")), 0.0)
        recent_bonus = _recent_finish_bonus(horse.get("recent_runs") or [])
        time_bonus, time_reason = _time_level_bonus(horse.get("recent_run_details") or [])
        score = round(odds_score + style_bonus + recent_bonus + time_bonus, 4)
        ranked.append({
            "horse_name": horse.get("horse_name"),
            "umaban": horse.get("umaban"),
            "waku": horse.get("waku"),
            "odds": horse.get("odds"),
            "style": horse.get("style"),
            "score": score,
            "reason": _rank_reason(horse, recent_bonus, time_reason),
        })
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def _recent_finish_bonus(recent_runs: list[str]) -> float:
    bonus = 0.0
    for idx, text in enumerate(recent_runs[:3]):
        match = re.search(r"\s(\d{1,2})\s", f" {_to_text(text)} ")
        if not match:
            continue
        finish = int(match.group(1))
        weight = 0.08 if idx == 0 else (0.04 if idx == 1 else 0.02)
        if finish <= 3:
            bonus += weight
        elif finish <= 6:
            bonus += weight / 2
    return bonus


def _rank_reason(horse: dict[str, Any], recent_bonus: float, time_reason: str = "") -> str:
    parts = []
    if horse.get("odds") is not None:
        parts.append(f"単勝{float(horse['odds']):.1f}")
    if horse.get("style"):
        parts.append(f"脚質{horse['style']}")
    if recent_bonus > 0:
        parts.append("近走評価あり")
    if time_reason:
        parts.append(time_reason)
    return " / ".join(parts) or "出馬表情報ベース"


def _format_stat_line(row: dict) -> str:
    label = _to_text(row.get("label"))
    starts = int(row.get("starts") or 0)
    top3 = int(row.get("top3") or 0)
    rate = float(row.get("top3_rate") or 0)
    if not label or starts <= 0:
        return ""
    return f"{label}（複勝率{rate:.1f}% / {top3}-{max(starts - top3, 0)}）"
