import pytest

from app.services.race_service import (
    MAX_CACHE_DEPTH,
    MAX_CACHE_STRING_LENGTH,
    validate_cache_payload,
)


def test_validate_cache_payload_accepts_minimal_payload() -> None:
    payload = {
        "meta": {"race_key": "2026-04-20_中山_皐月賞"},
        "web_raw": [],
        "youtube_raw": [],
    }
    validate_cache_payload(payload)


def test_validate_cache_payload_rejects_unknown_top_level_key() -> None:
    payload = {
        "meta": {},
        "web_raw": [],
        "unexpected_debug": {"enabled": True},
    }
    with pytest.raises(ValueError, match="unsupported top-level keys"):
        validate_cache_payload(payload)


def test_validate_cache_payload_rejects_deep_nesting() -> None:
    nested: dict[str, object] = {"value": "ok"}
    for _ in range(MAX_CACHE_DEPTH + 1):
        nested = {"next": nested}
    payload = {
        "meta": {},
        "web_raw": [nested],
    }
    with pytest.raises(ValueError, match="nesting is too deep"):
        validate_cache_payload(payload)


def test_validate_cache_payload_rejects_too_long_string() -> None:
    payload = {
        "meta": {},
        "web_raw": [{"text": "x" * (MAX_CACHE_STRING_LENGTH + 1)}],
    }
    with pytest.raises(ValueError, match="string is too long"):
        validate_cache_payload(payload)
