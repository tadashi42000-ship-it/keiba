from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[3]
LEGACY_DIR = ROOT_DIR / "legacy" / "streamlit_app"
if str(LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_DIR))

from get_keiba_info import fetch_race_csv as legacy_fetch_race_csv  # type: ignore  # noqa: E402
from race_catalog import get_upcoming_races as legacy_get_upcoming_races  # type: ignore  # noqa: E402
from race_catalog import resolve_race_id as legacy_resolve_race_id  # type: ignore  # noqa: E402


BACKEND_DATA_DIR = ROOT_DIR / "backend" / "data"
BACKEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR_LEGACY = LEGACY_DIR / "data" / "search_cache"
CACHE_DIR_ROOT = ROOT_DIR / "data" / "search_cache"
_WEEKDAYS_JA = ("月", "火", "水", "木", "金", "土", "日")

# cache payload validation policy
ALLOWED_CACHE_TOP_LEVEL_KEYS = {
    "meta",
    "horse_df",
    "youtube_videos",
    "youtube_raw",
    "youtube_summary_df",
    "web_articles",
    "web_raw",
    "race_characteristics",
    "gates_saved",
    "yt_detail_analysis",
    "yt_video_conclusions",
    "doc_horse_raw",
    "win_rates",
    "latest_odds",
    "latest_odds_error",
    "combined_keyword",
    "yt_detail_keyword",
    "x_tweets",
    "x_raw",
    "x_newest_id",
    "training_items",
    "training_time_rows",
    "bet_plan_settings",
    "bet_plan_result",
    "bet_type_odds",
}
MAX_CACHE_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_CACHE_DEPTH = 12
MAX_CACHE_CONTAINER_ITEMS = 6000
MAX_CACHE_STRING_LENGTH = 60000
MAX_CACHE_KEY_LENGTH = 120


def _normalize_text(value: object) -> str:
    text = str(value or "")
    text = text.replace("\u3000", " ")
    return re.sub(r"\s+", "", text).lower()


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized_map = {_normalize_text(col): col for col in df.columns}
    for col in candidates:
        hit = normalized_map.get(_normalize_text(col))
        if hit is not None:
            return hit
    return None


def _first_column_by_keywords(df: pd.DataFrame, keyword_groups: list[tuple[str, ...]]) -> str | None:
    for col in df.columns:
        normalized = _normalize_text(col)
        for group in keyword_groups:
            if all(token in normalized for token in group):
                return col
    return None


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    if not text:
        return None
    if text.lower() == "nan":
        return None
    return text


def _split_race_key(race_key: str) -> tuple[date | None, str, str]:
    text = (race_key or "").strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})_([^_]+)_(.+)$", text)
    if not match:
        return None, "", ""
    try:
        race_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        race_date = None
    return race_date, match.group(2).strip(), match.group(3).strip()


def _canonical_name(text: str) -> str:
    normalized = _normalize_text(text)
    normalized = normalized.replace("・", "")
    return normalized


def _race_matches_key(race: Any, race_key: str) -> bool:
    if getattr(race, "race_key", "") == race_key:
        return True

    key_date, key_venue, key_name = _split_race_key(race_key)
    if key_date is None:
        return False

    race_date = getattr(race, "date", None)
    if race_date != key_date:
        return False

    if _canonical_name(getattr(race, "venue", "")) != _canonical_name(key_venue):
        return False

    race_name = _canonical_name(getattr(race, "race_name", ""))
    target_name = _canonical_name(key_name)
    if race_name == target_name:
        return True

    # Looser fallback: allow partial inclusion to tolerate minor naming variations.
    return bool(race_name and target_name and (race_name in target_name or target_name in race_name))


def _dedupe_races_by_key(races: list[Any]) -> list[Any]:
    deduped: list[Any] = []
    seen: set[str] = set()
    for race in races:
        key = getattr(race, "race_key", "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(race)
    return deduped


def _format_date_with_weekday(value: date) -> str:
    return f"{value:%Y/%m/%d}({_WEEKDAYS_JA[value.weekday()]})"


def _iter_cached_race_infos(start_date: date, end_date: date) -> list[dict]:
    race_map: dict[str, dict] = {}
    for cache_dir in (CACHE_DIR_LEGACY, CACHE_DIR_ROOT):
        if not cache_dir.exists():
            continue
        for path in cache_dir.glob("*.json"):
            name = path.stem
            if name.startswith("manual_"):
                continue
            match = re.match(r"^(\d{4}-\d{2}-\d{2})_([^_]+)_(.+)$", name)
            if not match:
                continue
            try:
                race_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if race_date < start_date or race_date > end_date:
                continue
            venue = match.group(2).strip()
            race_name = match.group(3).strip()
            race_key = f"{race_date.isoformat()}_{venue}_{race_name}"
            race_map.setdefault(
                race_key,
                {
                    "race_name": race_name,
                    "grade": "CACHE",
                    "date_str": _format_date_with_weekday(race_date),
                    "date_iso": race_date.isoformat(),
                    "venue": venue,
                    "distance": "",
                    "surface": "",
                    "race_id": None,
                    "race_key": race_key,
                },
            )
    return list(race_map.values())


def get_upcoming_races(
    months_ahead: int = 2,
    days_ahead: int = 14,
    days_back: int = 7,
) -> list[dict]:
    window_days_ahead = max(1, int(days_ahead))
    window_days_back = max(0, int(days_back))
    start_date = date.today() - timedelta(days=window_days_back)
    total_days = window_days_ahead + window_days_back
    races = legacy_get_upcoming_races(
        months_ahead=months_ahead,
        from_date=start_date,
        days_ahead=total_days,
    )
    race_map: dict[str, dict] = {
        race.race_key: {
            "race_name": race.race_name,
            "grade": race.grade,
            "date_str": race.date_str,
            "date_iso": race.date.isoformat(),
            "venue": race.venue,
            "distance": race.distance,
            "surface": race.surface,
            "race_id": race.race_id,
            "race_key": race.race_key,
        }
        for race in races
    }
    if window_days_back > 0:
        end_date = start_date + timedelta(days=total_days)
        for row in _iter_cached_race_infos(start_date, end_date):
            race_map.setdefault(row["race_key"], row)

    return sorted(
        race_map.values(),
        key=lambda item: (item.get("date_iso", ""), item.get("race_name", "")),
    )


def resolve_race_id_by_key(race_key: str, months_ahead: int = 2, days_ahead: int = 60) -> dict | None:
    races = list(legacy_get_upcoming_races(months_ahead=months_ahead, days_ahead=days_ahead))

    # Fallback for past/out-of-window races: fetch around race_key date.
    target_date, _, _ = _split_race_key(race_key)
    if target_date is not None:
        from_date = target_date - timedelta(days=2)
        span_days = max(days_ahead, 45)
        races.extend(
            legacy_get_upcoming_races(
                months_ahead=max(months_ahead, 2),
                from_date=from_date,
                days_ahead=span_days,
            )
        )

    races = _dedupe_races_by_key(races)
    for race in races:
        if not _race_matches_key(race, race_key):
            continue
        race_id = race.race_id or legacy_resolve_race_id(race)
        return {
            "race_key": race_key,
            "race_id": race_id,
            "resolved": bool(race_id),
        }
    return None


def fetch_race_csv_file(race_id: str, output_file: str | None = None) -> str:
    csv_path = Path(output_file) if output_file else (BACKEND_DATA_DIR / f"race_{race_id}.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    return legacy_fetch_race_csv(race_id=race_id, output_file=str(csv_path))


def fetch_odds_for_race(race_id: str) -> dict:
    csv_path = fetch_race_csv_file(race_id=race_id)
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    horse_col = _first_existing_column(df, ["馬名", "horse_name"]) or _first_column_by_keywords(
        df, [("馬", "名"), ("horse", "name")]
    )
    umaban_col = _first_existing_column(df, ["馬番", "umaban"]) or _first_column_by_keywords(
        df, [("馬", "番"), ("umaban",)]
    )
    waku_col = _first_existing_column(df, ["枠番", "waku"]) or _first_column_by_keywords(
        df, [("枠", "番"), ("waku",)]
    )
    odds_col = _first_existing_column(df, ["オッズ", "単勝オッズ", "odds"]) or _first_column_by_keywords(
        df, [("オッズ",), ("単勝",), ("odds",)]
    )

    if horse_col is None:
        raise ValueError("horse name column was not found in CSV")

    horses: list[dict] = []
    for _, row in df.iterrows():
        horse_name = _to_text(row.get(horse_col)) or ""
        horses.append(
            {
                "horse_name": horse_name,
                "umaban": _to_text(row.get(umaban_col)) if umaban_col else None,
                "waku": _to_text(row.get(waku_col)) if waku_col else None,
                "odds": _to_float(row.get(odds_col)) if odds_col else None,
            }
        )

    return {
        "race_id": race_id,
        "source_csv": str(csv_path),
        "horses": horses,
    }


def get_minimal_race_characteristics_by_key(
    race_key: str,
    months_ahead: int = 2,
    days_ahead: int = 120,
) -> dict | None:
    races = list(legacy_get_upcoming_races(months_ahead=months_ahead, days_ahead=days_ahead))
    target_date, _, _ = _split_race_key(race_key)
    if target_date is not None:
        races.extend(
            legacy_get_upcoming_races(
                months_ahead=max(months_ahead, 2),
                from_date=target_date - timedelta(days=2),
                days_ahead=max(days_ahead, 45),
            )
        )

    races = _dedupe_races_by_key(races)
    for race in races:
        if not _race_matches_key(race, race_key):
            continue
        return {
            "race_key": race_key,
            "race_id": race.race_id,
            "race_name": race.race_name,
            "grade": race.grade,
            "venue": race.venue,
            "distance": race.distance,
            "surface": race.surface,
            "characteristics": {
                "コース特徴": f"{race.venue}競馬場 {race.surface}{race.distance}",
                "注目ポイント": f"{race.grade}レース",
            },
        }
    return None


def _sanitize_race_key_for_cache(race_key: str) -> str:
    text = (race_key or "").strip()
    # Windows-forbidden filename characters and separators.
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text or "unknown_race"


def _primary_cache_dir() -> Path:
    if CACHE_DIR_LEGACY.exists():
        return CACHE_DIR_LEGACY
    if CACHE_DIR_ROOT.exists():
        return CACHE_DIR_ROOT
    return CACHE_DIR_LEGACY


def _cache_file_candidates(race_key: str) -> list[Path]:
    safe = _sanitize_race_key_for_cache(race_key)
    return [
        CACHE_DIR_LEGACY / f"{safe}.json",
        CACHE_DIR_ROOT / f"{safe}.json",
    ]


def _validate_json_node(value: Any, path: str, depth: int) -> None:
    if depth > MAX_CACHE_DEPTH:
        raise ValueError(
            f"cache payload nesting is too deep at {path} (depth={depth}, max={MAX_CACHE_DEPTH})"
        )

    if isinstance(value, dict):
        if len(value) > MAX_CACHE_CONTAINER_ITEMS:
            raise ValueError(
                f"cache payload object is too large at {path} "
                f"({len(value)} keys, max={MAX_CACHE_CONTAINER_ITEMS})"
            )
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError(f"cache payload has non-string key at {path}")
            if len(key) > MAX_CACHE_KEY_LENGTH:
                raise ValueError(
                    f"cache payload key is too long at {path} "
                    f"(len={len(key)}, max={MAX_CACHE_KEY_LENGTH})"
                )
            _validate_json_node(nested, f"{path}.{key}", depth + 1)
        return

    if isinstance(value, list):
        if len(value) > MAX_CACHE_CONTAINER_ITEMS:
            raise ValueError(
                f"cache payload array is too large at {path} "
                f"({len(value)} items, max={MAX_CACHE_CONTAINER_ITEMS})"
            )
        for idx, nested in enumerate(value):
            _validate_json_node(nested, f"{path}[{idx}]", depth + 1)
        return

    if isinstance(value, str):
        if len(value) > MAX_CACHE_STRING_LENGTH:
            raise ValueError(
                f"cache payload string is too long at {path} "
                f"(len={len(value)}, max={MAX_CACHE_STRING_LENGTH})"
            )
        return

    if isinstance(value, (int, float, bool)) or value is None:
        return

    raise ValueError(f"cache payload has unsupported value type at {path}: {type(value).__name__}")


def _estimate_payload_size_bytes(payload: dict[str, Any]) -> int:
    try:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cache payload is not JSON-serializable: {exc}") from exc
    return len(serialized.encode("utf-8"))


def validate_cache_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("cache payload must be an object")

    unknown_keys = sorted(set(payload.keys()) - ALLOWED_CACHE_TOP_LEVEL_KEYS)
    if unknown_keys:
        listed = ", ".join(unknown_keys[:8])
        suffix = " ..." if len(unknown_keys) > 8 else ""
        raise ValueError(f"cache payload has unsupported top-level keys: {listed}{suffix}")

    meta = payload.get("meta")
    if meta is not None and not isinstance(meta, dict):
        raise ValueError("cache payload meta must be an object")

    _validate_json_node(payload, path="payload", depth=0)

    payload_size = _estimate_payload_size_bytes(payload)
    if payload_size > MAX_CACHE_PAYLOAD_BYTES:
        raise ValueError(
            f"cache payload is too large: {payload_size} bytes (max={MAX_CACHE_PAYLOAD_BYTES})"
        )


def get_race_cache_by_key(race_key: str) -> dict:
    for path in _cache_file_candidates(race_key):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {
                "race_key": race_key,
                "cache_path": str(path),
                "exists": False,
                "meta": {},
                "data": {},
            }
        return {
            "race_key": race_key,
            "cache_path": str(path),
            "exists": True,
            "meta": payload.get("meta", {}),
            "data": payload,
        }

    return {
        "race_key": race_key,
        "cache_path": str(_cache_file_candidates(race_key)[0]),
        "exists": False,
        "meta": {},
        "data": {},
    }


def save_race_cache_by_key(race_key: str, payload: dict) -> dict:
    primary_dir = _primary_cache_dir()
    primary_dir.mkdir(parents=True, exist_ok=True)

    safe = _sanitize_race_key_for_cache(race_key)
    path = primary_dir / f"{safe}.json"
    tmp = path.with_suffix(path.suffix + ".tmp")

    payload_to_save = dict(payload)
    payload_to_save.setdefault("meta", {})
    if not isinstance(payload_to_save["meta"], dict):
        raise ValueError("cache payload meta must be an object")

    payload_to_save["meta"]["race_key"] = race_key
    payload_to_save["meta"]["last_updated"] = datetime.now().isoformat(timespec="seconds")
    validate_cache_payload(payload_to_save)

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload_to_save, f, ensure_ascii=False, indent=2, allow_nan=False)
    tmp.replace(path)

    return {
        "race_key": race_key,
        "cache_path": str(path),
        "saved_at": payload_to_save["meta"]["last_updated"],
    }
