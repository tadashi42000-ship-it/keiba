from __future__ import annotations

import requests

from .base import ExternalApiError


class GeminiTextClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.5-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_sec: float = 30.0,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip() or "gemini-2.5-flash"
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def model_name(self) -> str:
        return self._model

    def generate_text(self, *, prompt: str, system_prompt: str | None = None) -> str:
        if not self.is_configured:
            raise ExternalApiError(
                "gemini",
                "GEMINI_API_KEY is not configured",
                code="not_configured",
            )

        content_text = (prompt or "").strip()
        if not content_text:
            raise ExternalApiError("gemini", "prompt must not be empty", code="invalid_input")

        url = f"{self._base_url}/models/{self._model}:generateContent"
        payload: dict[str, object] = {
            "contents": [{"parts": [{"text": content_text}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
            },
        }
        if system_prompt and system_prompt.strip():
            payload["systemInstruction"] = {"parts": [{"text": system_prompt.strip()}]}

        try:
            response = requests.post(
                url,
                params={"key": self._api_key},
                json=payload,
                timeout=self._timeout_sec,
            )
        except requests.RequestException as exc:
            raise ExternalApiError(
                "gemini",
                f"request failed: {exc}",
                code="request_failed",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            message = response.text.strip()
            try:
                body = response.json()
                if isinstance(body, dict):
                    msg = ((body.get("error") or {}).get("message")) if isinstance(body.get("error"), dict) else None
                    if msg:
                        message = str(msg)
            except ValueError:
                pass
            raise ExternalApiError(
                "gemini",
                f"http {response.status_code}: {message[:300]}",
                code="upstream_http_error",
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ExternalApiError("gemini", "invalid JSON response", code="invalid_response") from exc

        text = _extract_text_from_response(body)
        if not text:
            raise ExternalApiError("gemini", "empty text response", code="empty_response")
        return text


def _extract_text_from_response(body: object) -> str:
    if not isinstance(body, dict):
        return ""
    candidates = body.get("candidates", [])
    if not isinstance(candidates, list):
        return ""
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        content = cand.get("content", {})
        if not isinstance(content, dict):
            continue
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue
        chunks: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
        if chunks:
            return "\n".join(chunks).strip()
    return ""
