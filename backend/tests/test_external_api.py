from fastapi.testclient import TestClient

from app.api.v1 import external as external_api
from app.clients import ExternalApiError
from app.main import app


client = TestClient(app)


class _DummyService:
    def __init__(
        self,
        *,
        tavily_configured: bool,
        gemini_configured: bool,
        youtube_configured: bool,
        x_configured: bool,
    ) -> None:
        self._tavily_configured = tavily_configured
        self._gemini_configured = gemini_configured
        self._youtube_configured = youtube_configured
        self._x_configured = x_configured

    def provider_status(self) -> dict:
        return {
            "tavily": {"configured": self._tavily_configured},
            "gemini": {"configured": self._gemini_configured},
            "youtube": {"configured": self._youtube_configured},
            "x": {"configured": self._x_configured, "accounts_count": 2, "default_max_tweets": 30},
        }

    def web_summary(self, *, query: str, max_results: int = 5, include_domains=None) -> dict:
        return {
            "query": query,
            "summary": "test summary",
            "sources": [
                {
                    "title": "source-1",
                    "url": "https://example.com/1",
                    "score": 0.9,
                    "published_date": "2026-04-15",
                }
            ],
        }

    def youtube_search(self, *, query: str, max_results: int = 5, race_name: str = "") -> dict:
        return {
            "query": query,
            "race_name": race_name,
            "total_fetched": 6,
            "total_after_filter": 2,
            "videos": [
                {
                    "video_id": "abc123",
                    "title": "Satsuki prediction",
                    "description": "analysis",
                    "channel_title": "Test Channel",
                    "published_at": "2026-04-15T00:00:00Z",
                    "thumbnail_url": "https://example.com/thumb.jpg",
                    "video_url": "https://www.youtube.com/watch?v=abc123",
                }
            ],
        }

    def youtube_summary(self, *, query: str, max_results: int = 5, race_name: str = "") -> dict:
        payload = self.youtube_search(query=query, max_results=max_results, race_name=race_name)
        payload["summary"] = "youtube summary"
        return payload

    def youtube_horse_analysis(
        self,
        *,
        query: str,
        race_name: str,
        horse_names: list[str] | None = None,
        max_results: int = 5,
    ) -> dict:
        payload = self.youtube_search(query=query, max_results=max_results, race_name=race_name)
        payload["analysis_items"] = [
            {
                "horse": "Test Horse",
                "plus": "strong workout",
                "minus": "outside draw",
                "source_type": "youtube",
                "source_title": "Satsuki prediction",
                "source_url": "https://www.youtube.com/watch?v=abc123",
            }
        ]
        payload["video_conclusions"] = [
            {
                "head_pick": "Test Horse",
                "second_pick": "Second Horse",
                "dark_horse": "Dark Horse",
                "danger_horse": "Fav Horse",
                "bet_strategy": "small combos",
                "video_id": "abc123",
                "video_title": "Satsuki prediction",
                "video_url": "https://www.youtube.com/watch?v=abc123",
            }
        ]
        payload["warnings"] = []
        return payload

    def load_x_accounts(self) -> tuple[list[dict], int]:
        return [{"username": "tester", "label": "Tester"}], 30

    def x_search(self, *, race_name: str, max_tweets: int = 30, since_id: str | None = None) -> dict:
        return {
            "race_name": race_name,
            "tweets": [
                {
                    "tweet_id": "123",
                    "text": "Satsuki test post",
                    "author_username": "tester",
                    "author_label": "Tester",
                    "created_at": "2026-04-15T00:00:00Z",
                    "url": "https://x.com/tester/status/123",
                    "public_metrics": {"like_count": 10},
                }
            ],
            "newest_id": "123",
            "dropped_count": 0,
            "used_queries": ["(from:tester) race"],
            "accounts_count": 1,
            "default_max_tweets": 30,
        }

    def x_summary(self, *, race_name: str, max_tweets: int = 30, since_id: str | None = None) -> dict:
        payload = self.x_search(race_name=race_name, max_tweets=max_tweets, since_id=since_id)
        payload["summary"] = "x summary"
        return payload

    def x_horse_analysis(
        self,
        *,
        race_name: str,
        horse_names: list[str] | None = None,
        max_tweets: int = 30,
        since_id: str | None = None,
    ) -> dict:
        payload = self.x_search(race_name=race_name, max_tweets=max_tweets, since_id=since_id)
        payload["analysis_items"] = [
            {
                "horse": "Test Horse",
                "plus": "good pace",
                "minus": "distance risk",
                "source_type": "x",
                "source_title": "X @tester",
                "source_url": "https://x.com/tester/status/123",
            }
        ]
        payload["warnings"] = []
        return payload


def _override_dummy_service() -> None:
    app.dependency_overrides[external_api.get_external_analysis_service] = lambda: _DummyService(
        tavily_configured=True,
        gemini_configured=True,
        youtube_configured=True,
        x_configured=True,
    )


def test_external_provider_status() -> None:
    _override_dummy_service()
    response = client.get("/api/v1/external/providers")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert data["tavily"]["configured"] is True
    assert data["youtube"]["configured"] is True
    assert data["x"]["accounts_count"] == 2


def test_external_web_summary_success() -> None:
    _override_dummy_service()
    response = client.post(
        "/api/v1/external/web-summary",
        json={"query": "Satsuki oikiri", "max_results": 3, "include_domains": ["netkeiba.com"]},
    )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "Satsuki oikiri"
    assert data["summary"] == "test summary"
    assert len(data["sources"]) == 1


def test_external_youtube_search_summary_and_horse_analysis() -> None:
    _override_dummy_service()

    search_resp = client.post(
        "/api/v1/external/youtube/search",
        json={"query": "Satsuki", "race_name": "Satsuki Sho", "max_results": 5},
    )
    summary_resp = client.post(
        "/api/v1/external/youtube/summary",
        json={"query": "Satsuki", "race_name": "Satsuki Sho", "max_results": 5},
    )
    horse_resp = client.post(
        "/api/v1/external/youtube/horse-analysis",
        json={
            "query": "Satsuki",
            "race_name": "Satsuki Sho",
            "max_results": 5,
            "horse_names": ["Horse A", "Horse B"],
        },
    )

    app.dependency_overrides.clear()

    assert search_resp.status_code == 200
    assert summary_resp.status_code == 200
    assert horse_resp.status_code == 200

    horse_data = horse_resp.json()
    assert len(horse_data["analysis_items"]) == 1
    assert horse_data["analysis_items"][0]["horse"] == "Test Horse"
    assert len(horse_data["video_conclusions"]) == 1


def test_external_x_accounts_search_summary_and_horse_analysis() -> None:
    _override_dummy_service()

    accounts_resp = client.get("/api/v1/external/x/accounts")
    search_resp = client.post(
        "/api/v1/external/x/search",
        json={"race_name": "Satsuki Sho", "max_tweets": 30},
    )
    summary_resp = client.post(
        "/api/v1/external/x/summary",
        json={"race_name": "Satsuki Sho", "max_tweets": 30},
    )
    horse_resp = client.post(
        "/api/v1/external/x/horse-analysis",
        json={"race_name": "Satsuki Sho", "max_tweets": 30, "horse_names": ["Horse A"]},
    )

    app.dependency_overrides.clear()

    assert accounts_resp.status_code == 200
    assert search_resp.status_code == 200
    assert summary_resp.status_code == 200
    assert horse_resp.status_code == 200

    horse_data = horse_resp.json()
    assert len(horse_data["analysis_items"]) == 1
    assert horse_data["analysis_items"][0]["source_type"] == "x"


def test_external_web_summary_not_configured() -> None:
    class _MissingConfigService(_DummyService):
        def web_summary(self, *, query: str, max_results: int = 5, include_domains=None) -> dict:
            raise ExternalApiError("tavily", "TAVILY_API_KEY is not configured", code="not_configured")

    app.dependency_overrides[external_api.get_external_analysis_service] = lambda: _MissingConfigService(
        tavily_configured=False,
        gemini_configured=True,
        youtube_configured=True,
        x_configured=True,
    )
    response = client.post("/api/v1/external/web-summary", json={"query": "Satsuki oikiri"})
    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "not_configured" in response.json()["detail"]


def test_external_web_summary_upstream_error() -> None:
    class _UpstreamErrorService(_DummyService):
        def web_summary(self, *, query: str, max_results: int = 5, include_domains=None) -> dict:
            raise ExternalApiError(
                "gemini",
                "http 400: invalid request",
                code="upstream_http_error",
                status_code=400,
            )

    app.dependency_overrides[external_api.get_external_analysis_service] = lambda: _UpstreamErrorService(
        tavily_configured=True,
        gemini_configured=True,
        youtube_configured=True,
        x_configured=True,
    )
    response = client.post("/api/v1/external/web-summary", json={"query": "Satsuki oikiri"})
    app.dependency_overrides.clear()
    assert response.status_code == 502
    assert "upstream_http_error" in response.json()["detail"]


def test_external_x_search_not_configured() -> None:
    class _MissingXService(_DummyService):
        def x_search(self, *, race_name: str, max_tweets: int = 30, since_id: str | None = None) -> dict:
            raise ExternalApiError("x", "X_BEARER_TOKEN is not configured", code="not_configured")

    app.dependency_overrides[external_api.get_external_analysis_service] = lambda: _MissingXService(
        tavily_configured=True,
        gemini_configured=True,
        youtube_configured=True,
        x_configured=False,
    )
    response = client.post("/api/v1/external/x/search", json={"race_name": "Satsuki Sho", "max_tweets": 30})
    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "not_configured" in response.json()["detail"]
