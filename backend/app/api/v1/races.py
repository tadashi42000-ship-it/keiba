from fastapi import APIRouter, HTTPException, Query

from app.clients import ExternalApiError
from app.schemas.races import (
    BetPlanRequest,
    BetPlanResponse,
    FetchCsvRequest,
    FetchCsvResponse,
    OddsResponse,
    RaceCacheResponse,
    RaceCacheUpsertRequest,
    RaceCacheUpsertResponse,
    RaceCharacteristicsResponse,
    RaceCourseStatsResponse,
    RaceEntryResponse,
    ResearchNotesBackup,
    ResearchNotesBackupResponse,
    ResearchParsed,
    ResearchParseRequest,
    SameDayRacesResponse,
    SameDaySheetResponse,
    ResolveRaceIdResponse,
    UpcomingRace,
    UpcomingRacesResponse,
)
from app.services.research_notes_store import load_research_notes_backup, save_research_notes_backup
from app.services import research_parser
from app.services.race_service import (
    fetch_odds_for_race,
    fetch_race_csv_file,
    get_minimal_race_characteristics_by_key,
    get_race_cache_by_key,
    get_upcoming_races,
    resolve_race_id_by_key,
    save_race_cache_by_key,
)
from app.services.same_day_service import (
    build_bet_plan_snapshot,
    build_same_day_sheet_snapshot,
    get_course_stats_snapshot,
    get_entry_snapshot,
    get_same_day_races,
    refresh_same_day_sheet_volatile,
)

from datetime import date as Date

router = APIRouter(prefix="/races")


@router.get("/upcoming", response_model=UpcomingRacesResponse)
def api_upcoming_races(
    months_ahead: int = Query(default=2, ge=0, le=6),
    days_ahead: int = Query(default=14, ge=1, le=180),
    days_back: int = Query(default=7, ge=0, le=30),
) -> UpcomingRacesResponse:
    items = get_upcoming_races(
        months_ahead=months_ahead,
        days_ahead=days_ahead,
        days_back=days_back,
    )
    return UpcomingRacesResponse(races=[UpcomingRace(**item) for item in items])


@router.get("/same-day", response_model=SameDayRacesResponse)
def api_same_day_races(
    target_date: Date = Query(..., alias="date"),
    venue: str | None = Query(default=None),
) -> SameDayRacesResponse:
    result = get_same_day_races(target_date=target_date, venue=venue)
    return SameDayRacesResponse(**result)


@router.get("/same-day-sheet", response_model=SameDaySheetResponse)
def api_same_day_sheet(
    target_date: Date = Query(..., alias="date"),
    venue: str = Query(...),
    budget_yen: int = Query(default=3000, ge=100, le=100000),
    refresh: bool = Query(default=False),
) -> SameDaySheetResponse:
    result = build_same_day_sheet_snapshot(
        target_date=target_date,
        venue=venue,
        budget_yen=budget_yen,
        refresh=refresh,
    )
    return SameDaySheetResponse(**result)


@router.post("/same-day-sheet/refresh-volatile", response_model=SameDaySheetResponse)
def api_same_day_sheet_refresh_volatile(
    target_date: Date = Query(..., alias="date"),
    venue: str = Query(...),
    budget_yen: int = Query(default=3000, ge=100, le=100000),
    race_id: str | None = Query(default=None),
    race_number: str | None = Query(default=None),
) -> SameDaySheetResponse:
    result = refresh_same_day_sheet_volatile(
        target_date=target_date,
        venue=venue,
        budget_yen=budget_yen,
        race_id=race_id,
        race_number=race_number,
    )
    return SameDaySheetResponse(**result)


@router.get("/resolve-id", response_model=ResolveRaceIdResponse)
def api_resolve_race_id(
    race_key: str,
    months_ahead: int = Query(default=2, ge=0, le=6),
    days_ahead: int = Query(default=60, ge=1, le=365),
) -> ResolveRaceIdResponse:
    item = resolve_race_id_by_key(race_key=race_key, months_ahead=months_ahead, days_ahead=days_ahead)
    if item is None:
        raise HTTPException(status_code=404, detail="race_key not found")
    return ResolveRaceIdResponse(**item)


@router.post("/fetch-csv", response_model=FetchCsvResponse)
def api_fetch_csv(payload: FetchCsvRequest) -> FetchCsvResponse:
    csv_path = fetch_race_csv_file(race_id=payload.race_id, output_file=payload.output_file)
    return FetchCsvResponse(race_id=payload.race_id, csv_path=csv_path)


@router.get("/{race_id}/odds", response_model=OddsResponse)
def api_race_odds(race_id: str) -> OddsResponse:
    try:
        result = fetch_odds_for_race(race_id=race_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OddsResponse(**result)


@router.get("/{race_id}/entry", response_model=RaceEntryResponse)
def api_race_entry(
    race_id: str,
    venue: str = Query(default=""),
    distance: str = Query(default=""),
    surface: str = Query(default=""),
) -> RaceEntryResponse:
    try:
        result = get_entry_snapshot(race_id=race_id, venue=venue, distance=distance, surface=surface)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RaceEntryResponse(**result)


@router.get("/{race_id}/course-stats", response_model=RaceCourseStatsResponse)
def api_race_course_stats(
    race_id: str,
    venue: str = Query(...),
    distance: str = Query(...),
    surface: str = Query(...),
) -> RaceCourseStatsResponse:
    result = get_course_stats_snapshot(
        race_id=race_id,
        venue=venue,
        distance=distance,
        surface=surface,
    )
    return RaceCourseStatsResponse(**result)


@router.post("/{race_id}/bet-plan", response_model=BetPlanResponse)
def api_race_bet_plan(race_id: str, payload: BetPlanRequest) -> BetPlanResponse:
    result = build_bet_plan_snapshot(race_id=race_id, budget_yen=payload.budget_yen)
    return BetPlanResponse(**result)


@router.post("/{race_id}/research/parse", response_model=ResearchParsed)
def api_parse_research_report(race_id: str, payload: ResearchParseRequest) -> ResearchParsed:
    if not payload.raw_text or len(payload.raw_text.strip()) < 10:
        raise HTTPException(status_code=422, detail="raw_text が短すぎます")
    try:
        return research_parser.parse_research_report(payload.raw_text, payload.entry_horses)
    except ExternalApiError as exc:
        status_code = 503 if exc.code == "not_configured" else 502
        raise HTTPException(status_code=status_code, detail=f"{exc.provider}:{exc.code}: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{race_id}/research/notes", response_model=ResearchNotesBackupResponse)
def api_get_research_notes_backup(race_id: str) -> ResearchNotesBackupResponse:
    return load_research_notes_backup(race_id)


@router.put("/{race_id}/research/notes", response_model=ResearchNotesBackupResponse)
def api_put_research_notes_backup(race_id: str, payload: ResearchNotesBackup) -> ResearchNotesBackupResponse:
    try:
        return save_research_notes_backup(race_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/characteristics", response_model=RaceCharacteristicsResponse)
def api_race_characteristics(
    race_key: str,
    months_ahead: int = Query(default=2, ge=0, le=6),
    days_ahead: int = Query(default=120, ge=7, le=365),
) -> RaceCharacteristicsResponse:
    result = get_minimal_race_characteristics_by_key(
        race_key=race_key,
        months_ahead=months_ahead,
        days_ahead=days_ahead,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="race_key not found")
    return RaceCharacteristicsResponse(**result)


@router.get("/cache", response_model=RaceCacheResponse)
def api_race_cache(race_key: str) -> RaceCacheResponse:
    return RaceCacheResponse(**get_race_cache_by_key(race_key))


@router.put("/cache", response_model=RaceCacheUpsertResponse)
def api_race_cache_upsert(race_key: str, payload: RaceCacheUpsertRequest) -> RaceCacheUpsertResponse:
    try:
        result = save_race_cache_by_key(race_key=race_key, payload=payload.payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RaceCacheUpsertResponse(**result)
