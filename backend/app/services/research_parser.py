from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.clients import ExternalApiError, GeminiTextClient, TextAnalysisClient
from app.core.config import settings
from app.schemas.races import ResearchEntryHorse, ResearchParsed


_CIRCLED_DIGITS = {
    "①": "1",
    "②": "2",
    "③": "3",
    "④": "4",
    "⑤": "5",
    "⑥": "6",
    "⑦": "7",
    "⑧": "8",
    "⑨": "9",
    "⑩": "10",
    "⑪": "11",
    "⑫": "12",
    "⑬": "13",
    "⑭": "14",
    "⑮": "15",
    "⑯": "16",
    "⑰": "17",
    "⑱": "18",
}

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_VALID_MARKS = {"◎", "〇", "○", "▲", "△", "☆", "注", "消"}


def parse_research_report(
    raw_text: str,
    entry_horses: list[ResearchEntryHorse] | list[dict[str, Any]] | None,
    *,
    client: TextAnalysisClient | None = None,
) -> ResearchParsed:
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("raw_text is empty")

    horses = _normalize_entry_horses(entry_horses or [])
    text_client = client or GeminiTextClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        base_url=settings.gemini_base_url,
        timeout_sec=settings.external_api_timeout_sec,
    )

    system_prompt = _build_system_prompt()
    prompt = _build_prompt(raw_text=text, entry_horses=horses)
    last_error = ""
    for attempt in range(2):
        try:
            response_text = text_client.generate_text(
                prompt=prompt,
                system_prompt=system_prompt if attempt == 0 else f"{system_prompt}\n前回の出力が JSON として無効でした。必ず JSON のみで返してください。",
                max_output_tokens=8192,
            )
        except ExternalApiError:
            raise
        try:
            payload = json.loads(_extract_json_text(response_text))
            return _normalize_parsed_payload(payload, horses)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            last_error = str(exc)
    raise ValueError(f"Research report parse failed: {last_error}")


def normalize_umaban(value: object) -> str:
    text = str(value or "").strip()
    for source, target in _CIRCLED_DIGITS.items():
        text = text.replace(source, target)
    text = text.translate(_FULLWIDTH_DIGITS)
    match = re.search(r"\d+", text)
    if not match:
        return ""
    number = str(int(match.group(0)))
    return number if number != "0" else ""


def _normalize_entry_horses(items: list[ResearchEntryHorse] | list[dict[str, Any]]) -> list[dict[str, str]]:
    horses: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, ResearchEntryHorse):
            umaban = item.umaban
            horse_name = item.horse_name
        elif isinstance(item, dict):
            umaban = item.get("umaban", "")
            horse_name = item.get("horse_name", "")
        else:
            continue
        normalized = normalize_umaban(umaban)
        name = str(horse_name or "").strip()
        if normalized or name:
            horses.append({"umaban": normalized, "horse_name": name})
    return horses


def _build_system_prompt() -> str:
    assumed_prompt = (
        "\nAssumed-value extraction:\n"
        "- For each marked horse, extract assumed_odds and assumed_ev when the report states them.\n"
        "- Extract assumed_pace_label, assumed_frame_bias, and assumed_style_bias for the whole report when stated.\n"
        "- Use numbers for assumed_odds/assumed_ev, and use null or empty strings when absent.\n"
        'Extended JSON sample: {"marks":[{"umaban":"6","horse_name":"...","mark":"◎","comment":"...",'
        '"assumed_odds":5.1,"assumed_ev":1.2}],"assumed_pace_label":"","assumed_frame_bias":"",'
        '"assumed_style_bias":""}\n'
    )
    return (
        "あなたは競馬のレース予想レポートを構造化する解析器です。\n"
        "入力は人間が書いた自然文 + 表形式の予想レポートです。\n"
        "以下の JSON スキーマだけを返してください。説明文・Markdown・追加コメントは禁止です。\n"
        "馬番は entry_horses の umaban とマッチしてください。表記揺れ（①〜⑱、丸数字、半角全角）は半角数字へ正規化してください。\n"
        "パース不能な部分は無視してください。配列が空でも構いません。\n"
        "null は使用禁止です。空欄は必ず空文字 \"\"、空配列 []、または formation のみ null を返してください。\n"
        "formation は必ず array of array of string です。例: [[\"6\"],[\"4\",\"7\"]]。文字列で説明を書かないでください。\n"
        "reason/comment/text は短く要約し、長文を避けてください。\n"
        '返却形式: {"marks":[{"umaban":"6","horse_name":"...","mark":"◎","comment":"..."}],'
        '"horse_notes":[{"umaban":"6","horse_name":"...","label":"好材料","text":"..."}],'
        '"pace_label":"","course_note":"","tickets":[{"bet_type":"単勝","horses":["4"],"formation":null,"amount_yen":1000,"reason":"..."}],'
        '"scratched":[{"umaban":"13","horse_name":"...","reason":"..."}],"max_payout_scenario":""}'
    ) + assumed_prompt


def _build_prompt(*, raw_text: str, entry_horses: list[dict[str, str]]) -> str:
    return "\n".join(
        [
            "entry_horses:",
            json.dumps(entry_horses, ensure_ascii=False),
            "",
            "raw_report:",
            raw_text,
        ]
    )


def _extract_json_text(text: str) -> str:
    candidate = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        return candidate[start : end + 1].strip()
    return candidate


def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.translate(str.maketrans("０１２３４５６７８９．，", "0123456789.."))
    text = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _normalize_parsed_payload(payload: Any, entry_horses: list[dict[str, str]]) -> ResearchParsed:
    if not isinstance(payload, dict):
        raise ValueError("Gemini response JSON root must be an object")
    allowed_numbers = {horse["umaban"] for horse in entry_horses if horse.get("umaban")}
    name_by_number = {horse["umaban"]: horse.get("horse_name", "") for horse in entry_horses if horse.get("umaban")}

    normalized = dict(payload)
    for key in ("marks", "horse_notes", "scratched"):
        rows = normalized.get(key)
        if not isinstance(rows, list):
            normalized[key] = []
            continue
        clean_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            next_row = dict(row)
            umaban = normalize_umaban(next_row.get("umaban"))
            if not umaban:
                umaban = _match_horse_name(str(next_row.get("horse_name") or ""), entry_horses)
            if allowed_numbers and umaban not in allowed_numbers:
                continue
            if not umaban:
                continue
            next_row["umaban"] = umaban
            if not str(next_row.get("horse_name") or "").strip() and umaban in name_by_number:
                next_row["horse_name"] = name_by_number[umaban]
            if key == "marks" and next_row.get("mark") not in _VALID_MARKS:
                continue
            if key == "marks":
                next_row["assumed_odds"] = _to_optional_float(next_row.get("assumed_odds"))
                next_row["assumed_ev"] = _to_optional_float(next_row.get("assumed_ev"))
            clean_rows.append(next_row)
        normalized[key] = clean_rows

    for text_key in ("assumed_pace_label", "assumed_frame_bias", "assumed_style_bias"):
        normalized[text_key] = "" if normalized.get(text_key) is None else str(normalized.get(text_key, ""))

    tickets = normalized.get("tickets")
    if isinstance(tickets, list):
        normalized_tickets = []
        for ticket in tickets:
            if not isinstance(ticket, dict):
                continue
            next_ticket = dict(ticket)
            for text_key in ("bet_type", "reason"):
                if next_ticket.get(text_key) is None:
                    next_ticket[text_key] = ""
                else:
                    next_ticket[text_key] = str(next_ticket.get(text_key, ""))
            amount = next_ticket.get("amount_yen")
            if amount is None or isinstance(amount, str) and not amount.strip().isdigit():
                next_ticket["amount_yen"] = 0
            horses = next_ticket.get("horses")
            if isinstance(horses, list):
                next_ticket["horses"] = [normalize_umaban(value) or str(value or "").strip() for value in horses if str(value or "").strip()]
            elif horses is None:
                next_ticket["horses"] = []
            else:
                next_ticket["horses"] = [normalize_umaban(horses) or str(horses).strip()] if str(horses).strip() else []
            formation = next_ticket.get("formation")
            if isinstance(formation, list):
                next_ticket["formation"] = [
                    [normalize_umaban(value) or str(value or "").strip() for value in row if str(value or "").strip()]
                    for row in formation
                    if isinstance(row, list)
                ]
            else:
                next_ticket["formation"] = None
            normalized_tickets.append(next_ticket)
        normalized["tickets"] = normalized_tickets
    else:
        normalized["tickets"] = []

    return ResearchParsed(**normalized)


def _match_horse_name(horse_name: str, entry_horses: list[dict[str, str]]) -> str:
    target = horse_name.strip()
    if not target:
        return ""
    for horse in entry_horses:
        name = horse.get("horse_name", "")
        if target == name or (target and name and (target in name or name in target)):
            return horse.get("umaban", "")
    return ""
