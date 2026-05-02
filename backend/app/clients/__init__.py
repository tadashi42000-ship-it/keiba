"""External API client abstractions."""

from .base import (
    ExternalApiError,
    SearchDocument,
    TextAnalysisClient,
    WebSearchClient,
    XClient,
    XTweet,
    YouTubeClient,
    YouTubeVideo,
)
from .gemini_client import GeminiTextClient
from .tavily_client import TavilyWebSearchClient
from .x_client import XRecentSearchClient
from .youtube_client import YouTubeSearchClient

__all__ = [
    "ExternalApiError",
    "SearchDocument",
    "TextAnalysisClient",
    "WebSearchClient",
    "XClient",
    "XTweet",
    "YouTubeClient",
    "YouTubeVideo",
    "GeminiTextClient",
    "TavilyWebSearchClient",
    "XRecentSearchClient",
    "YouTubeSearchClient",
]
