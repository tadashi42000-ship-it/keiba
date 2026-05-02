from __future__ import annotations

import requests

from .base import ExternalApiError, YouTubeVideo


class YouTubeSearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://www.googleapis.com/youtube/v3",
        timeout_sec: float = 20.0,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def search_videos(self, *, query: str, max_results: int = 5) -> list[YouTubeVideo]:
        if not self.is_configured:
            raise ExternalApiError(
                "youtube",
                "YOUTUBE_API_KEY is not configured",
                code="not_configured",
            )

        q = (query or "").strip()
        if not q:
            raise ExternalApiError("youtube", "query must not be empty", code="invalid_input")

        url = f"{self._base_url}/search"
        params = {
            "key": self._api_key,
            "q": q,
            "part": "id,snippet",
            "type": "video",
            "order": "relevance",
            "regionCode": "JP",
            "relevanceLanguage": "ja",
            "maxResults": max(1, min(int(max_results), 25)),
        }

        try:
            response = requests.get(url, params=params, timeout=self._timeout_sec)
        except requests.RequestException as exc:
            raise ExternalApiError(
                "youtube",
                f"request failed: {exc}",
                code="request_failed",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            message = response.text.strip()
            try:
                body = response.json()
                err = body.get("error", {}) if isinstance(body, dict) else {}
                if isinstance(err, dict):
                    message = str(err.get("message") or message)
            except ValueError:
                pass
            raise ExternalApiError(
                "youtube",
                f"http {response.status_code}: {message[:300]}",
                code="upstream_http_error",
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ExternalApiError("youtube", "invalid JSON response", code="invalid_response") from exc

        items = body.get("items", []) if isinstance(body, dict) else []
        if not isinstance(items, list):
            return []

        videos: list[YouTubeVideo] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            video_id = ((item.get("id") or {}).get("videoId")) if isinstance(item.get("id"), dict) else None
            snippet = item.get("snippet", {}) if isinstance(item.get("snippet"), dict) else {}
            if not video_id:
                continue
            videos.append(
                YouTubeVideo(
                    video_id=str(video_id),
                    title=str(snippet.get("title") or "").strip(),
                    description=str(snippet.get("description") or "").strip(),
                    channel_title=str(snippet.get("channelTitle") or "").strip(),
                    published_at=str(snippet.get("publishedAt") or "").strip(),
                    thumbnail_url=_extract_thumbnail_url(snippet),
                    video_url=f"https://www.youtube.com/watch?v={video_id}",
                )
            )
        return videos


def _extract_thumbnail_url(snippet: dict) -> str:
    thumbnails = snippet.get("thumbnails", {})
    if not isinstance(thumbnails, dict):
        return ""
    for key in ("high", "medium", "default"):
        val = thumbnails.get(key)
        if isinstance(val, dict) and val.get("url"):
            return str(val["url"]).strip()
    return ""
