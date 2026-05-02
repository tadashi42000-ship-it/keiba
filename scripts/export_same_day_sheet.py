from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.same_day_service import (  # noqa: E402
    build_bet_plan_snapshot,
    get_course_stats_snapshot,
    get_entry_snapshot,
    get_same_day_races,
)


def _safe_name(value: str) -> str:
    keep = []
    for char in value:
        if char.isalnum() or char in {"-", "_"}:
            keep.append(char)
        else:
            keep.append("_")
    return "".join(keep).strip("_") or "same_day"


def _text(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _odds(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.1f}"
    return "未公開"


def _race_title(race: dict[str, Any]) -> str:
    return (
        f"{_text(race.get('race_number'))} {_text(race.get('race_name'))} "
        f"({_text(race.get('surface'), '')}{_text(race.get('distance'), '')})"
    ).strip()


def _format_recent_runs(horse: dict[str, Any]) -> str:
    runs = horse.get("recent_runs") or []
    last3fs = horse.get("last3fs") or []
    parts: list[str] = []
    for idx, run in enumerate(runs[:3]):
        label = "前走" if idx == 0 else f"{idx + 1}走前"
        run_text = _text(run)
        last3f = _text(last3fs[idx] if idx < len(last3fs) else "", "")
        if last3f:
            run_text = f"{run_text} / 上り{last3f}"
        parts.append(f"{label}: {run_text}")
    return "<br>".join(parts) if parts else "-"


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        escaped = [cell.replace("\n", "<br>").replace("|", "／") for cell in row]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines)


def _race_markdown(snapshot: dict[str, Any]) -> str:
    race = snapshot["race"]
    entry = snapshot["entry"]
    stats = snapshot["course_stats"]
    bet_plan = snapshot["bet_plan"]
    horses = entry.get("horses") or []
    ranking = bet_plan.get("ranking") or []
    tickets = bet_plan.get("tickets") or []
    warnings = list(dict.fromkeys((entry.get("warnings") or []) + (bet_plan.get("warnings") or [])))

    lines = [
        f"## {_race_title(race)}",
        "",
        f"- race_id: `{_text(race.get('race_id'))}`",
        f"- 発走: {_text(entry.get('start_time'))}",
        f"- 脚質分布: {_text(entry.get('style_distribution_label'))}",
        f"- 天候/馬場: {_text(entry.get('weather'))} / {_text(entry.get('track_conditions'))}",
    ]
    if warnings:
        lines.append(f"- 注意: {' / '.join(warnings)}")
    lines.append("")

    if ranking:
        rank_rows = []
        for idx, item in enumerate(ranking[:6], start=1):
            rank_rows.append([
                str(idx),
                _text(item.get("umaban")),
                _text(item.get("horse_name")),
                _text(item.get("style")),
                _odds(item.get("odds")),
                f"{float(item.get('score') or 0):.3f}",
                _text(item.get("reason")),
            ])
        lines.extend([
            "### 候補馬ランキング",
            "",
            _markdown_table(["順", "馬番", "馬名", "脚質", "単勝", "score", "理由"], rank_rows),
            "",
        ])

    if tickets:
        ticket_rows = [
            [
                _text(ticket.get("type")),
                _text(ticket.get("selection")),
                _text(", ".join(ticket.get("horse_names") or [])),
                f"{int(ticket.get('amount_yen') or 0)}円",
                _text(ticket.get("reason")),
            ]
            for ticket in tickets
        ]
        lines.extend([
            "### 買い目メモ",
            "",
            _markdown_table(["券種", "印", "馬名", "金額", "理由"], ticket_rows),
            "",
        ])

    horse_rows = []
    for horse in horses:
        body = _text(horse.get("body_weight"), "未発表")
        if horse.get("body_delta"):
            body = f"{body} ({horse.get('body_delta')})"
        horse_rows.append([
            f"{_text(horse.get('waku'))}-{_text(horse.get('umaban'))}",
            _text(horse.get("horse_name")),
            _text(horse.get("jockey")),
            _text(horse.get("weight")),
            body,
            _text(horse.get("style")),
            _odds(horse.get("odds")),
            _format_recent_runs(horse),
        ])
    lines.extend([
        "### 出馬表メモ",
        "",
        _markdown_table(["枠-番", "馬名", "騎手", "斤量", "馬体重", "脚質", "単勝", "近3走"], horse_rows),
        "",
    ])

    frame_markdown = stats.get("frame_markdown")
    if frame_markdown:
        lines.extend([
            "### 枠別割合",
            "",
            str(frame_markdown),
            "",
        ])

    return "\n".join(lines)


def build_snapshot(target_date: date, venue: str) -> dict[str, Any]:
    races_response = get_same_day_races(target_date, venue)
    snapshots: list[dict[str, Any]] = []
    for race in races_response.get("races", []):
        race_id = race.get("race_id")
        if not race_id:
            snapshots.append({"race": race, "error": "race_id未解決"})
            continue
        entry = get_entry_snapshot(str(race_id))
        course_stats = get_course_stats_snapshot(
            race_id=str(race_id),
            venue=str(race.get("venue") or venue),
            distance=str(race.get("distance") or ""),
            surface=str(race.get("surface") or ""),
        )
        bet_plan = build_bet_plan_snapshot(str(race_id))
        snapshots.append(
            {
                "race": race,
                "entry": entry,
                "course_stats": course_stats,
                "bet_plan": bet_plan,
            }
        )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date": target_date.isoformat(),
        "venue": venue,
        "race_count": len(races_response.get("races", [])),
        "races": snapshots,
    }


def write_outputs(snapshot: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(f"{snapshot['date']}_{snapshot['venue']}_same_day_sheet")
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"

    json_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        f"# {snapshot['date']} {snapshot['venue']} 全レース記録シート",
        "",
        f"- 生成: {snapshot['generated_at']}",
        f"- レース数: {snapshot['race_count']}",
        "- メモ: オッズ・馬体重は当日公開後に更新してください。",
        "",
    ]
    for race_snapshot in snapshot.get("races", []):
        if race_snapshot.get("error"):
            lines.extend([
                f"## {_race_title(race_snapshot.get('race') or {})}",
                "",
                f"- 警告: {race_snapshot['error']}",
                "",
            ])
        else:
            lines.append(_race_markdown(race_snapshot))
            lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Export same-day race sheet for on-site use.")
    parser.add_argument("--date", required=True, help="Target date, e.g. 2026-04-26")
    parser.add_argument("--venue", required=True, help="Venue name, e.g. 東京")
    parser.add_argument("--out-dir", default=str(ROOT_DIR / "data" / "same_day_sheets"))
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    snapshot = build_snapshot(target_date, args.venue)
    json_path, md_path = write_outputs(snapshot, Path(args.out_dir))
    print(f"race_count={snapshot['race_count']}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
