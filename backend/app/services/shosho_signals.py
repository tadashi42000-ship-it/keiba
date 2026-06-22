from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from itertools import combinations
from typing import Any

# Tunable defaults based on docs/shosho-baken-method.md:
# - value curve and win odds band: §3, §5-1
# - value flags: §5-1, §6
# - danger flags: §7
# - axis demerits: §8
# - venue constants: §10
SHOSHO_SCHEMA_VERSION = "v3"

AXIS_DEMERIT_COEF = 0.03
AXIS_DEMERIT_MAX_PENALTY = 0.30

LAYOFF_DAYS = 180
DISTANCE_CHANGE_M = 200
BODY_WEIGHT_SWING_KG = 15

POPULAR_ODDS_RANK_MAX = 4
POPULAR_ODDS_THRESHOLD = 5.0
VALUE_ODDS_MIN = 4.0
VALUE_ODDS_MAX_EXCLUSIVE = 10.0
MID_LONG_ODDS_MIN = 5.0
# 「荒れ（3連複向き）」判定の絞り込み定数。
# value_candidates は ev ピーク(0.60)を超える＝妙味フラグ持ちの 4〜9.9 倍馬のみ。
CLEAR_FAVORITE_ODDS = 2.5
ROUGH_VALUE_SCORE_MIN = 0.60
ROUGH_VALUE_CANDIDATES = 3
TRIO_HATSURAN_SHRINK = 0.55
TRIO_HATSURAN_STOP = 0.70

DANGER_WEIGHTS = {
    "front_runner_overbet": 0.08,
    "muddy_track_rebound": 0.06,
    "filly_only_to_mixed_dirt": 0.08,
    "layoff_popular": 0.06,
}
VALUE_WEIGHTS = {
    "distance_shorten": 0.07,
    "prev_finish_4_6": 0.06,
    "turf_to_dirt": 0.05,
    "turf_to_dirt_heavy": 0.07,
    "course_return": 0.04,
    "pin_par": 0.04,
    "course_fit": 0.03,
    "distance_fit": 0.03,
    "going_fit": 0.02,
}
AXIS_DEMERIT_POINTS = {
    "front_runner_axis": -5,
    "muddy_track_axis": -4,
    "distance_extend": -5,
    "local_to_main": -4,
    "filly_only_to_mixed_dirt_axis": -5,
    "layoff_axis": -3,
    "first_surface": -5,
    "heavy_handicap": -3,
    "body_weight_swing": -2,
    "no_slope_success": -2,
    "handedness_concern": -1,
    "winter_filly": -1,
    "summer_male": -1,
    "jockey_change_axis": -1,
}

LOCAL_VENUES = {"札幌", "函館", "福島", "新潟", "小倉"}
MAIN_VENUES = {"東京", "中山", "中京", "京都", "阪神"}
STEEP_SLOPE_VENUES = {"中山", "阪神", "中京"}
HANDEDNESS = {
    "札幌": "右",
    "函館": "右",
    "福島": "右",
    "新潟": "左",
    "東京": "左",
    "中山": "右",
    "中京": "左",
    "京都": "右",
    "阪神": "右",
    "小倉": "右",
}

# Data for 初ブリンカー, 昇級初戦, and 前走枠替わり is not available in
# current snapshots. Do not infer those rules until entry/run-detail ingestion is expanded.


@dataclass(frozen=True)
class ShoshoRaceContext:
    race_name: str = ""
    grade: str = ""
    venue: str = ""
    surface: str = ""
    distance_m: int = 0
    going: str = "良"
    race_date: date | None = None
    race_month: int = 0
    field_size: int = 0
    is_handicap: bool = False
    is_filly_only: bool = False
    is_two_year_old: bool = False
    odds_available: bool = False
    top_handicap_weight: float = 0.0
    odds_rank_by_key: dict[tuple[str, str], int] = field(default_factory=dict)
    style_distribution: dict[str, int] = field(default_factory=dict)
    track_bias: dict[str, Any] = field(default_factory=dict)


def evaluate_shosho_signals(horse: dict[str, Any], ctx: ShoshoRaceContext) -> dict[str, Any]:
    danger_flags: list[dict[str, Any]] = []
    value_flags: list[dict[str, Any]] = []
    axis_demerits: list[dict[str, Any]] = []

    first = _first_detail(horse)
    recent_details = _recent_details(horse)

    if first:
        style = _corner_style(_to_text(first.get("corner")), _to_text(first.get("field_size")))
        finish = _finish_int(first.get("finish"))
        if style == "逃げ" and finish is not None and finish <= 3:
            _add_flag(danger_flags, "front_runner_overbet", "前走逃げ好走", DANGER_WEIGHTS["front_runner_overbet"])
            _add_demerit(axis_demerits, "front_runner_axis", "前走逃げ好走", AXIS_DEMERIT_POINTS["front_runner_axis"])

        previous_going = _to_text(first.get("going"))
        if _going_bucket(previous_going) == "soft" and finish is not None and finish <= 3 and _going_bucket(ctx.going) == "firm":
            _add_flag(danger_flags, "muddy_track_rebound", "特殊馬場好走→良", DANGER_WEIGHTS["muddy_track_rebound"])
            _add_demerit(axis_demerits, "muddy_track_axis", "特殊馬場好走→良", AXIS_DEMERIT_POINTS["muddy_track_axis"])

        previous_distance = _to_int(first.get("distance_m"))
        if previous_distance and ctx.distance_m:
            diff = previous_distance - ctx.distance_m
            if diff >= DISTANCE_CHANGE_M:
                _add_flag(value_flags, "distance_shorten", "距離短縮", VALUE_WEIGHTS["distance_shorten"])
            elif -diff >= DISTANCE_CHANGE_M:
                _add_demerit(axis_demerits, "distance_extend", "距離延長", AXIS_DEMERIT_POINTS["distance_extend"])

        if finish is not None and 4 <= finish <= 6:
            _add_flag(value_flags, "prev_finish_4_6", "前走4-6着", VALUE_WEIGHTS["prev_finish_4_6"])

        previous_surface = _normalize_surface(first.get("surface"))
        if previous_surface == "芝" and ctx.surface == "ダ":
            code = "turf_to_dirt_heavy" if (_horse_weight(horse) or 0) >= 460 else "turf_to_dirt"
            _add_flag(value_flags, "turf_to_dirt", "芝→ダ替わり", VALUE_WEIGHTS[code])

        if _to_text(first.get("venue")) == ctx.venue and finish is not None and finish <= 3:
            _add_flag(value_flags, "course_return", "得意コース回帰", VALUE_WEIGHTS["course_return"])

        if _to_text(first.get("venue")) in LOCAL_VENUES and ctx.venue in MAIN_VENUES:
            _add_demerit(axis_demerits, "local_to_main", "前走ローカル", AXIS_DEMERIT_POINTS["local_to_main"])

        if _to_text(first.get("race_name")) and "牝" in _to_text(first.get("race_name")) and not ctx.is_filly_only and ctx.surface == "ダ":
            _add_flag(danger_flags, "filly_only_to_mixed_dirt", "牝限→牡馬混合ダ", DANGER_WEIGHTS["filly_only_to_mixed_dirt"])
            _add_demerit(axis_demerits, "filly_only_to_mixed_dirt_axis", "牝限→牡馬混合ダ", AXIS_DEMERIT_POINTS["filly_only_to_mixed_dirt_axis"])

        previous_date = _parse_run_date(first.get("date"))
        if ctx.race_date and previous_date and (ctx.race_date - previous_date).days >= LAYOFF_DAYS:
            _add_flag(danger_flags, "layoff_popular", "半年以上休み明け", DANGER_WEIGHTS["layoff_popular"])
            _add_demerit(axis_demerits, "layoff_axis", "半年以上休み明け", AXIS_DEMERIT_POINTS["layoff_axis"])

        previous_jockey = _to_text(first.get("jockey"))
        current_jockey = _to_text(horse.get("jockey"))
        if previous_jockey and current_jockey and previous_jockey != current_jockey:
            _add_demerit(axis_demerits, "jockey_change_axis", "騎手乗り替わり", AXIS_DEMERIT_POINTS["jockey_change_axis"])

    if ctx.surface and recent_details and not any(_normalize_surface(detail.get("surface")) == ctx.surface for detail in recent_details):
        _add_demerit(axis_demerits, "first_surface", f"初{ctx.surface}", AXIS_DEMERIT_POINTS["first_surface"])

    if _is_pin_par(recent_details):
        _add_flag(value_flags, "pin_par", "ピンパー", VALUE_WEIGHTS["pin_par"])

    if ctx.is_handicap and _is_high_handicap_weight(horse, ctx):
        _add_demerit(axis_demerits, "heavy_handicap", "ハンデ斤量重め", AXIS_DEMERIT_POINTS["heavy_handicap"])

    body_delta = _signed_int(horse.get("body_delta"))
    if body_delta is not None and abs(body_delta) >= BODY_WEIGHT_SWING_KG:
        _add_demerit(axis_demerits, "body_weight_swing", "馬体重±15kg以上", AXIS_DEMERIT_POINTS["body_weight_swing"])

    if ctx.venue in STEEP_SLOPE_VENUES and not _has_steep_slope_success(recent_details):
        _add_demerit(axis_demerits, "no_slope_success", "坂実績なし", AXIS_DEMERIT_POINTS["no_slope_success"])

    handedness = HANDEDNESS.get(ctx.venue)
    if handedness and _has_handedness_concern(recent_details, handedness):
        _add_demerit(axis_demerits, "handedness_concern", f"{handedness}回り不安", AXIS_DEMERIT_POINTS["handedness_concern"])

    sex_age = _to_text(horse.get("sex_age"))
    month = ctx.race_month
    if month in {12, 1, 2} and "牝" in sex_age:
        _add_demerit(axis_demerits, "winter_filly", "冬の牝馬", AXIS_DEMERIT_POINTS["winter_filly"])
    if month in {6, 7, 8, 9} and "牡" in sex_age:
        _add_demerit(axis_demerits, "summer_male", "夏の牡馬", AXIS_DEMERIT_POINTS["summer_male"])

    if ctx.venue and _has_recent_success(recent_details, venue=ctx.venue) and not _has_flag(value_flags, "course_return"):
        _add_flag(value_flags, "course_fit", "コース適性", VALUE_WEIGHTS["course_fit"])
    if ctx.distance_m and _has_recent_success(recent_details, distance_m=ctx.distance_m):
        _add_flag(value_flags, "distance_fit", "距離適性", VALUE_WEIGHTS["distance_fit"])
    if ctx.going and _has_recent_success(recent_details, going=ctx.going):
        _add_flag(value_flags, "going_fit", "馬場適性", VALUE_WEIGHTS["going_fit"])

    # Data for training, paddock, photo-paddock, class-rise first start, first
    # blinkers, and frame-switch detection is not collected in current snapshots.
    # Keep those detectors disabled instead of inferring unsupported signals.

    axis_total = sum(int(item.get("points") or 0) for item in axis_demerits)
    return {
        "danger_flags": danger_flags,
        "value_flags": value_flags,
        "axis_demerits": axis_demerits,
        "axis_demerit_total": axis_total,
    }


def ev_curve(odds: float | int | None) -> float:
    if not isinstance(odds, (int, float)) or not math.isfinite(float(odds)):
        return 0.0
    value = float(odds)
    if value < 1.0:
        return 0.0
    if value < 2.0:
        return -0.20
    if value < 4.0:
        return 0.20
    if value < 10.0:
        return 0.60
    if value < 15.0:
        return 0.35
    if value < 30.0:
        return 0.20
    return 0.08


def horse_key(horse: dict[str, Any]) -> tuple[str, str]:
    return (_to_text(horse.get("umaban")), _to_text(horse.get("horse_name")))


def danger_penalty_applies(horse: dict[str, Any], ctx: ShoshoRaceContext) -> bool:
    odds = _to_float(horse.get("odds"))
    rank = ctx.odds_rank_by_key.get(horse_key(horse))
    return (rank is not None and rank <= POPULAR_ODDS_RANK_MAX) or (odds is not None and odds < POPULAR_ODDS_THRESHOLD)


def value_score(odds: float | int | None, signals: dict[str, Any], horse: dict[str, Any], ctx: ShoshoRaceContext) -> float:
    value_bonus = sum(float(item.get("weight") or 0.0) for item in signals.get("value_flags") or [])
    danger_penalty = 0.0
    if danger_penalty_applies(horse, ctx):
        danger_penalty = sum(float(item.get("weight") or 0.0) for item in signals.get("danger_flags") or [])
    return round(ev_curve(odds) + value_bonus - danger_penalty, 4)


def axis_score(ability_score: float, axis_demerit_total: int) -> float:
    penalty = min(abs(axis_demerit_total) * AXIS_DEMERIT_COEF, AXIS_DEMERIT_MAX_PENALTY)
    return round(ability_score - penalty, 4)


def recommend_bets(
    ranked: list[dict[str, Any]],
    ctx: ShoshoRaceContext,
    budget_yen: int,
    *,
    provisional_only: bool = False,
) -> dict[str, Any]:
    shape = _race_shape(ranked, ctx)
    if provisional_only:
        return {
            "race_shape": shape,
            "tickets": [],
            "note": "馬番/枠番が未確定のため正式買い目は作成せず、2軸評価のみ表示します。",
        }
    if not ctx.odds_available:
        return {
            "race_shape": shape,
            "tickets": [],
            "note": "オッズ未公開のため妙味・推奨は限定（軽量更新後に再評価）",
        }

    if shape["is_solid"]:
        return {
            "race_shape": shape,
            "tickets": [_skip_ticket("見送り", "1倍台人気が素直で妙味候補が薄い")],
            "note": "堅い人気決着寄り。買わない判断を優先します。",
        }

    tickets: list[dict[str, Any]] = []
    tickets.extend(_win_recommendations(ranked, budget_yen, shape))
    tickets.extend(_wide_recommendations(ranked, budget_yen))
    tickets.extend(_quinella_recommendations(ranked, budget_yen))
    trio_note = ""
    if shape["is_rough"]:
        hatsuran_do = float(shape.get("hatsuran_do") or 0.0)
        if hatsuran_do >= TRIO_HATSURAN_STOP:
            shape["trio_policy"] = "stop"
            trio_note = " 極端な波乱度のため3連複は停止し、単勝/ワイド/馬連へ寄せます。"
        elif hatsuran_do >= TRIO_HATSURAN_SHRINK:
            shape["trio_policy"] = "shrink"
            tickets.extend(_trio_compact_recommendations(ranked, budget_yen))
            trio_note = " 波乱度高めのため3連複は6点以内に縮小します。"
        else:
            shape["trio_policy"] = "normal"
            tickets.extend(_trio_recommendations(ranked, budget_yen, ctx))

    if not tickets:
        tickets.append(_skip_ticket("見送り", "妙味候補または軸候補が条件不足"))
    return {
        "race_shape": shape,
        "tickets": tickets,
        "note": f"丞相メソッドの単勝/ワイド/馬連/3連複ルールで点数を絞っています。{trio_note}".strip(),
    }


def _race_shape(ranked: list[dict[str, Any]], ctx: ShoshoRaceContext) -> dict[str, Any]:
    favorite = min(
        (item for item in ranked if _to_float(item.get("odds")) is not None),
        key=lambda item: _to_float(item.get("odds")) or 999.0,
        default=None,
    )
    has_dangerous_favorite = bool(
        favorite and favorite.get("danger_flags") and favorite.get("danger_penalty_applied")
    )
    favorite_odds = _to_float(favorite.get("odds")) if favorite else None
    # 「穴候補」= 4〜9.9倍 かつ §6 の妙味フラグを持つ馬（単なる人気薄ではない）。
    value_candidates = [
        item for item in ranked
        if _is_value_odds(item.get("odds"))
        and float(item.get("value_score") or 0.0) > ROUGH_VALUE_SCORE_MIN
        and item.get("value_flags")
    ]
    has_clear_favorite = bool(
        favorite
        and favorite_odds is not None
        and favorite_odds < CLEAR_FAVORITE_ODDS
        and not favorite.get("danger_penalty_applied")
    )
    has_strong_short_favorite = bool(
        favorite and (favorite_odds or 999.0) < 2.0 and not favorite.get("danger_penalty_applied")
    )
    is_graded = ctx.grade in {"G1", "G2", "G3"}
    is_solid = has_strong_short_favorite and not value_candidates
    # 3連複向きの「荒れ」= 構造的条件（危険人気/ハンデ/牝馬限定"重賞"/2歳）
    # または「明確な人気馬が不在 ＆ 妙味フラグ付きの穴が複数」(§6)。
    is_rough = (
        has_dangerous_favorite
        or ctx.is_handicap
        or (ctx.is_filly_only and is_graded)
        or ctx.is_two_year_old
        or (len(value_candidates) >= ROUGH_VALUE_CANDIDATES and not has_clear_favorite)
    )
    labels: list[str] = []
    if has_dangerous_favorite:
        labels.append("危険人気あり")
    if is_solid:
        labels.append("堅い")
    if is_rough:
        labels.append("荒れ注意")
    hatsuran_do = _hatsuran_do(
        favorite_odds=favorite_odds,
        has_dangerous_favorite=has_dangerous_favorite,
        has_clear_favorite=has_clear_favorite,
        value_candidate_count=len(value_candidates),
        ctx=ctx,
    )
    return {
        "has_dangerous_favorite": has_dangerous_favorite,
        "is_rough": is_rough,
        "is_solid": is_solid,
        "value_candidate_count": len(value_candidates),
        "label": " / ".join(labels) if labels else "標準",
        "hatsuran_do": hatsuran_do,
        "axis_place_prob": _axis_place_prob(ranked, favorite),
        "aite_confidence": _aite_confidence(ranked),
        "pace_pattern": _pace_pattern(ctx),
    }


def _win_recommendations(ranked: list[dict[str, Any]], budget_yen: int, shape: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        item for item in sorted(ranked, key=lambda row: row.get("value_score", 0), reverse=True)
        if _is_value_odds(item.get("odds")) and _to_text(item.get("umaban"))
    ]
    if not candidates:
        return []
    horse = candidates[0]
    amount = _unit_amount(budget_yen, 4 if shape.get("has_dangerous_favorite") else 6)
    return [{
        "type": "単勝",
        "selection": _to_text(horse.get("umaban")),
        "horse_names": [_to_text(horse.get("horse_name"))],
        "amount_yen": amount,
        "reason": "4〜9.9倍の妙味帯を優先",
        "strategy": "単勝妙味",
        "point_note": "1点",
        "max_points": 1,
    }]


def _wide_recommendations(ranked: list[dict[str, Any]], budget_yen: int) -> list[dict[str, Any]]:
    axes = [
        item for item in sorted(ranked, key=lambda row: row.get("axis_score", -999), reverse=True)
        if _to_text(item.get("umaban")) and int(item.get("axis_demerit_total") or 0) >= -5
    ]
    values = [
        item for item in sorted(ranked, key=lambda row: row.get("value_score", -999), reverse=True)
        if _to_text(item.get("umaban"))
    ]
    if not axes:
        return []
    axis = axes[0]
    partners = [item for item in values if item is not axis and item.get("umaban") != axis.get("umaban")][:3]
    if not partners:
        return []
    selection = f"{axis.get('umaban')}-" + ",".join(_to_text(item.get("umaban")) for item in partners)
    return [{
        "type": "ワイド",
        "selection": selection,
        "horse_names": [_to_text(axis.get("horse_name"))] + [_to_text(item.get("horse_name")) for item in partners],
        "amount_yen": _unit_amount(budget_yen, 6),
        "reason": "軸信頼上位から妙味上位へ流し",
        "strategy": "ワイド人気×穴",
        "point_note": f"{len(partners)}点",
        "max_points": 3,
    }]


def _quinella_recommendations(ranked: list[dict[str, Any]], budget_yen: int) -> list[dict[str, Any]]:
    candidates = [
        item for item in sorted(ranked, key=lambda row: (row.get("axis_score", 0) + row.get("value_score", 0)), reverse=True)
        if _to_text(item.get("umaban")) and not (1.0 <= (_to_float(item.get("odds")) or 999.0) < 2.0)
    ][:4]
    pairs = list(combinations(candidates, 2))[:6]
    if not pairs:
        return []
    selection = ",".join(f"{a.get('umaban')}-{b.get('umaban')}" for a, b in pairs)
    names = sorted({_to_text(item.get("horse_name")) for pair in pairs for item in pair if _to_text(item.get("horse_name"))})
    return [{
        "type": "馬連",
        "selection": selection,
        "horse_names": names,
        "amount_yen": _unit_amount(budget_yen, 8),
        "reason": "1倍台軸を避け、6点以内に圧縮",
        "strategy": "馬連厳選",
        "point_note": f"{len(pairs)}点以内",
        "max_points": 6,
    }]


def _trio_recommendations(ranked: list[dict[str, Any]], budget_yen: int, ctx: ShoshoRaceContext) -> list[dict[str, Any]]:
    fixed = _trio_18_point_ticket(ranked, budget_yen, ctx)
    if fixed:
        return [fixed]
    return _trio_generic_recommendations(ranked, budget_yen)


def _trio_compact_recommendations(ranked: list[dict[str, Any]], budget_yen: int) -> list[dict[str, Any]]:
    axes = [
        item for item in sorted(ranked, key=lambda row: row.get("axis_score", -999), reverse=True)
        if _to_text(item.get("umaban")) and int(item.get("axis_demerit_total") or 0) >= -5
    ][:1]
    values = [
        item for item in sorted(ranked, key=lambda row: row.get("value_score", -999), reverse=True)
        if _to_text(item.get("umaban")) and item not in axes
    ][:4]
    combos: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for axis in axes:
        for a, b in combinations(values, 2):
            combos.append((axis, a, b))
            if len(combos) >= 6:
                break
    if not combos:
        return []
    selection = ",".join("-".join(_to_text(item.get("umaban")) for item in combo) for combo in combos)
    names = sorted({_to_text(item.get("horse_name")) for combo in combos for item in combo if _to_text(item.get("horse_name"))})
    return [{
        "type": "3連複",
        "selection": selection,
        "horse_names": names,
        "amount_yen": _unit_amount(budget_yen, 16),
        "reason": "波乱度高めのため軸1頭×妙味4頭で6点以内に圧縮",
        "strategy": "3連複縮小",
        "point_note": f"{len(combos)}点以内",
        "max_points": 6,
    }]


def _trio_18_point_ticket(ranked: list[dict[str, Any]], budget_yen: int, ctx: ShoshoRaceContext) -> dict[str, Any] | None:
    if not (ctx.odds_available and ctx.odds_rank_by_key):
        return None
    rows = [
        item for item in ranked
        if _to_text(item.get("umaban")) and _odds_rank(item, ctx) is not None
    ]
    if len(rows) < 10:
        return None

    axis_candidates = [item for item in rows if 2 <= int(_odds_rank(item, ctx) or 99) <= 4]
    axis = _best_by_value(axis_candidates)
    if not axis:
        return None

    middle_rank_candidates = [
        item for item in rows
        if item is not axis and 3 <= int(_odds_rank(item, ctx) or 99) <= 6
    ]
    b = _best_by_value(middle_rank_candidates)
    hole_candidates = [
        item for item in rows
        if item is not axis and item is not b and int(_odds_rank(item, ctx) or 0) >= 5
    ]
    holes = sorted(hole_candidates, key=_value_sort_key, reverse=True)[:2]
    if not b or len(holes) < 2:
        return None

    favorite = next((item for item in rows if _odds_rank(item, ctx) == 1), None)
    if not favorite:
        return None

    second_column = _unique_items([b, *holes])
    if len(second_column) != 3:
        return None

    used = {horse_key(item) for item in [axis, favorite, *second_column]}
    delta_candidates = [item for item in rows if horse_key(item) not in used]
    deltas = sorted(delta_candidates, key=_delta_sort_key, reverse=True)[:4]
    third_column = _unique_items([favorite, *second_column, *deltas])
    if len(third_column) != 8:
        return None

    combos: set[tuple[str, str, str]] = set()
    for second in second_column:
        for third in third_column:
            if horse_key(third) in {horse_key(axis), horse_key(second)}:
                continue
            umabans = tuple(sorted(
                (_to_text(axis.get("umaban")), _to_text(second.get("umaban")), _to_text(third.get("umaban"))),
                key=_umaban_sort_key,
            ))
            combos.add(umabans)
    if len(combos) != 18:
        return None

    selection = ",".join("-".join(combo) for combo in sorted(combos, key=lambda combo: [_umaban_sort_key(value) for value in combo]))
    combo_umabans = {umaban for combo in combos for umaban in combo}
    names = sorted({
        _to_text(item.get("horse_name"))
        for item in rows
        if _to_text(item.get("umaban")) in combo_umabans and _to_text(item.get("horse_name"))
    })
    return {
        "type": "3連複",
        "selection": selection,
        "horse_names": names,
        "amount_yen": _unit_amount(budget_yen, 10),
        "reason": "1番人気は3列目(合成オッズ低下回避)/2列目に穴2頭",
        "strategy": "3連複18点鉄板",
        "point_note": "18点",
        "max_points": 20,
    }


def _trio_generic_recommendations(ranked: list[dict[str, Any]], budget_yen: int) -> list[dict[str, Any]]:
    axes = [
        item for item in sorted(ranked, key=lambda row: row.get("axis_score", -999), reverse=True)
        if _to_text(item.get("umaban"))
    ][:2]
    values = [
        item for item in sorted(ranked, key=lambda row: row.get("value_score", -999), reverse=True)
        if _to_text(item.get("umaban")) and item not in axes
    ][:8]
    combos: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for axis in axes[:1]:
        for a, b in combinations(values, 2):
            combos.append((axis, a, b))
            if len(combos) >= 20:
                break
        if combos:
            break
    if not combos:
        return []
    selection = ",".join("-".join(_to_text(item.get("umaban")) for item in combo) for combo in combos)
    names = sorted({_to_text(item.get("horse_name")) for combo in combos for item in combo if _to_text(item.get("horse_name"))})
    return [{
        "type": "3連複",
        "selection": selection,
        "horse_names": names,
        "amount_yen": _unit_amount(budget_yen, 10),
        "reason": "荒れ条件で人気軸から穴へ、20点以内",
        "strategy": "3連複荒れ回収",
        "point_note": f"{len(combos)}点以内",
        "max_points": 20,
    }]


def _hatsuran_do(
    *,
    favorite_odds: float | None,
    has_dangerous_favorite: bool,
    has_clear_favorite: bool,
    value_candidate_count: int,
    ctx: ShoshoRaceContext,
) -> float:
    score = 0.28
    if favorite_odds is not None:
        if favorite_odds < 2.0:
            score -= 0.16
        elif favorite_odds >= 3.5:
            score += 0.12
    if has_clear_favorite:
        score -= 0.12
    if has_dangerous_favorite:
        score += 0.22
    score += min(value_candidate_count, 5) * 0.08
    if ctx.is_handicap:
        score += 0.12
    if ctx.is_filly_only and ctx.grade in {"G1", "G2", "G3"}:
        score += 0.08
    if ctx.is_two_year_old:
        score += 0.10
    return round(_clamp(score, 0.0, 1.0), 3)


def _axis_place_prob(ranked: list[dict[str, Any]], favorite: dict[str, Any] | None) -> float:
    odds_rows = [item for item in ranked if _to_float(item.get("odds")) and (_to_float(item.get("odds")) or 0) > 0]
    implied_sum = sum(1.0 / float(_to_float(item.get("odds")) or 999.0) for item in odds_rows)
    favorite_prob = 0.35
    if favorite and implied_sum > 0:
        favorite_prob = (1.0 / float(_to_float(favorite.get("odds")) or 999.0)) / implied_sum
    best_axis = max((float(item.get("axis_score") or 0.0) for item in ranked), default=0.0)
    axis_component = _clamp(0.38 + best_axis, 0.18, 0.72)
    return round(_clamp(favorite_prob * 0.55 + axis_component * 0.45, 0.0, 1.0), 3)


def _aite_confidence(ranked: list[dict[str, Any]]) -> str:
    value_rows = sorted(ranked, key=lambda item: float(item.get("value_score") or -999.0), reverse=True)
    challengers = value_rows[1:4] if len(value_rows) > 1 else value_rows
    best = max((float(item.get("value_score") or 0.0) for item in challengers), default=0.0)
    if best >= 0.68:
        return "A"
    if best >= 0.48:
        return "B"
    return "C"


def _pace_pattern(ctx: ShoshoRaceContext) -> str:
    distribution = ctx.style_distribution or {}
    front_count = int(distribution.get("逃げ") or 0) + int(distribution.get("先行") or 0)
    field_size = max(ctx.field_size, sum(int(value or 0) for value in distribution.values()), 1)
    track_bias = ctx.track_bias if isinstance(ctx.track_bias, dict) else {}
    bias_label = _to_text(track_bias.get("summary_label"))
    confidence = _to_text(track_bias.get("confidence"))
    if confidence in {"high", "medium"} and bias_label and bias_label != "サンプル不足":
        return "TB重視"
    if front_count <= 2:
        return "前残り"
    if front_count >= max(5, math.ceil(field_size * 0.42)):
        return "前潰れ"
    return "能力重視"


def _odds_rank(item: dict[str, Any], ctx: ShoshoRaceContext) -> int | None:
    return ctx.odds_rank_by_key.get(horse_key(item))


def _best_by_value(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    return sorted(items, key=_value_sort_key, reverse=True)[0]


def _value_sort_key(item: dict[str, Any]) -> tuple[float, float, float]:
    odds = _to_float(item.get("odds")) or 999.0
    return (
        float(item.get("value_score") or -999.0),
        float(item.get("axis_score") or -999.0),
        -odds,
    )


def _delta_sort_key(item: dict[str, Any]) -> tuple[float, float]:
    rank_hint = 100 - (_to_float(item.get("odds")) or 0.0)
    return (float(item.get("value_score") or -999.0), -rank_hint)


def _unique_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = horse_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _umaban_sort_key(value: Any) -> tuple[int, str]:
    text = _to_text(value)
    number = _to_int(text)
    return (number if number is not None else 99, text)


def _skip_ticket(strategy: str, reason: str) -> dict[str, Any]:
    return {
        "type": "見送り",
        "selection": "-",
        "horse_names": [],
        "amount_yen": 0,
        "reason": reason,
        "strategy": strategy,
        "point_note": "0点",
        "max_points": 0,
    }


def _unit_amount(budget_yen: int, divisor: int) -> int:
    return max(100, int(max(budget_yen, 100) / divisor / 100) * 100)


def _is_value_odds(odds: Any) -> bool:
    parsed = _to_float(odds)
    return parsed is not None and VALUE_ODDS_MIN <= parsed < VALUE_ODDS_MAX_EXCLUSIVE


def _first_detail(horse: dict[str, Any]) -> dict[str, Any]:
    details = _recent_details(horse)
    return details[0] if details else {}


def _recent_details(horse: dict[str, Any]) -> list[dict[str, Any]]:
    return [detail for detail in horse.get("recent_run_details") or [] if isinstance(detail, dict)]


def _add_flag(flags: list[dict[str, Any]], code: str, label: str, weight: float) -> None:
    flags.append({"code": code, "label": label, "weight": round(weight, 4)})


def _add_demerit(demerits: list[dict[str, Any]], code: str, label: str, points: int) -> None:
    demerits.append({"code": code, "label": label, "points": points})


def _has_flag(flags: list[dict[str, Any]], code: str) -> bool:
    return any(item.get("code") == code for item in flags)


def _has_recent_success(
    details: list[dict[str, Any]],
    *,
    venue: str | None = None,
    distance_m: int | None = None,
    going: str | None = None,
) -> bool:
    for detail in details:
        finish = _finish_int(detail.get("finish"))
        if finish is None or finish > 3:
            continue
        if venue and _to_text(detail.get("venue")) != venue:
            continue
        if distance_m:
            previous_distance = _to_int(detail.get("distance_m"))
            if previous_distance is None or abs(previous_distance - distance_m) > 100:
                continue
        if going and _going_bucket(detail.get("going")) != _going_bucket(going):
            continue
        return True
    return False


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _going_bucket(value: Any) -> str:
    text = re.sub(r"\s+", "", _to_text(value))
    if not text:
        return ""
    if any(token in text for token in ("不良", "不", "稍重", "稍", "やや重", "重")):
        return "soft"
    if "良" in text:
        return "firm"
    return text


def _to_float(value: Any) -> float | None:
    text = _to_text(value).replace(",", "")
    if not text or text in {"-", "---"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _to_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    text = _to_text(value).replace(",", "")
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def _signed_int(value: Any) -> int | None:
    text = _to_text(value).replace(",", "")
    match = re.search(r"[+-]?\d+", text)
    return int(match.group(0)) if match else None


def _finish_int(value: Any) -> int | None:
    return _to_int(value)


def _horse_weight(horse: dict[str, Any]) -> int | None:
    return _to_int(horse.get("body_weight")) or _to_int(_first_detail(horse).get("body_weight"))


def _normalize_surface(value: Any) -> str:
    text = _to_text(value)
    if "芝" in text:
        return "芝"
    if "ダート" in text or text == "ダ" or "ダ" in text:
        return "ダ"
    return text


def _parse_run_date(value: Any) -> date | None:
    text = _to_text(value)
    match = re.search(r"(\d{2,4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if not match:
        return None
    year = int(match.group(1))
    if year < 100:
        year += 2000 if year < 70 else 1900
    try:
        return date(year, int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _corner_style(corner_text: str, field_size: str = "") -> str:
    values = [int(x) for x in re.findall(r"\d{1,2}", corner_text)]
    if not values:
        return ""
    pos_4 = values[-1]
    size = _to_int(field_size) or 0
    if pos_4 <= 1:
        return "逃げ"
    if size > 0:
        ratio = pos_4 / size
        if ratio <= 0.30:
            return "先行"
        if ratio <= 0.65:
            return "差し"
        return "追込"
    if pos_4 <= 3:
        return "先行"
    if pos_4 <= 7:
        return "差し"
    return "追込"


def _is_pin_par(details: list[dict[str, Any]]) -> bool:
    finishes = [_finish_int(detail.get("finish")) for detail in details[:3]]
    finishes = [finish for finish in finishes if finish is not None]
    return len(finishes) >= 3 and any(finish == 1 for finish in finishes) and all(finish == 1 or finish >= 7 for finish in finishes)


def _is_high_handicap_weight(horse: dict[str, Any], ctx: "ShoshoRaceContext") -> bool:
    weight = _to_float(horse.get("weight"))
    if weight is None:
        return False
    top = ctx.top_handicap_weight or 0.0
    if top > 0:
        # レース内の最上位斤量帯（トップから1.0kg以内）かつ56kg以上のみ減点。
        return weight >= top - 1.0 and weight >= 56.0
    return weight >= 57.0


def _has_steep_slope_success(details: list[dict[str, Any]]) -> bool:
    for detail in details:
        if _to_text(detail.get("venue")) in STEEP_SLOPE_VENUES:
            finish = _finish_int(detail.get("finish"))
            if finish is not None and finish <= 3:
                return True
    return False


def _has_handedness_concern(details: list[dict[str, Any]], current_handedness: str) -> bool:
    known = [HANDEDNESS.get(_to_text(detail.get("venue"))) for detail in details if HANDEDNESS.get(_to_text(detail.get("venue")))]
    if not known:
        # 過去走の回り情報が無い馬は減点しない（データ不足を不安扱いしない）。
        return False
    current_count = sum(1 for value in known if value == current_handedness)
    return current_count == 0 or (len(known) >= 3 and current_count == 1)
