from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import races as races_api
from app.clients import ExternalApiError
from app.main import app
from app.services import research_parser


client = TestClient(app)


class _DummyTextClient:
    def __init__(self, responses: list[str] | str) -> None:
        self.responses = responses if isinstance(responses, list) else [responses]
        self.calls: list[dict] = []

    @property
    def is_configured(self) -> bool:
        return True

    def generate_text(self, *, prompt: str, system_prompt: str | None = None, max_output_tokens: int | None = None) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "max_output_tokens": max_output_tokens,
            }
        )
        if len(self.calls) <= len(self.responses):
            return self.responses[len(self.calls) - 1]
        return self.responses[-1]


def test_parse_research_report_normalizes_circled_numbers_and_json_fence() -> None:
    text_client = _DummyTextClient(
        """```json
{"marks":[{"umaban":"⑥","horse_name":"テストホース","mark":"◎","comment":"軸"}],
"horse_notes":[{"umaban":"６","horse_name":"テストホース","label":"好材料","text":"追い切り良好"}],
"pace_label":"先行有利","course_note":"内枠注意",
"tickets":[{"bet_type":"単勝","horses":["⑥"],"amount_yen":1000,"reason":"本命"}],
"scratched":[{"umaban":"１３","horse_name":"消し馬","reason":"距離不安"}],
"max_payout_scenario":"相手荒れ"}
```"""
    )

    parsed = research_parser.parse_research_report(
        "①②⑥を中心にした長いレポートです。",
        [{"umaban": "6", "horse_name": "テストホース"}, {"umaban": "13", "horse_name": "消し馬"}],
        client=text_client,
    )

    assert parsed.marks[0].umaban == "6"
    assert parsed.horse_notes[0].umaban == "6"
    assert parsed.tickets[0].horses == ["6"]
    assert parsed.scratched[0].umaban == "13"
    assert parsed.pace_label == "先行有利"
    assert text_client.calls[0]["max_output_tokens"] == 8192


def test_parse_research_report_retries_once_for_broken_json() -> None:
    text_client = _DummyTextClient(
        [
            "{broken",
            '{"marks":[{"umaban":"1","horse_name":"A","mark":"○","comment":""}],"tickets":[]}',
        ]
    )

    parsed = research_parser.parse_research_report(
        "十分な長さのレポート本文です。",
        [{"umaban": "1", "horse_name": "A"}],
        client=text_client,
    )

    assert len(text_client.calls) == 2
    assert "前回の出力が JSON として無効" in text_client.calls[1]["system_prompt"]
    assert parsed.marks[0].umaban == "1"


def test_parse_research_report_tolerates_null_reason_and_string_formation() -> None:
    text_client = _DummyTextClient(
        '{"marks":[],"tickets":[{"bet_type":"3連複","horses":"⑥","formation":"1列目：⑥④／2列目：①⑤","amount_yen":null,"reason":null}]}'
    )

    parsed = research_parser.parse_research_report(
        "十分な長さのレポート本文です。",
        [{"umaban": "6", "horse_name": "A"}],
        client=text_client,
    )

    assert parsed.tickets[0].horses == ["6"]
    assert parsed.tickets[0].formation is None
    assert parsed.tickets[0].amount_yen == 0
    assert parsed.tickets[0].reason == ""


def test_parse_research_report_extracts_assumed_values() -> None:
    mark = next(iter(research_parser._VALID_MARKS))
    text_client = _DummyTextClient(
        json.dumps(
            {
                "marks": [{"umaban": "1", "horse_name": "A", "mark": mark, "comment": "axis", "assumed_odds": "5.1x", "assumed_ev": "1.25"}],
                "assumed_pace_label": "high",
                "assumed_frame_bias": "inner",
                "assumed_style_bias": "front",
            },
            ensure_ascii=False,
        )
    )

    parsed = research_parser.parse_research_report(
        "long enough research report text",
        [{"umaban": "1", "horse_name": "A"}],
        client=text_client,
    )

    assert parsed.marks[0].assumed_odds == 5.1
    assert parsed.marks[0].assumed_ev == 1.25
    assert parsed.assumed_pace_label == "high"
    assert parsed.assumed_frame_bias == "inner"
    assert parsed.assumed_style_bias == "front"
    assert "assumed_odds" in text_client.calls[0]["system_prompt"]


def test_parse_research_report_keeps_old_payload_compatible() -> None:
    mark = next(iter(research_parser._VALID_MARKS))
    text_client = _DummyTextClient(json.dumps({"marks": [{"umaban": "1", "horse_name": "A", "mark": mark, "comment": ""}], "tickets": []}, ensure_ascii=False))

    parsed = research_parser.parse_research_report(
        "long enough research report text",
        [{"umaban": "1", "horse_name": "A"}],
        client=text_client,
    )

    assert parsed.marks[0].assumed_odds is None
    assert parsed.marks[0].assumed_ev is None
    assert parsed.assumed_pace_label == ""
    assert parsed.assumed_frame_bias == ""
    assert parsed.assumed_style_bias == ""


def test_parse_research_report_raises_value_error_after_retry_failure() -> None:
    text_client = _DummyTextClient(["{broken", "still broken"])

    with pytest.raises(ValueError):
        research_parser.parse_research_report("十分な長さのレポート本文です。", [], client=text_client)


def test_parse_research_report_allows_empty_entry_horses() -> None:
    text_client = _DummyTextClient('{"marks":[{"umaban":"①","horse_name":"A","mark":"◎","comment":""}]}')

    parsed = research_parser.parse_research_report("十分な長さのレポート本文です。", [], client=text_client)

    assert parsed.marks[0].umaban == "1"


def test_research_parse_endpoint_success_and_short_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_parse(raw_text, entry_horses):
        return research_parser.ResearchParsed(
            marks=[{"umaban": "1", "horse_name": "A", "mark": "◎", "comment": "軸"}],
        )

    monkeypatch.setattr(races_api.research_parser, "parse_research_report", fake_parse)
    response = client.post(
        "/api/v1/races/202605310505/research/parse",
        json={"raw_text": "十分な長さのレポート本文です。", "entry_horses": [{"umaban": "1", "horse_name": "A"}]},
    )
    short_response = client.post(
        "/api/v1/races/202605310505/research/parse",
        json={"raw_text": "短い", "entry_horses": []},
    )

    assert response.status_code == 200
    assert response.json()["marks"][0]["mark"] == "◎"
    assert short_response.status_code == 422


def test_research_parse_endpoint_maps_external_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_parse(raw_text, entry_horses):
        raise ExternalApiError("gemini", "GEMINI_API_KEY is not configured", code="not_configured")

    monkeypatch.setattr(races_api.research_parser, "parse_research_report", fake_parse)
    response = client.post(
        "/api/v1/races/202605310505/research/parse",
        json={"raw_text": "十分な長さのレポート本文です。", "entry_horses": []},
    )

    assert response.status_code == 503
    assert "not_configured" in response.json()["detail"]
