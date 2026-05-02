from __future__ import annotations

import requests

from .base import ExternalApiError, SearchDocument


class TavilyWebSearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.tavily.com",
        timeout_sec: float = 20.0,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def search(
        self,
        *,
        query: str,
        max_results: int = 5,
        include_domains: list[str] | None = None,
    ) -> list[SearchDocument]:
        if not self.is_configured:
            raise ExternalApiError(
                "tavily",
                "TAVILY_API_KEY is not configured",
                code="not_configured",
            )

        q = (query or "").strip()
        if not q:
            raise ExternalApiError("tavily", "query must not be empty", code="invalid_input")

        url = f"{self._base_url}/search"
        payload: dict[str, object] = {
            "api_key": self._api_key,
            "query": q,
            "search_depth": "advanced",
            "max_results": max(1, min(int(max_results), 10)),
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
        }
        if include_domains:
            payload["include_domains"] = include_domains

        try:
            response = requests.post(url, json=payload, timeout=self._timeout_sec)
        except requests.RequestException as exc:
            raise ExternalApiError(
                "tavily",
                f"request failed: {exc}",
                code="request_failed",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            message = response.text.strip()
            try:
                body = response.json()
                if isinstance(body, dict) and body.get("error"):
                    message = str(body["error"])
            except ValueError:
                pass
            raise ExternalApiError(
                "tavily",
                f"http {response.status_code}: {message[:300]}",
                code="upstream_http_error",
                status_code=response.status_code,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ExternalApiError("tavily", "invalid JSON response", code="invalid_response") from exc

        raw_results = body.get("results", []) if isinstance(body, dict) else []
        if not isinstance(raw_results, list):
            return []

        docs: list[SearchDocument] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            docs.append(
                SearchDocument(
                    title=str(item.get("title") or "").strip(),
                    url=str(item.get("url") or "").strip(),
                    content=str(item.get("content") or "").strip(),
                    score=_to_float(item.get("score")),
                    published_date=str(item.get("published_date") or "").strip() or None,
                )
            )
        return docs


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None
