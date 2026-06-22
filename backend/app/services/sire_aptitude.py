from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
SIRE_APTITUDE_PATH = ROOT_DIR / "backend" / "app" / "data" / "sire_aptitude.json"

MARK_SCORE = {"◎": 3, "○": 2, "△": 1, "×": 0}
SPACIOUS_VENUES = {"東京", "阪神", "京都", "新潟"}
TIGHT_VENUES = {"中山", "中京", "福島", "小倉", "札幌", "函館"}
SIRE_ALIASES = {
    "Arrogate": "アロゲート",
    "Benbatl": "ベンバトル",
    "Frankel": "フランケル",
    "Liam's Map": "リアムズマップ",
    "Mischevious Alex": "ミスチヴィアスアレックス",
    "Nyquist": "ナイキスト",
    "Sottsass": "ソットサス",
    "Vino Rosso": "ヴィノロッソ",
    "White Muzzle": "ホワイトマズル",
    "Workforce": "ワークフォース",
    "Written Tycoon": "リトゥンタイクーン",
}


@lru_cache(maxsize=1)
def load_sire_aptitude_db() -> dict[str, Any]:
    if not SIRE_APTITUDE_PATH.exists():
        return {"version": 1, "updated_at": "", "sires": {}}
    try:
        data = json.loads(SIRE_APTITUDE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "updated_at": "", "sires": {}}
    if not isinstance(data, dict):
        return {"version": 1, "updated_at": "", "sires": {}}
    if not isinstance(data.get("sires"), dict):
        data["sires"] = {}
    return data


def evaluate_sire_aptitude(
    sire_name: str,
    surface: str,
    distance_m: int,
    venue: str,
    going: str,
) -> dict[str, Any]:
    db = load_sire_aptitude_db()
    sire = str(sire_name or "").strip()
    sires = db.get("sires") or {}
    payload = None
    if isinstance(sires, dict):
        for candidate in _sire_lookup_candidates(sire):
            payload = sires.get(candidate)
            if isinstance(payload, dict):
                break
    if not isinstance(payload, dict):
        return {
            "sire_data_available": False,
            "marks": {},
            "score": 0,
            "max_score": 0,
            "summary_mark": "",
            "notes": "",
        }

    marks: dict[str, str] = {}
    _add_mark(marks, "surface", _mark_for_surface(payload, surface))
    _add_mark(marks, "distance", _mark_for_distance(payload, distance_m))
    _add_mark(marks, "course_shape", _mark_for_course_shape(payload, venue))
    if _going_bucket(going) == "soft":
        _add_mark(marks, "going", _mark_for_going(payload, going))

    score = sum(MARK_SCORE.get(mark, 0) for mark in marks.values())
    max_score = len(marks) * 3
    ratio = (score / max_score) if max_score > 0 else 0.0
    if ratio >= 0.75:
        summary = "◎"
    elif ratio >= 0.5:
        summary = "○"
    elif ratio >= 0.25:
        summary = "△"
    else:
        summary = "×"

    return {
        "sire_data_available": True,
        "marks": marks,
        "score": score,
        "max_score": max_score,
        "summary_mark": summary,
        "notes": str(payload.get("notes") or "").strip(),
    }


def _sire_lookup_candidates(sire_name: str) -> list[str]:
    sire = str(sire_name or "").strip()
    if not sire:
        return []
    candidates = [sire]
    without_country = re.sub(r"\s*\([^)]+\)\s*$", "", sire).strip()
    without_english = re.sub(r"\s+[A-Za-z].*$", "", without_country).strip()
    for candidate in (without_country, without_english):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for candidate in list(candidates):
        alias = SIRE_ALIASES.get(candidate)
        if alias and alias not in candidates:
            candidates.append(alias)
    return candidates


def _add_mark(marks: dict[str, str], axis: str, mark: str | None) -> None:
    if mark in MARK_SCORE:
        marks[axis] = mark


def _mark_for_surface(payload: dict[str, Any], surface: str) -> str | None:
    key = _surface_key(surface)
    values = payload.get("surfaces") if isinstance(payload.get("surfaces"), dict) else {}
    return values.get(key) if key else None


def _mark_for_distance(payload: dict[str, Any], distance_m: int) -> str | None:
    key = _distance_bucket(distance_m)
    values = payload.get("distances") if isinstance(payload.get("distances"), dict) else {}
    return values.get(key) if key else None


def _mark_for_course_shape(payload: dict[str, Any], venue: str) -> str | None:
    key = _course_shape_key(venue)
    values = payload.get("course_shape") if isinstance(payload.get("course_shape"), dict) else {}
    return values.get(key) if key else None


def _mark_for_going(payload: dict[str, Any], going: str) -> str | None:
    key = _going_bucket(going)
    values = payload.get("going") if isinstance(payload.get("going"), dict) else {}
    return values.get(key) if key else None


def _surface_key(surface: str) -> str:
    text = str(surface or "")
    if "芝" in text:
        return "turf"
    if "ダ" in text:
        return "dirt"
    return ""


def _distance_bucket(distance_m: int) -> str:
    try:
        distance = int(distance_m)
    except (TypeError, ValueError):
        distance = 0
    if distance <= 1400:
        return "sprint"
    if distance <= 1700:
        return "mile"
    if distance <= 2100:
        return "intermediate"
    return "long"


def _course_shape_key(venue: str) -> str:
    text = str(venue or "")
    for name in SPACIOUS_VENUES:
        if name in text:
            return "spacious"
    for name in TIGHT_VENUES:
        if name in text:
            return "tight"
    return ""


def _going_bucket(going: str) -> str:
    text = re.sub(r"\s+", "", str(going or ""))
    if not text:
        return "firm"
    if any(token in text for token in ("不良", "不", "稍重", "稍", "やや重", "重")):
        return "soft"
    return "firm" if "良" in text else "soft"
