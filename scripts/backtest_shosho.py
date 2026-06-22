from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import time

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "legacy" / "streamlit_app"))
sys.path.insert(0, str(ROOT / "backend"))

from app.services import same_day_service as sds  # noqa: E402
from same_day_sources import build_requests_session as _build_session  # type: ignore  # noqa: E402

_PAYOUT_SESSION: requests.Session | None = None
_PAYOUT_FETCH_DELAY = 12  # seconds between payout requests to avoid IP blocks


def _payout_session() -> requests.Session:
    global _PAYOUT_SESSION
    if _PAYOUT_SESSION is None:
        _PAYOUT_SESSION = _build_session()
    return _PAYOUT_SESSION

CACHE_PATTERNS = (
    ROOT / "data" / "same_day_sheets" / "*_same_day_sheet.json",
    ROOT / "tmp" / "same_day_*.json",
)
PAYOUT_CACHE = ROOT / "data" / "shosho_backtest_payouts.json"


def _to_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(_to_text(value).replace(",", ""))
    except ValueError:
        return None
    return parsed


def _to_int(value: Any) -> int | None:
    match = re.search(r"\d+", _to_text(value).replace(",", ""))
    return int(match.group(0)) if match else None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _load_payout_cache() -> dict[str, Any]:
    payload = _load_json(PAYOUT_CACHE)
    if not payload:
        return {"version": 1, "races": {}}
    payload.setdefault("version", 1)
    payload.setdefault("races", {})
    return payload


def _save_payout_cache(payload: dict[str, Any]) -> None:
    PAYOUT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PAYOUT_CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _race_meta(snapshot: dict[str, Any], race: dict[str, Any]) -> dict[str, Any]:
    distance = _to_int(race.get("distance"))
    return {
        "date": _to_text(race.get("date_iso")) or _to_text(snapshot.get("date")),
        "venue": _to_text(race.get("venue")) or _to_text(snapshot.get("venue")),
        "surface": _to_text(race.get("surface")),
        "distance_m": distance or 0,
        "race_number": _to_text(race.get("race_number")),
    }


def _load_race_items() -> list[tuple[Path, dict[str, Any], dict[str, Any]]]:
    found: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    seen: set[str] = set()
    for pattern in CACHE_PATTERNS:
        for path in sorted(pattern.parent.glob(pattern.name)):
            snapshot = _load_json(path)
            if not snapshot:
                continue
            for item in snapshot.get("races") or []:
                if not isinstance(item, dict) or not isinstance(item.get("entry"), dict):
                    continue
                race = item.get("race") if isinstance(item.get("race"), dict) else {}
                race_id = _to_text(race.get("race_id")) or _to_text(item["entry"].get("race_id"))
                if not race_id or race_id in seen:
                    continue
                if not item["entry"].get("horses"):
                    continue
                seen.add(race_id)
                found.append((path, snapshot, item))
    return found


# en.netkeiba.com CSS class → 券種マップ
_EN_TYPE_MAP: dict[str, str] = {
    "Tansho": "単勝",
    "Fukusho": "複勝",
    "Wakuren": "枠連",
    "Umaren": "馬連",
    "Wide": "ワイド",
    "Umatan": "馬単",
    "Fuku3": "3連複",
    "Tan3": "3連単",
}
# 順序維持が必要な券種（馬単・3連単）
_ORDERED_TYPES: frozenset[str] = frozenset({"馬単", "3連単"})

_last_payout_fetch: float = 0.0


def _normalize_combo(nums: list[str], *, ordered: bool) -> str:
    if ordered:
        return "-".join(str(int(n)) for n in nums)
    return "-".join(sorted((str(int(n)) for n in nums), key=lambda x: int(x)))


def _parse_en_netkeiba_payouts(html: str) -> dict[str, list[dict[str, Any]]]:
    """Parse .Result_Pay_Back table from en.netkeiba.com race result page.

    Uses ul/span structure per combo so multi-leg payouts (e.g. Wide 3 combos)
    are never collapsed into a single selection string.
    """
    soup = BeautifulSoup(html, "html.parser")
    block = soup.select_one(".Result_Pay_Back")
    if not block:
        return {}

    payouts: dict[str, list[dict[str, Any]]] = {}
    for tr in block.select("tr"):
        classes = tr.get("class") or []
        bet_type = next((_EN_TYPE_MAP[c] for c in classes if c in _EN_TYPE_MAP), None)
        if not bet_type:
            continue

        result_td = tr.select_one("td.Result")
        payout_td = tr.select_one("td.Payout")
        if not result_td or not payout_td:
            continue

        ordered = bet_type in _ORDERED_TYPES

        # Each <ul> is one combination (e.g. Wide has 3 uls per row)
        groups: list[str] = []
        uls = result_td.select("ul")
        if uls:
            for ul in uls:
                nums = [s.get_text(strip=True) for s in ul.select("span") if s.get_text(strip=True).isdigit()]
                if nums:
                    groups.append(_normalize_combo(nums, ordered=ordered))
        else:
            # Fallback: individual spans (単勝/複勝)
            nums = [s.get_text(strip=True) for s in result_td.select("span") if s.get_text(strip=True).isdigit()]
            for n in nums:
                groups.append(_normalize_combo([n], ordered=ordered))

        # en.netkeiba uses ￥ prefix (not 円 suffix); extract all ¥/￥-prefixed values
        payout_text = payout_td.get_text("\n", strip=True)
        yen_vals = [int(x.replace(",", "")) for x in re.findall(r"[¥￥]([\d,]+)", payout_text)]
        # Fallback: 円-suffix format (other sites)
        if not yen_vals:
            yen_vals = [int(x.replace(",", "")) for x in re.findall(r"([\d,]+)円", payout_text)]
        # Final fallback: any 3+ digit number
        if not yen_vals:
            yen_vals = [int(x.replace(",", "")) for x in re.findall(r"\b([\d,]{3,})\b", payout_text)]

        for sel, yen in zip(groups, yen_vals):
            payouts.setdefault(bet_type, []).append({"selection": sel, "payout_yen": yen})

    return payouts


def _fetch_payouts(race_id: str, refresh: bool = False) -> dict[str, Any]:
    global _last_payout_fetch
    cache = _load_payout_cache()
    races = cache.setdefault("races", {})
    # Return cache when already successfully fetched
    if not refresh and isinstance(races.get(race_id), dict):
        entry = races[race_id]
        if entry.get("available") or _has_usable_composite_payouts(entry):
            return entry
        # Previously failed: protect IP, skip unless refresh requested
        if entry.get("error") or (entry.get("fetched_at") and not entry.get("payouts")):
            return entry

    # Polite delay between fetches
    since = time.time() - _last_payout_fetch
    if since < _PAYOUT_FETCH_DELAY:
        time.sleep(_PAYOUT_FETCH_DELAY - since)

    url = f"https://en.netkeiba.com/race/race_result.html?race_id={race_id}"
    payouts: dict[str, list[dict[str, Any]]] = {}
    try:
        sess = _payout_session()
        response = sess.get(url, timeout=15)
        _last_payout_fetch = time.time()
        if response.status_code != 200 or not response.content:
            raise ValueError(f"HTTP {response.status_code}")
        payouts = _parse_en_netkeiba_payouts(response.text)
        candidate = {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "url": url,
            "payouts": payouts,
            "available": bool(payouts) and _has_usable_composite_payouts({"payouts": payouts}),
        }
        if payouts and not candidate["available"]:
            candidate["note"] = "払戻テーブル取得済みだが複合買い目照合に失敗"
        races[race_id] = candidate
    except Exception as exc:
        _last_payout_fetch = time.time()
        races[race_id] = {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "url": url,
            "payouts": {},
            "available": False,
            "error": str(exc),
        }
    _save_payout_cache(cache)
    return races[race_id]


def _has_usable_composite_payouts(payload: dict[str, Any]) -> bool:
    payouts = payload.get("payouts") if isinstance(payload.get("payouts"), dict) else {}
    for ticket_type, min_legs in (("ワイド", 2), ("馬連", 2), ("3連複", 3)):
        for row in payouts.get(ticket_type, []) or []:
            if len(_to_text(row.get("selection")).split("-")) >= min_legs:
                return True
    return False


def _normalize_selection(selection: str) -> str:
    values = re.findall(r"\d{1,2}", _to_text(selection))
    return "-".join(sorted((str(int(value)) for value in values), key=lambda value: int(value)))


def _point_count(ticket: dict[str, Any]) -> int:
    selection = _to_text(ticket.get("selection"))
    if not selection or selection == "-":
        return 0
    if ticket.get("type") == "単勝":
        return 1
    if ticket.get("type") == "ワイド" and selection.count("-") == 1 and "," in selection.split("-", 1)[1]:
        return len([part for part in selection.split("-", 1)[1].split(",") if part])
    return len([part for part in selection.split(",") if part])


def _ticket_points(ticket: dict[str, Any]) -> list[str]:
    selection = _to_text(ticket.get("selection"))
    if not selection or selection == "-":
        return []
    if ticket.get("type") == "単勝":
        return [_normalize_selection(selection)]
    if ticket.get("type") == "ワイド" and selection.count("-") == 1 and "," in selection.split("-", 1)[1]:
        axis, partners = selection.split("-", 1)
        return [_normalize_selection(f"{axis}-{partner}") for partner in partners.split(",") if partner]
    return [_normalize_selection(part) for part in selection.split(",") if part]


def _finish_sets(rows: list[dict[str, Any]]) -> tuple[set[str], set[str], set[str]]:
    first = {_to_text(row.get("umaban")) for row in rows if _to_int(row.get("finish_pos")) == 1}
    top2 = {_to_text(row.get("umaban")) for row in rows if (_to_int(row.get("finish_pos")) or 99) <= 2}
    top3 = {_to_text(row.get("umaban")) for row in rows if (_to_int(row.get("finish_pos")) or 99) <= 3}
    return first, top2, top3


def _is_hit(ticket_type: str, point: str, first: set[str], top2: set[str], top3: set[str]) -> bool:
    legs = set(point.split("-"))
    if ticket_type == "単勝":
        return bool(legs & first)
    if ticket_type == "ワイド":
        return len(legs & top3) >= 2
    if ticket_type == "馬連":
        return legs == top2 and len(legs) == 2
    if ticket_type == "3連複":
        return legs == top3 and len(legs) == 3
    return False


def _evaluate(label: str, tickets: list[dict[str, Any]], rows: list[dict[str, Any]], payouts: dict[str, Any], odds_by_umaban: dict[str, float]) -> dict[str, Any]:
    first, top2, top3 = _finish_sets(rows)
    summary: dict[str, Any] = defaultdict(lambda: {"tickets": 0, "points": 0, "hits": 0, "stake": 0, "return": 0.0, "unpriced_hits": 0})
    payout_rows = payouts.get("payouts") if isinstance(payouts.get("payouts"), dict) else {}
    for ticket in tickets:
        ticket_type = _to_text(ticket.get("type"))
        if ticket_type == "見送り":
            continue
        amount = int(ticket.get("amount_yen") or 0)
        points = _ticket_points(ticket)
        if not points:
            continue
        bucket = summary[ticket_type]
        bucket["tickets"] += 1
        bucket["points"] += len(points)
        bucket["stake"] += amount * len(points)
        for point in points:
            if not _is_hit(ticket_type, point, first, top2, top3):
                continue
            bucket["hits"] += 1
            if ticket_type == "単勝":
                odd = odds_by_umaban.get(point)
                if odd:
                    bucket["return"] += amount * odd
            else:
                payout = next(
                    (row.get("payout_yen") for row in payout_rows.get(ticket_type, []) if row.get("selection") == point),
                    None,
                )
                if payout:
                    bucket["return"] += amount * float(payout) / 100.0
                else:
                    bucket["unpriced_hits"] += 1
    return {"label": label, "summary": summary}


def _print_summary(title: str, result: dict[str, Any]) -> None:
    print(f"\n## {title}")
    print("券種       tickets points hits hit_rate stake return roi unpriced")
    for ticket_type in ("単勝", "ワイド", "馬連", "3連複"):
        row = result["summary"].get(ticket_type, {})
        points = int(row.get("points") or 0)
        hits = int(row.get("hits") or 0)
        stake = float(row.get("stake") or 0)
        ret = float(row.get("return") or 0)
        hit_rate = hits / points * 100 if points else 0.0
        roi = ret / stake * 100 if stake else 0.0
        print(f"{ticket_type:<8} {int(row.get('tickets') or 0):>7} {points:>6} {hits:>4} {hit_rate:>7.1f}% {stake:>6.0f} {ret:>7.0f} {roi:>5.1f}% {int(row.get('unpriced_hits') or 0):>8}")


def _roi(row: dict[str, Any]) -> float:
    stake = float(row.get("stake") or 0)
    return (float(row.get("return") or 0) / stake * 100) if stake else 0.0


def _print_diff(baseline: dict[str, Any], current: dict[str, Any]) -> None:
    print("\n## current - baseline")
    print("券種       hit_rate_diff roi_diff stake_diff")
    for ticket_type in ("単勝", "ワイド", "馬連", "3連複"):
        base = baseline["summary"].get(ticket_type, {})
        cur = current["summary"].get(ticket_type, {})
        base_points = int(base.get("points") or 0)
        cur_points = int(cur.get("points") or 0)
        base_hit = (int(base.get("hits") or 0) / base_points * 100) if base_points else 0.0
        cur_hit = (int(cur.get("hits") or 0) / cur_points * 100) if cur_points else 0.0
        print(
            f"{ticket_type:<8} {cur_hit - base_hit:>12.1f}% {_roi(cur) - _roi(base):>8.1f}% "
            f"{float(cur.get('stake') or 0) - float(base.get('stake') or 0):>10.0f}"
        )


def _print_race_detail(
    num: int,
    meta: dict[str, Any],
    race: dict[str, Any],
    path: Path,
    current_tickets: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    payouts: dict[str, Any],
    odds_by_umaban: dict[str, float],
    plan: dict[str, Any],
) -> None:
    first, top2, top3 = _finish_sets(rows)
    rec = plan.get("recommendations") or {}
    shape = rec.get("race_shape") or {}

    trio_18 = any(t.get("strategy") == "3連複18点鉄板" for t in current_tickets)
    trio_note = " [18点鉄板]" if trio_18 else ""

    types = sorted({t.get("type") for t in current_tickets if t.get("type") != "見送り"})
    types_str = "/".join(types) or "見送り"
    label = shape.get("label", "?")

    print(f"\n{'='*60}")
    print(f"{num:02d}. {meta.get('date')} {meta.get('venue')} {meta.get('race_number')}R {race.get('race_name','')} [{label}]{trio_note}")
    print(f"    1着={sorted(first)} 2着以内={sorted(top2)} 3着以内={sorted(top3)}")

    payout_rows = payouts.get("payouts") if isinstance(payouts.get("payouts"), dict) else {}
    for t in current_tickets:
        ttype = _to_text(t.get("type"))
        if ttype == "見送り":
            continue
        points = _ticket_points(t)
        hits = [p for p in points if _is_hit(ttype, p, first, top2, top3)]
        sel_preview = _to_text(t.get("selection", ""))[:80]
        hit_note = ""
        if hits:
            payout_note = ""
            for p in hits:
                pay = next((r.get("payout_yen") for r in payout_rows.get(ttype, []) if r.get("selection") == p), None)
                payout_note += f" ¥{pay}" if pay else " (unpriced)"
            hit_note = f" → HIT {hits}{payout_note}"
        print(f"    {ttype}({len(points)}点) {sel_preview}...{hit_note}")

    hatsuran = shape.get("hatsuran_do", "?")
    axis_prob = shape.get("axis_place_prob", "?")
    aite = shape.get("aite_confidence", "?")
    pace = shape.get("pace_pattern", "?")
    print(f"    [metrics] 波乱度={hatsuran:.2f} 軸連対率={axis_prob:.2f} 相手信頼={aite} 展開={pace}")


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Shosho backtest")
    parser.add_argument("--date", default="", help="Filter by date (YYYY-MM-DD)")
    parser.add_argument("--venue", default="", help="Filter by venue (e.g. 東京)")
    parser.add_argument("--refresh-payouts", action="store_true", help="Re-fetch payouts even if cached (use after IP block clears)")
    args = parser.parse_args(argv)
    filter_date = args.date.strip()
    refresh_payouts = args.refresh_payouts
    filter_venue = args.venue.strip()

    items = _load_race_items()
    if not items:
        print("No same-day cache races found.")
        return 1

    if filter_date or filter_venue:
        def _matches(snapshot: dict, race: dict) -> bool:
            d = _to_text(race.get("date_iso")) or _to_text(snapshot.get("date"))
            v = _to_text(race.get("venue")) or _to_text(snapshot.get("venue"))
            if filter_date and d != filter_date:
                return False
            if filter_venue and v != filter_venue:
                return False
            return True
        items = [(p, s, it) for p, s, it in items if _matches(s, it.get("race") or {})]
        print(f"フィルタ: date={filter_date or 'all'} venue={filter_venue or 'all'} → {len(items)}レース")

    empty_summary = lambda: {"tickets": 0, "points": 0, "hits": 0, "stake": 0, "return": 0.0, "unpriced_hits": 0}
    aggregate_current = {"label": "current", "summary": defaultdict(empty_summary)}
    aggregate_baseline = {"label": "baseline", "summary": defaultdict(empty_summary)}
    used = 0
    payout_available = 0

    for path, snapshot, item in items:
        race = item.get("race") if isinstance(item.get("race"), dict) else {}
        entry = item.get("entry")
        if not isinstance(entry, dict):
            continue
        race_id = _to_text(race.get("race_id")) or _to_text(entry.get("race_id"))
        meta = _race_meta(snapshot, race)
        try:
            rows = sds.get_race_result_rows(race_id, meta, refresh=False)
        except Exception:
            rows = []
        if not rows:
            print(f"  → {meta.get('date')} {meta.get('venue')} {meta.get('race_number')} 結果取得不可 (skip)")
            continue
        current = sds._build_bet_plan_from_entry(
            entry,
            budget_yen=int((item.get("bet_plan") or {}).get("budget_yen") or 3000),
            course_stats=item.get("course_stats") if isinstance(item.get("course_stats"), dict) else None,
            track_bias=item.get("track_bias") if isinstance(item.get("track_bias"), dict) else None,
            race=race,
        )
        baseline_plan = item.get("bet_plan") if isinstance(item.get("bet_plan"), dict) else {}
        baseline_tickets = ((baseline_plan.get("recommendations") or {}).get("tickets") or baseline_plan.get("tickets") or [])
        current_tickets = ((current.get("recommendations") or {}).get("tickets") or [])
        odds_by_umaban = {
            _to_text(horse.get("umaban")): float(odd)
            for horse in entry.get("horses", [])
            if (odd := _to_float(horse.get("odds"))) is not None and _to_text(horse.get("umaban"))
        }
        payouts = _fetch_payouts(race_id, refresh=refresh_payouts)
        if payouts.get("available"):
            payout_available += 1
        used += 1
        _print_race_detail(used, meta, race, path, current_tickets, rows, payouts, odds_by_umaban, current)

        for result in (
            _evaluate("baseline", baseline_tickets, rows, payouts, odds_by_umaban),
            _evaluate("current", current_tickets, rows, payouts, odds_by_umaban),
        ):
            target = aggregate_baseline if result["label"] == "baseline" else aggregate_current
            for ticket_type, row in result["summary"].items():
                bucket = target["summary"][ticket_type]
                for key in ("tickets", "points", "hits", "stake", "return", "unpriced_hits"):
                    bucket[key] += row.get(key, 0)

    print(f"\n{'='*60}")
    print("キャッシュオッズを近似に使用・少数サンプルの方向性確認であり統計的断定ではありません。")
    print(f"対象レース: {used} / 払戻取得: {payout_available}")
    _print_summary("baseline (cached old plan)", aggregate_baseline)
    _print_summary("current (recomputed A/C/F)", aggregate_current)
    _print_diff(aggregate_baseline, aggregate_current)
    if payout_available < used:
        print("\n注: ワイド/馬連/3連複の回収率は公式払戻を買い目単位で照合できたレースのみ反映。不足分は的中率中心に確認してください。")
    return 0 if used else 1


if __name__ == "__main__":
    raise SystemExit(main())
