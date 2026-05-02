from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.clients import (
    ExternalApiError,
    GeminiTextClient,
    TavilyWebSearchClient,
    XRecentSearchClient,
    YouTubeSearchClient,
)
from app.core.config import settings
from app.schemas.external import (
    ExternalProvidersResponse,
    ProviderStatusItem,
    WebSummaryRequest,
    WebSummaryResponse,
    XAccountsResponse,
    XHorseAnalysisRequest,
    XHorseAnalysisResponse,
    XSearchRequest,
    XSearchResponse,
    XSummaryResponse,
    YouTubeHorseAnalysisRequest,
    YouTubeHorseAnalysisResponse,
    YouTubeSearchRequest,
    YouTubeSearchResponse,
    YouTubeSummaryResponse,
)
from app.services.external_analysis_service import ExternalAnalysisService

router = APIRouter(prefix="/external")


def get_external_analysis_service() -> ExternalAnalysisService:
    return ExternalAnalysisService(
        web_search_client=TavilyWebSearchClient(
            api_key=settings.tavily_api_key,
            base_url=settings.tavily_base_url,
            timeout_sec=settings.external_api_timeout_sec,
        ),
        text_analysis_client=GeminiTextClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            base_url=settings.gemini_base_url,
            timeout_sec=settings.external_api_timeout_sec,
        ),
        youtube_client=YouTubeSearchClient(
            api_key=settings.youtube_api_key,
            timeout_sec=settings.external_api_timeout_sec,
        ),
        x_client=XRecentSearchClient(
            bearer_token=settings.x_bearer_token,
            primary_base_url=settings.x_api_base_primary,
            fallback_base_url=settings.x_api_base_fallback,
            timeout_sec=settings.external_api_timeout_sec,
        ),
        x_accounts_path=settings.x_accounts_path,
    )


@router.get("/providers", response_model=ExternalProvidersResponse)
def api_external_providers(
    service: ExternalAnalysisService = Depends(get_external_analysis_service),
) -> ExternalProvidersResponse:
    status = service.provider_status()
    return ExternalProvidersResponse(
        tavily=ProviderStatusItem(**status["tavily"]),
        gemini=ProviderStatusItem(**status["gemini"]),
        youtube=ProviderStatusItem(**status["youtube"]),
        x=ProviderStatusItem(**status["x"]),
    )


@router.post("/web-summary", response_model=WebSummaryResponse)
def api_external_web_summary(
    payload: WebSummaryRequest,
    service: ExternalAnalysisService = Depends(get_external_analysis_service),
) -> WebSummaryResponse:
    try:
        result = service.web_summary(
            query=payload.query,
            max_results=payload.max_results,
            include_domains=payload.include_domains or None,
        )
    except ExternalApiError as exc:
        raise _external_http_exception(exc) from exc
    return WebSummaryResponse(**result)


@router.post("/youtube/search", response_model=YouTubeSearchResponse)
def api_youtube_search(
    payload: YouTubeSearchRequest,
    service: ExternalAnalysisService = Depends(get_external_analysis_service),
) -> YouTubeSearchResponse:
    try:
        result = service.youtube_search(
            query=payload.query,
            max_results=payload.max_results,
            race_name=payload.race_name,
        )
    except ExternalApiError as exc:
        raise _external_http_exception(exc) from exc
    return YouTubeSearchResponse(**result)


@router.post("/youtube/summary", response_model=YouTubeSummaryResponse)
def api_youtube_summary(
    payload: YouTubeSearchRequest,
    service: ExternalAnalysisService = Depends(get_external_analysis_service),
) -> YouTubeSummaryResponse:
    try:
        result = service.youtube_summary(
            query=payload.query,
            max_results=payload.max_results,
            race_name=payload.race_name,
        )
    except ExternalApiError as exc:
        raise _external_http_exception(exc) from exc
    return YouTubeSummaryResponse(**result)


@router.post("/youtube/horse-analysis", response_model=YouTubeHorseAnalysisResponse)
def api_youtube_horse_analysis(
    payload: YouTubeHorseAnalysisRequest,
    service: ExternalAnalysisService = Depends(get_external_analysis_service),
) -> YouTubeHorseAnalysisResponse:
    try:
        result = service.youtube_horse_analysis(
            query=payload.query,
            race_name=payload.race_name,
            horse_names=payload.horse_names,
            max_results=payload.max_results,
        )
    except ExternalApiError as exc:
        raise _external_http_exception(exc) from exc
    return YouTubeHorseAnalysisResponse(**result)


@router.get("/x/accounts", response_model=XAccountsResponse)
def api_x_accounts(
    service: ExternalAnalysisService = Depends(get_external_analysis_service),
) -> XAccountsResponse:
    accounts, default_max_tweets = service.load_x_accounts()
    return XAccountsResponse(accounts=accounts, default_max_tweets=default_max_tweets)


@router.post("/x/search", response_model=XSearchResponse)
def api_x_search(
    payload: XSearchRequest,
    service: ExternalAnalysisService = Depends(get_external_analysis_service),
) -> XSearchResponse:
    try:
        result = service.x_search(
            race_name=payload.race_name,
            max_tweets=payload.max_tweets,
            since_id=payload.since_id,
        )
    except ExternalApiError as exc:
        raise _external_http_exception(exc) from exc
    return XSearchResponse(**result)


@router.post("/x/summary", response_model=XSummaryResponse)
def api_x_summary(
    payload: XSearchRequest,
    service: ExternalAnalysisService = Depends(get_external_analysis_service),
) -> XSummaryResponse:
    try:
        result = service.x_summary(
            race_name=payload.race_name,
            max_tweets=payload.max_tweets,
            since_id=payload.since_id,
        )
    except ExternalApiError as exc:
        raise _external_http_exception(exc) from exc
    return XSummaryResponse(**result)


@router.post("/x/horse-analysis", response_model=XHorseAnalysisResponse)
def api_x_horse_analysis(
    payload: XHorseAnalysisRequest,
    service: ExternalAnalysisService = Depends(get_external_analysis_service),
) -> XHorseAnalysisResponse:
    try:
        result = service.x_horse_analysis(
            race_name=payload.race_name,
            horse_names=payload.horse_names,
            max_tweets=payload.max_tweets,
            since_id=payload.since_id,
        )
    except ExternalApiError as exc:
        raise _external_http_exception(exc) from exc
    return XHorseAnalysisResponse(**result)


def _external_http_exception(exc: ExternalApiError) -> HTTPException:
    if exc.code == "not_configured":
        status_code = 503
    elif exc.retryable:
        status_code = 503
    else:
        status_code = 502
    return HTTPException(
        status_code=status_code,
        detail=f"{exc.provider}:{exc.code}:{str(exc)}",
    )
