from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ExternalApiError(RuntimeError):
    def __init__(
        self,
        provider: str,
        message: str,
        *,
        code: str = "external_error",
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


@dataclass(slots=True)
class SearchDocument:
    title: str
    url: str
    content: str
    score: float | None = None
    published_date: str | None = None


@dataclass(slots=True)
class YouTubeVideo:
    video_id: str
    title: str
    description: str
    channel_title: str
    published_at: str
    thumbnail_url: str
    video_url: str


@dataclass(slots=True)
class XTweet:
    tweet_id: str
    text: str
    author_username: str
    author_label: str
    created_at: str
    url: str
    public_metrics: dict


class WebSearchClient(Protocol):
    @property
    def is_configured(self) -> bool: ...

    def search(
        self,
        *,
        query: str,
        max_results: int = 5,
        include_domains: list[str] | None = None,
    ) -> list[SearchDocument]: ...


class TextAnalysisClient(Protocol):
    @property
    def is_configured(self) -> bool: ...

    def generate_text(self, *, prompt: str, system_prompt: str | None = None) -> str: ...


class YouTubeClient(Protocol):
    @property
    def is_configured(self) -> bool: ...

    def search_videos(self, *, query: str, max_results: int = 5) -> list[YouTubeVideo]: ...


class XClient(Protocol):
    @property
    def is_configured(self) -> bool: ...

    def search_recent(
        self,
        *,
        query: str,
        max_results: int = 30,
        since_id: str | None = None,
        next_token: str | None = None,
    ) -> dict: ...
