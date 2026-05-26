from __future__ import annotations

import csv
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
COURSE_RECORDS_PATH = ROOT_DIR / "data" / "コースレコード.txt"
LAST3F_RECORDS_PATH = ROOT_DIR / "data" / "上がり_レコード.txt"
RATING_CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "rating_config.json"

VENUE_JA_TO_EN = {
    "東京": "Tokyo",
    "中山": "Nakayama",
    "阪神": "Hanshin",
    "京都": "Kyoto",
    "中京": "Chukyo",
    "札幌": "Sapporo",
    "函館": "Hakodate",
    "新潟": "Niigata",
    "福島": "Fukushima",
    "小倉": "Kokura",
}
SURFACE_JA_TO_EN = {"芝": "Turf", "ダ": "Dirt", "ダート": "Dirt"}
GOING_NORMALIZE = {
    "良": "Good",
    "稍重": "Yielding",
    "重": "Soft",
    "不良": "Heavy",
    "Good": "Good",
    "Yielding": "Yielding",
    "Soft": "Soft",
    "Heavy": "Heavy",
}

DEFAULT_RATING_CONFIG: dict[str, Any] = {
    "raceTimeThresholds": {"S": 0.5, "A": 1.2, "B": 2.0, "C": 3.0},
    "last3fThresholdsSec": {"S": 0.3, "A": 0.8, "B": 1.5, "C": 2.5},
    "goingFallbackAdjustments": {
        "Turf": {"Good": 0.0, "Yielding": 0.3, "Soft": 0.8, "Heavy": 1.3},
        "Dirt": {"Good": 0.0, "Yielding": -0.2, "Soft": -0.4, "Heavy": -0.5},
    },
    "weightAdjustment": {"standardWeight": 57.0, "secPerKgAt1600m": 0.15},
}


def parse_race_time_to_seconds(time_str: str | None) -> float | None:
    text = str(time_str or "").strip()
    if not text or text.upper() in {"-", "NA", "N/A", "NONE", "NAN"}:
        return None
    text = text.replace(",", "")
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return _finite_float(text)
    match = re.fullmatch(r"(\d+):(\d{1,2}(?:\.\d+)?)", text)
    if not match:
        return None
    minutes = _finite_float(match.group(1))
    seconds = _finite_float(match.group(2))
    if minutes is None or seconds is None:
        return None
    return round(minutes * 60 + seconds, 3)


@lru_cache(maxsize=1)
def load_course_records() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for row in _read_csv_rows(COURSE_RECORDS_PATH):
        venue = _normalize_venue(row.get("Racecourse"))
        surface = _normalize_surface(row.get("Surface"))
        distance = str(row.get("Distance") or "").strip()
        record_sec = parse_race_time_to_seconds(row.get("RecordTime"))
        if not venue or not surface or not distance or record_sec is None:
            continue
        key = _record_key(venue, surface, distance)
        current = records.get(key)
        if current and current.get("recordTimeSec", math.inf) <= record_sec:
            continue
        records[key] = {
            "recordTimeSec": record_sec,
            "recordTime": str(row.get("RecordTime") or "").strip(),
            "horseName": str(row.get("HorseName") or "").strip(),
            "jockey": str(row.get("Jockey") or "").strip(),
            "date": str(row.get("Date") or "").strip(),
        }
    return records


@lru_cache(maxsize=1)
def load_last3f_records() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for row in _read_csv_rows(LAST3F_RECORDS_PATH):
        venue = _normalize_venue(row.get("Racecourse"))
        surface = _normalize_surface(row.get("Surface"))
        distance_key = str(row.get("DistanceKey") or row.get("Distance") or "").strip()
        record_sec = parse_race_time_to_seconds(row.get("Record3F"))
        if not venue or not surface or not distance_key or record_sec is None:
            continue
        key = _record_key(venue, surface, distance_key)
        current = records.get(key)
        if current and current.get("record3fSec", math.inf) <= record_sec:
            continue
        records[key] = {
            "record3fSec": record_sec,
            "record3f": str(row.get("Record3F") or "").strip(),
            "horseName": str(row.get("HorseName") or "").strip(),
            "jockey": str(row.get("Jockey") or "").strip(),
            "date": str(row.get("Date") or "").strip(),
        }
    return records


@lru_cache(maxsize=1)
def load_rating_config() -> dict[str, Any]:
    try:
        payload = json.loads(RATING_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_RATING_CONFIG
    if not isinstance(payload, dict):
        return DEFAULT_RATING_CONFIG
    merged = dict(DEFAULT_RATING_CONFIG)
    for key, value in payload.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def evaluate_race_time(
    raw_race_time: str | None,
    venue: str,
    surface: str,
    distance_m: int | None,
    going: str,
    carried_weight: float | None,
) -> dict[str, Any]:
    raw_sec = parse_race_time_to_seconds(raw_race_time)
    venue_en = _normalize_venue(venue)
    surface_en = _normalize_surface(surface)
    distance = int(distance_m or 0)
    config = load_rating_config()
    track_adjustment = _get_track_adjustment(surface_en, going, config)
    weight_adjustment = _get_weight_adjustment(carried_weight, distance, config)
    corrected_sec = round(raw_sec - track_adjustment - weight_adjustment, 3) if raw_sec is not None else None
    base = {
        "grade": "-",
        "rawRaceTimeSec": raw_sec,
        "correctedRaceTimeSec": corrected_sec,
        "recordTimeSec": None,
        "recordDiffSec": None,
        "recordDiffRate": None,
        "adjustments": {
            "trackAdjustmentSec": track_adjustment,
            "weightAdjustmentSec": weight_adjustment,
        },
        "reason": "",
    }
    if raw_sec is None:
        base["reason"] = "タイム未取得"
        return base
    if not venue_en or not surface_en or not distance:
        base["reason"] = "条件不足"
        return base
    record = load_course_records().get(_record_key(venue_en, surface_en, str(distance)))
    if not record:
        base["reason"] = "レコード未収録"
        return base
    record_sec = float(record["recordTimeSec"])
    diff_sec = round((corrected_sec or raw_sec) - record_sec, 3)
    diff_rate = round(diff_sec / record_sec * 100, 3) if record_sec else None
    base.update(
        {
            "grade": _grade_from_thresholds(diff_rate, config.get("raceTimeThresholds", {}), rate=True),
            "recordTimeSec": record_sec,
            "recordDiffSec": diff_sec,
            "recordDiffRate": diff_rate,
            "recordMeta": {
                "horseName": record.get("horseName", ""),
                "jockey": record.get("jockey", ""),
                "date": record.get("date", ""),
            },
            "reason": "",
        }
    )
    return base


def evaluate_last3f(
    last3f: str | None,
    venue: str,
    surface: str,
    distance_m: int | None,
    specification: str | None = None,
) -> dict[str, Any]:
    last3f_sec = parse_race_time_to_seconds(last3f)
    venue_en = _normalize_venue(venue)
    surface_en = _normalize_surface(surface)
    distance = int(distance_m or 0)
    base = {
        "grade": "-",
        "last3fSec": last3f_sec,
        "record3fSec": None,
        "last3fDiffSec": None,
        "recordMeta": None,
        "reason": "",
    }
    if last3f_sec is None:
        base["reason"] = "上がり未取得"
        return base
    if not venue_en or not surface_en or not distance:
        base["reason"] = "条件不足"
        return base
    record = _find_last3f_record(venue_en, surface_en, distance, specification)
    if not record:
        base["reason"] = "レコード未収録"
        return base
    record_sec = float(record["record3fSec"])
    diff_sec = round(last3f_sec - record_sec, 3)
    base.update(
        {
            "grade": _grade_from_thresholds(diff_sec, load_rating_config().get("last3fThresholdsSec", {}), rate=False),
            "record3fSec": record_sec,
            "last3fDiffSec": diff_sec,
            "recordMeta": {
                "horseName": record.get("horseName", ""),
                "jockey": record.get("jockey", ""),
                "date": record.get("date", ""),
            },
            "reason": "",
        }
    )
    return base


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def _finite_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _normalize_venue(value: object) -> str:
    text = str(value or "").strip()
    if text in VENUE_JA_TO_EN:
        return VENUE_JA_TO_EN[text]
    if text in VENUE_JA_TO_EN.values():
        return text
    for ja, en in VENUE_JA_TO_EN.items():
        if ja in text or en in text:
            return en
    return ""


def _normalize_surface(value: object) -> str:
    text = str(value or "").strip()
    if text in SURFACE_JA_TO_EN:
        return SURFACE_JA_TO_EN[text]
    if text in {"Turf", "Dirt"}:
        return text
    if "芝" in text:
        return "Turf"
    if "ダート" in text or "ダ" in text:
        return "Dirt"
    return ""


def _normalize_going(value: object) -> str:
    text = str(value or "").strip()
    return GOING_NORMALIZE.get(text, text)


def _record_key(venue_en: str, surface_en: str, distance: str) -> str:
    return f"{venue_en}|{surface_en}|{distance}"


def _get_track_adjustment(surface_en: str, going: str, config: dict[str, Any]) -> float:
    normalized = _normalize_going(going) or "Good"
    adjustments = config.get("goingFallbackAdjustments")
    if not isinstance(adjustments, dict):
        return 0.0
    surface_adjustments = adjustments.get(surface_en)
    if not isinstance(surface_adjustments, dict):
        return 0.0
    value = surface_adjustments.get(normalized, 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _get_weight_adjustment(carried_weight: float | None, distance_m: int, config: dict[str, Any]) -> float:
    if carried_weight is None or not distance_m:
        return 0.0
    weight_config = config.get("weightAdjustment") if isinstance(config.get("weightAdjustment"), dict) else {}
    standard = float(weight_config.get("standardWeight", 57.0))
    sec_per_kg = float(weight_config.get("secPerKgAt1600m", 0.15))
    return round((float(carried_weight) - standard) * sec_per_kg * (distance_m / 1600), 3)


def _grade_from_thresholds(value: float | None, thresholds: dict[str, Any], *, rate: bool) -> str:
    if value is None:
        return "-"
    if value <= 0:
        return "S"
    ordered = ("S", "A", "B", "C")
    defaults = DEFAULT_RATING_CONFIG["raceTimeThresholds" if rate else "last3fThresholdsSec"]
    for grade in ordered:
        threshold = thresholds.get(grade, defaults[grade]) if isinstance(thresholds, dict) else defaults[grade]
        if value <= float(threshold):
            return grade
    return "D"


def _find_last3f_record(venue_en: str, surface_en: str, distance_m: int, specification: str | None) -> dict[str, Any] | None:
    records = load_last3f_records()
    spec = str(specification or "").strip()
    if spec:
        record = records.get(_record_key(venue_en, surface_en, f"{distance_m}-{spec}"))
        if record:
            return record
    return records.get(_record_key(venue_en, surface_en, str(distance_m)))
