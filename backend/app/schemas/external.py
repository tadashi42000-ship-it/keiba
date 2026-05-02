from pydantic import BaseModel, Field


class ProviderStatusItem(BaseModel):
    configured: bool
    accounts_count: int | None = None
    default_max_tweets: int | None = None


class ExternalProvidersResponse(BaseModel):
    tavily: ProviderStatusItem
    gemini: ProviderStatusItem
    youtube: ProviderStatusItem
    x: ProviderStatusItem


class WebSummaryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=300)
    max_results: int = Field(default=5, ge=1, le=10)
    include_domains: list[str] = Field(default_factory=list, max_length=15)


class WebSummarySource(BaseModel):
    title: str
    url: str
    score: float | None = None
    published_date: str | None = None


class WebSummaryResponse(BaseModel):
    query: str
    summary: str
    sources: list[WebSummarySource]


class YouTubeVideoItem(BaseModel):
    video_id: str
    title: str
    description: str
    channel_title: str
    published_at: str
    thumbnail_url: str
    video_url: str


class YouTubeSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=300)
    race_name: str = Field(default="", max_length=120)
    max_results: int = Field(default=5, ge=1, le=10)


class HorseAnalysisItem(BaseModel):
    horse: str
    plus: str
    minus: str
    source_type: str
    source_title: str
    source_url: str


class YouTubeVideoConclusionItem(BaseModel):
    head_pick: str = ""
    second_pick: str = ""
    dark_horse: str = ""
    danger_horse: str = ""
    bet_strategy: str = ""
    video_id: str = ""
    video_title: str = ""
    video_url: str = ""


class YouTubeSearchResponse(BaseModel):
    query: str
    race_name: str
    videos: list[YouTubeVideoItem]
    total_fetched: int
    total_after_filter: int


class YouTubeSummaryResponse(YouTubeSearchResponse):
    summary: str


class YouTubeHorseAnalysisRequest(YouTubeSearchRequest):
    horse_names: list[str] = Field(default_factory=list, max_length=80)


class YouTubeHorseAnalysisResponse(YouTubeSearchResponse):
    analysis_items: list[HorseAnalysisItem] = Field(default_factory=list)
    video_conclusions: list[YouTubeVideoConclusionItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class XAccountItem(BaseModel):
    username: str
    label: str


class XAccountsResponse(BaseModel):
    accounts: list[XAccountItem]
    default_max_tweets: int


class XTweetItem(BaseModel):
    tweet_id: str
    text: str
    author_username: str
    author_label: str
    created_at: str
    url: str
    public_metrics: dict


class XSearchRequest(BaseModel):
    race_name: str = Field(..., min_length=2, max_length=120)
    max_tweets: int = Field(default=30, ge=5, le=100)
    since_id: str | None = Field(default=None, max_length=30)


class XSearchResponse(BaseModel):
    race_name: str
    tweets: list[XTweetItem]
    newest_id: str | None = None
    dropped_count: int = 0
    used_queries: list[str] = Field(default_factory=list)
    accounts_count: int = 0
    default_max_tweets: int = 30


class XSummaryResponse(XSearchResponse):
    summary: str


class XHorseAnalysisRequest(XSearchRequest):
    horse_names: list[str] = Field(default_factory=list, max_length=80)


class XHorseAnalysisResponse(XSearchResponse):
    analysis_items: list[HorseAnalysisItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
