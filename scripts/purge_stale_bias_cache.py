from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT_DIR / "data" / "track_bias_results_cache.json"


def _race_date(entry: dict[str, Any]) -> date | None:
    race_meta = entry.get("race_meta")
    if not isinstance(race_meta, dict):
        return None
    try:
        return date.fromisoformat(str(race_meta.get("date") or ""))
    except ValueError:
        return None


def main() -> int:
    if not CACHE_PATH.exists():
        print("data/track_bias_results_cache.json not found. deleted=0")
        return 0

    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"failed to read cache: {type(exc).__name__}")
        return 1

    races = payload.get("races")
    if not isinstance(races, dict):
        print("cache has no races object. deleted=0")
        return 0

    today = date.today()
    delete_keys: list[str] = []
    for race_id, entry in races.items():
        if not isinstance(entry, dict):
            continue
        rows = entry.get("rows")
        race_date = _race_date(entry)
        if race_date and race_date < today and rows == [] and not bool(entry.get("has_result")):
            delete_keys.append(str(race_id))

    for race_id in delete_keys:
        races.pop(race_id, None)

    if delete_keys:
        CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"deleted={len(delete_keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
