from typing import Any

from pydantic import BaseModel, Field


class UpcomingRace(BaseModel):
    race_name: str
    grade: str
    date_str: str
    date_iso: str
    venue: str
    distance: str
    surface: str
    race_id: str | None = None
    race_key: str
    race_number: str = ""


class UpcomingRacesResponse(BaseModel):
    races: list[UpcomingRace]


class ResolveRaceIdResponse(BaseModel):
    race_key: str
    race_id: str | None = None
    resolved: bool


class FetchCsvRequest(BaseModel):
    race_id: str = Field(..., min_length=12, max_length=12)
    output_file: str | None = None


class FetchCsvResponse(BaseModel):
    race_id: str
    csv_path: str


class OddsHorse(BaseModel):
    horse_name: str
    umaban: str | None = None
    waku: str | None = None
    odds: float | None = None


class OddsResponse(BaseModel):
    race_id: str
    source_csv: str
    horses: list[OddsHorse]


class RecentRunDetail(BaseModel):
    date: str = ""
    venue: str = ""
    finish: str = ""
    race_name: str = ""
    course: str = ""
    race_time: str = ""
    margin: str = ""
    time_index: float | None = None
    race_level: str = ""
    race_eval: str = ""
    last3f: str = ""
    corner: str = ""
    field_size: str = ""


class SameDayRacesResponse(BaseModel):
    date: str
    venue: str = ""
    venues: list[str]
    races: list[UpcomingRace]


class EntryHorse(BaseModel):
    horse_name: str
    waku: str = ""
    umaban: str = ""
    sex_age: str = ""
    weight: str = ""
    body_weight: str = ""
    body_delta: str = ""
    jockey: str = ""
    style: str = ""
    odds: float | None = None
    recent_runs: list[str] = Field(default_factory=list)
    last3fs: list[str] = Field(default_factory=list)
    corners: list[str] = Field(default_factory=list)
    field_sizes: list[str] = Field(default_factory=list)
    recent_run_details: list[RecentRunDetail] = Field(default_factory=list)


class RaceEntryResponse(BaseModel):
    race_id: str
    source_csv: str
    start_time: str = ""
    weather: str = ""
    track_conditions: dict[str, str] = Field(default_factory=dict)
    race_data01: str = ""
    race_data02: str = ""
    odds_updated_at: str = ""
    body_updated_at: str = ""
    horses: list[EntryHorse]
    style_distribution: dict[str, int] = Field(default_factory=dict)
    style_distribution_label: str = ""
    warnings: list[str] = Field(default_factory=list)


class CourseStatsSummary(BaseModel):
    course: str = ""
    winning_type: str = ""
    pace_note: str = ""


class RaceCourseStatsResponse(BaseModel):
    race_id: str
    schema_version: str
    source_url: str = ""
    sample_race_count: int = 0
    target: dict[str, Any] = Field(default_factory=dict)
    frame_stats: list[dict[str, Any]] = Field(default_factory=list)
    style_stats: list[dict[str, Any]] = Field(default_factory=list)
    popularity_stats: list[dict[str, Any]] = Field(default_factory=list)
    pace_tendency: str = ""
    frame_markdown: str = ""
    summary: CourseStatsSummary = Field(default_factory=CourseStatsSummary)


class BetPlanRequest(BaseModel):
    budget_yen: int = Field(default=3000, ge=100, le=100000)


class BetRankingItem(BaseModel):
    horse_name: str
    umaban: str = ""
    waku: str = ""
    odds: float | None = None
    style: str = ""
    score: float
    reason: str = ""


class BetTicket(BaseModel):
    type: str
    selection: str
    horse_names: list[str] = Field(default_factory=list)
    amount_yen: int
    reason: str = ""


class BetPlanResponse(BaseModel):
    race_id: str
    budget_yen: int
    provisional_only: bool
    ranking: list[BetRankingItem]
    tickets: list[BetTicket]
    warnings: list[str] = Field(default_factory=list)


class SameDaySheetRace(BaseModel):
    race: UpcomingRace
    entry: RaceEntryResponse | None = None
    course_stats: RaceCourseStatsResponse | None = None
    bet_plan: BetPlanResponse | None = None
    error: str = ""


class SameDaySheetResponse(BaseModel):
    generated_at: str
    date: str
    venue: str
    race_count: int
    races: list[SameDaySheetRace]


class RaceCharacteristicsResponse(BaseModel):
    race_key: str
    race_id: str | None = None
    race_name: str
    grade: str
    venue: str
    distance: str
    surface: str
    characteristics: dict[str, str]


class RaceCacheResponse(BaseModel):
    race_key: str
    cache_path: str
    exists: bool
    meta: dict[str, Any]
    data: dict[str, Any]


class RaceCacheUpsertRequest(BaseModel):
    payload: dict[str, Any]


class RaceCacheUpsertResponse(BaseModel):
    race_key: str
    cache_path: str
    saved_at: str
