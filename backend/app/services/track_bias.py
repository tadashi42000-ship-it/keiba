from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


STYLE_ORDER = ("逃げ", "先行", "差し", "追込")


def _to_int(value: Any) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _race_number_value(value: Any) -> int:
    return _to_int(value)


def _same_surface(row: dict[str, Any], surface: str) -> bool:
    return str(row.get("surface") or "").strip() == str(surface or "").strip()


def _before_target(row: dict[str, Any], target_race_number: str | None) -> bool:
    if not target_race_number:
        return True
    row_number = _race_number_value(row.get("race_number"))
    target_number = _race_number_value(target_race_number)
    return bool(row_number and target_number and row_number < target_number)


def _same_distance_band(row: dict[str, Any], distance_m: int) -> bool:
    row_distance = _to_int(row.get("distance_m"))
    return bool(row_distance and distance_m and abs(row_distance - distance_m) <= 200)


def _top3_rate(top3: int, total: int) -> float:
    return round(top3 / total, 4) if total else 0.0


def _summarize(rows: list[dict[str, Any]], *, fallback_used: bool, min_samples: int) -> dict[str, Any]:
    race_ids = {str(row.get("race_id") or "") for row in rows if row.get("race_id")}
    sample_size = len(race_ids)
    frame_total = {"inner": 0, "outer": 0}
    frame_top3 = {"inner": 0, "outer": 0}
    style_total: dict[str, int] = defaultdict(int)
    style_top3: dict[str, int] = defaultdict(int)

    for row in rows:
        finish = _to_int(row.get("finish_pos"))
        if not finish:
            continue
        waku = _to_int(row.get("waku"))
        if 1 <= waku <= 8:
            side = "inner" if waku <= 4 else "outer"
            frame_total[side] += 1
            if finish <= 3:
                frame_top3[side] += 1
        style = str(row.get("style") or "").strip()
        if style:
            style_total[style] += 1
            if finish <= 3:
                style_top3[style] += 1

    frame_bias = {
        "inner": _top3_rate(frame_top3["inner"], frame_total["inner"]),
        "outer": _top3_rate(frame_top3["outer"], frame_total["outer"]),
    }
    style_bias = {style: _top3_rate(style_top3[style], style_total[style]) for style in STYLE_ORDER}

    if sample_size < min_samples:
        return {
            "frame_bias": frame_bias,
            "style_bias": style_bias,
            "sample_size": sample_size,
            "fallback_used": fallback_used,
            "summary_label": f"サンプル不足（{sample_size}R）",
            "confidence": "low",
        }

    labels: list[str] = []
    frame_gap = frame_bias["inner"] - frame_bias["outer"]
    if frame_gap >= 0.08:
        labels.append("内枠有利")
    elif frame_gap <= -0.08:
        labels.append("外枠有利")

    best_style = ""
    best_rate = 0.0
    for style in STYLE_ORDER:
        rate = style_bias.get(style, 0.0)
        if rate > best_rate:
            best_style = style
            best_rate = rate
    if best_style and best_rate >= 0.35:
        labels.append(f"{best_style}有利")

    if not labels:
        labels.append("大きな偏りなし")
    return {
        "frame_bias": frame_bias,
        "style_bias": style_bias,
        "sample_size": sample_size,
        "fallback_used": fallback_used,
        "summary_label": " / ".join(labels),
        "confidence": "high" if sample_size >= 8 else "medium",
    }


def compute_track_bias(
    today_results: list[dict[str, Any]],
    yesterday_results: list[dict[str, Any]],
    surface: str,
    distance_m: int,
    min_samples: int = 5,
    target_race_number: str | None = None,
) -> dict[str, Any]:
    today_same_surface_before = [
        row for row in today_results if _same_surface(row, surface) and _before_target(row, target_race_number)
    ]
    same_course = [row for row in today_same_surface_before if _same_distance_band(row, distance_m)]
    if len({str(row.get("race_id") or "") for row in same_course if row.get("race_id")}) >= min_samples:
        return _summarize(same_course, fallback_used=False, min_samples=min_samples)

    if len({str(row.get("race_id") or "") for row in today_same_surface_before if row.get("race_id")}) >= min_samples:
        return _summarize(today_same_surface_before, fallback_used=True, min_samples=min_samples)

    combined = today_same_surface_before + [row for row in yesterday_results if _same_surface(row, surface)]
    return _summarize(combined, fallback_used=bool(today_same_surface_before or yesterday_results), min_samples=min_samples)
