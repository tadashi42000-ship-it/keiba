from __future__ import annotations

import requests

from .base import ExternalApiError


class XRecentSearchClient:
    def __init__(
        self,
        *,
        bearer_token: str,
        primary_base_url: str = "https://api.x.com",
        fallback_base_url: str = "https://api.twitter.com",
        timeout_sec: float = 20.0,
    ) -> None:
        self._bearer_token = (bearer_token or "").strip()
        self._primary_base_url = primary_base_url.rstrip("/")
        self._fallback_base_url = fallback_base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._active_base_url = self._primary_base_url

    @property
    def is_configured(self) -> bool:
        return bool(self._bearer_token)

    @property
    def active_base_url(self) -> str:
        return self._active_base_url

    def search_recent(
        self,
        *,
        query: str,
        max_results: int = 30,
        since_id: str | None = None,
        next_token: str | None = None,
    ) -> dict:
        if not self.is_configured:
            raise ExternalApiError(
                "x",
                "X_BEARER_TOKEN is not configured",
                code="not_configured",
            )

        q = (query or "").strip()
        if not q:
            raise ExternalApiError("x", "query must not be empty", code="invalid_input")

        params: dict[str, str | int] = {
            "query": q,
            "max_results": max(10, min(int(max_results), 100)),
            "tweet.fields": "created_at,public_metrics,author_id",
            "expansions": "author_id",
            "user.fields": "username",
        }
        if since_id:
            params["since_id"] = str(since_id)
        if next_token:
            params["next_token"] = str(next_token)

        headers = {"Authorization": f"Bearer {self._bearer_token}"}
        path = "/2/tweets/search/recent"

        try:
            response = requests.get(
                f"{self._active_base_url}{path}",
                headers=headers,
                params=params,
                timeout=self._timeout_sec,
            )
        except requests.RequestException as first_error:
            if self._active_base_url != self._primary_base_url:
                raise ExternalApiError(
                    "x",
                    f"request failed: {first_error}",
                    code="request_failed",
                    retryable=True,
                ) from first_error
            response = self._fallback_request(path=path, headers=headers, params=params, cause=first_error)

        if response.status_code >= 400:
            message = response.text.strip()
            try:
                body = response.json()
                err = body.get("detail") if isinstance(body, dict) else None
                if isinstance(err, str):
                    message = err
                elif isinstance(err, list) and err:
                    first = err[0]
                    if isinstance(first, dict) and first.get("message"):
                        message = str(first.get("message"))
            except ValueError:
                pass

            retryable = response.status_code in (429, 500, 502, 503, 504)
            raise ExternalApiError(
                "x",
                f"http {response.status_code}: {message[:300]}",
                code="upstream_http_error",
                status_code=response.status_code,
                retryable=retryable,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ExternalApiError("x", "invalid JSON response", code="invalid_response") from exc

        if not isinstance(body, dict):
            raise ExternalApiError("x", "invalid response shape", code="invalid_response")
        return body

    def _fallback_request(
        self,
        *,
        path: str,
        headers: dict,
        params: dict,
        cause: Exception,
    ) -> requests.Response:
        try:
            response = requests.get(
                f"{self._fallback_base_url}{path}",
                headers=headers,
                params=params,
                timeout=self._timeout_sec,
            )
        except requests.RequestException as fallback_error:
            raise ExternalApiError(
                "x",
                f"request failed: {fallback_error}",
                code="request_failed",
                retryable=True,
            ) from fallback_error

        self._active_base_url = self._fallback_base_url
        return response
