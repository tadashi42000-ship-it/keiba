from __future__ import annotations

from app.clients import YouTubeVideo
from app.services.external_analysis_service import (
    ExternalAnalysisService,
    _build_youtube_query_candidates,
    _filter_relevant_videos,
)


def _video(video_id: str, title: str, description: str = "", channel: str = "indie") -> YouTubeVideo:
    return YouTubeVideo(
        video_id=video_id,
        title=title,
        description=description,
        channel_title=channel,
        published_at="2026-04-15T00:00:00Z",
        thumbnail_url="",
        video_url=f"https://www.youtube.com/watch?v={video_id}",
    )


def test_youtube_filter_strict_race_drops_other_race_title_even_if_desc_mentions_target() -> None:
    videos = [
        _video("a", "【桜花賞2026】最終予想 本命発表", "追い切り評価と展開予想"),
        _video("b", "【東京スプリント2026】最終予想", "桜花賞の話題にも少し触れます"),
    ]

    result = _filter_relevant_videos(videos, race_name="桜花賞", query="桜花賞 2026 予想")

    assert [v.video_id for v in result] == ["a"]


def test_youtube_filter_strict_race_returns_empty_when_no_target_match() -> None:
    videos = [
        _video("a", "【東京スプリント2026】予想", "大井1200mの展望"),
        _video("b", "【皐月賞2026】予想", "中山2000mの展望"),
    ]

    result = _filter_relevant_videos(videos, race_name="桜花賞", query="桜花賞 2026 予想")

    assert result == []


def test_youtube_filter_non_strict_keeps_videos_when_race_name_is_empty() -> None:
    videos = [
        _video("a", "競馬ニュース", "今週の注目レース"),
        _video("b", "パドック解説", "馬体診断"),
    ]

    result = _filter_relevant_videos(videos, race_name="", query="競馬")

    assert len(result) >= 1
    assert result[0].video_id == "a"


def test_build_youtube_query_candidates_adds_race_fallback_queries() -> None:
    queries = _build_youtube_query_candidates(query="予想", race_name="桜花賞")
    assert "予想" in queries
    assert "桜花賞 競馬 予想" in queries
    assert "桜花賞 予想" in queries


class _DummyWebSearchClient:
    is_configured = True

    def search(self, *, query: str, max_results: int = 5, include_domains=None):
        return []


class _DummyTextClient:
    is_configured = True

    def generate_text(self, *, prompt: str, system_prompt: str | None = None) -> str:
        return "ok"


class _DummyXClient:
    is_configured = True

    def search_recent(self, *, query: str, max_results: int = 30, since_id=None, next_token=None):
        return {"data": [], "meta": {}}


class _DummyYouTubeClient:
    is_configured = True

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search_videos(self, *, query: str, max_results: int = 5):
        self.queries.append(query)
        if "競馬 予想" in query:
            return [_video("target", "【桜花賞2026】最終予想", "追い切り評価")]
        return [_video("other", "【東京スプリント2026】最終予想", "大井1200m")]


def test_external_service_youtube_search_uses_fallback_query_candidates() -> None:
    youtube = _DummyYouTubeClient()
    service = ExternalAnalysisService(
        web_search_client=_DummyWebSearchClient(),
        text_analysis_client=_DummyTextClient(),
        youtube_client=youtube,
        x_client=_DummyXClient(),
        x_accounts_path="",
    )

    result = service.youtube_search(query="桜花賞 2026 予想", race_name="桜花賞", max_results=1)

    assert len(youtube.queries) >= 2
    assert result["total_after_filter"] >= 1
    assert result["videos"][0]["video_id"] == "target"
