"""Lightweight same-day cache updater for field PWA use.

Examples:
  python scripts/run_same_day_updater.py --date 2026-06-14 --venue tokyo --once
  python scripts/run_same_day_updater.py --date 2026-06-14 --venue tokyo --loop

The updater is intended to run on the home PC. Phones in the field should keep
reading the cached same-day sheet quickly while this process refreshes volatile
odds/body-weight data in the background.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

JST = timezone(timedelta(hours=9))
VENUE_ALIASES = {
    "tokyo": "\u6771\u4eac",
    "kyoto": "\u4eac\u90fd",
    "hanshin": "\u962a\u795e",
    "nakayama": "\u4e2d\u5c71",
    "fukushima": "\u798f\u5cf6",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh same-day PWA cache from a home PC.")
    parser.add_argument("--date", required=True, help="Target date, e.g. 2026-06-14")
    parser.add_argument("--venue", required=True, help="Venue, e.g. 東京")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="FastAPI base URL")
    parser.add_argument("--budget-yen", type=int, default=3000)
    parser.add_argument("--lookahead-min", type=int, default=30, help="Refresh races starting within this window")
    parser.add_argument("--post-start-min", type=int, default=1, help="Keep refreshing briefly after start")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--loop", action="store_true", help="Keep running until Ctrl+C")
    args = parser.parse_args()
    args.venue = VENUE_ALIASES.get(args.venue.strip().lower(), args.venue)

    if not args.once and not args.loop:
        args.once = True

    while True:
        try:
            sleep_seconds = run_cycle(args)
        except KeyboardInterrupt:
            print("stopped")
            return 0
        except Exception as exc:
            print(f"[WARN] cycle failed: {type(exc).__name__}: {exc}", flush=True)
            sleep_seconds = 60

        if args.once:
            return 0
        time.sleep(max(5, sleep_seconds))


def run_cycle(args: argparse.Namespace) -> int:
    sheet = get_json(
        args.base_url,
        "/api/v1/races/same-day-sheet",
        {"date": args.date, "venue": args.venue, "budget_yen": str(args.budget_yen)},
    )
    target = choose_target_race(sheet, args.date, args.lookahead_min, args.post_start_min)
    generated_at = sheet.get("generated_at", "-")
    if not target:
        print(f"[INFO] {args.date} {args.venue}: no race in refresh window / cache generated_at={generated_at}", flush=True)
        return 60

    race = target["race"]
    entry = target.get("entry") or {}
    remaining = target["remaining_sec"]
    phase_sleep = interval_for_remaining(remaining)
    race_id = race.get("race_id") or ""
    race_number = race.get("race_number") or ""
    race_name = race.get("race_name") or ""

    started = time.monotonic()
    refreshed = post_json(
        args.base_url,
        "/api/v1/races/same-day-sheet/refresh-volatile",
        {
            "date": args.date,
            "venue": args.venue,
            "budget_yen": str(args.budget_yen),
            "race_id": str(race_id),
            "race_number": str(race_number),
        },
    )
    elapsed = time.monotonic() - started
    refreshed_item = find_race(refreshed, str(race_id), str(race_number))
    refreshed_entry = (refreshed_item or {}).get("entry") or {}
    odds_count = sum(1 for horse in refreshed_entry.get("horses") or [] if horse.get("odds") is not None)
    body_count = sum(1 for horse in refreshed_entry.get("horses") or [] if horse.get("body_weight"))
    print(
        "[OK] "
        f"{race_number} {race_name} race_id={race_id} "
        f"remaining={int(remaining)}s odds={odds_count} body={body_count} "
        f"elapsed={elapsed:.2f}s generated_at={refreshed.get('generated_at', '-')}",
        flush=True,
    )
    if entry.get("odds_updated_at") or entry.get("body_updated_at"):
        print(
            f"[INFO] previous cache odds={entry.get('odds_updated_at') or '-'} body={entry.get('body_updated_at') or '-'}",
            flush=True,
        )
    return phase_sleep


def choose_target_race(sheet: dict[str, Any], date_iso: str, lookahead_min: int, post_start_min: int) -> dict[str, Any] | None:
    now = datetime.now(JST)
    candidates: list[dict[str, Any]] = []
    for item in sheet.get("races") or []:
        if not isinstance(item, dict):
            continue
        entry = item.get("entry") if isinstance(item.get("entry"), dict) else {}
        start_time = str(entry.get("start_time") or "")
        start_dt = parse_start_datetime(date_iso, start_time)
        if not start_dt:
            continue
        remaining = (start_dt - now).total_seconds()
        if remaining > lookahead_min * 60:
            continue
        if remaining < -post_start_min * 60:
            continue
        item = dict(item)
        item["remaining_sec"] = remaining
        candidates.append(item)
    candidates.sort(key=lambda item: abs(float(item["remaining_sec"])))
    return candidates[0] if candidates else None


def parse_start_datetime(date_iso: str, start_time: str) -> datetime | None:
    parts = start_time.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        year, month, day = (int(part) for part in date_iso.split("-"))
        return datetime(year, month, day, hour, minute, tzinfo=JST)
    except ValueError:
        return None


def interval_for_remaining(remaining_sec: float) -> int:
    if remaining_sec <= 60:
        return 15
    if remaining_sec <= 5 * 60:
        return 30
    if remaining_sec <= 30 * 60:
        return 60
    return 60


def find_race(sheet: dict[str, Any], race_id: str, race_number: str) -> dict[str, Any] | None:
    for item in sheet.get("races") or []:
        race = item.get("race") if isinstance(item, dict) else {}
        if race_id and str(race.get("race_id") or "") == race_id:
            return item
        if race_number and str(race.get("race_number") or "") == race_number:
            return item
    return None


def get_json(base_url: str, path: str, params: dict[str, str]) -> dict[str, Any]:
    url = build_url(base_url, path, params)
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(base_url: str, path: str, params: dict[str, str]) -> dict[str, Any]:
    url = build_url(base_url, path, params)
    request = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc


def build_url(base_url: str, path: str, params: dict[str, str]) -> str:
    query = urllib.parse.urlencode(params)
    return f"{base_url.rstrip('/')}{path}?{query}"


if __name__ == "__main__":
    sys.exit(main())
