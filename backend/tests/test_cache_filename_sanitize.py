from app.services.race_service import _sanitize_race_key_for_cache


def test_sanitize_race_key_for_cache_windows_invalid_chars() -> None:
    raw = '2026-04-05_?阪/神:大*阪<杯>|"'
    safe = _sanitize_race_key_for_cache(raw)
    for ch in '<>:"/\\|?*':
        assert ch not in safe
    assert safe
