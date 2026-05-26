export type HealthResponse = {
  status: string;
  service: string;
  version: string;
};

export type SampleItem = {
  title: string;
  value: string;
};

export type SampleResponse = {
  message: string;
  generated_at: string;
  sample_items: SampleItem[];
};

export type UpcomingRace = {
  race_name: string;
  grade: string;
  date_str: string;
  date_iso: string;
  venue: string;
  distance: string;
  surface: string;
  race_id: string | null;
  race_key: string;
  race_number?: string;
};

export type UpcomingRacesResponse = {
  races: UpcomingRace[];
};

export type ResolveRaceIdResponse = {
  race_key: string;
  race_id: string | null;
  resolved: boolean;
};

export type FetchCsvResponse = {
  race_id: string;
  csv_path: string;
};

export type OddsHorse = {
  horse_name: string;
  umaban: string | null;
  waku?: string | null;
  odds: number | null;
};

export type OddsResponse = {
  race_id: string;
  source_csv: string;
  horses: OddsHorse[];
};

export type RecentRunDetail = {
  date: string;
  venue?: string;
  finish: string;
  race_name: string;
  jockey?: string;
  course: string;
  distance_m?: number | null;
  surface?: string;
  going?: string;
  carried_weight?: number | null;
  race_time: string;
  margin: string;
  time_index: number | null;
  race_level: string;
  race_eval?: string;
  body_weight?: number | null;
  last3f: string;
  race_time_grade?: string;
  race_time_grade_detail?: Record<string, unknown>;
  last3f_grade?: string;
  last3f_grade_detail?: Record<string, unknown>;
  corner: string;
  field_size: string;
};

export type SameDayRacesResponse = {
  date: string;
  venue: string;
  venues: string[];
  races: UpcomingRace[];
};

export type EntryHorse = {
  horse_name: string;
  waku: string;
  umaban: string;
  sex_age: string;
  weight: string;
  body_weight: string;
  body_delta: string;
  body_weight_bucket?: string;
  body_weight_source?: "current" | "previous" | "";
  body_weight_top3_rate?: number | null;
  jockey: string;
  style: string;
  odds: number | null;
  recent_runs: string[];
  last3fs: string[];
  corners: string[];
  field_sizes: string[];
  recent_run_details?: RecentRunDetail[];
  sire_name?: string;
  sire_data_available?: boolean;
  sire_aptitude_marks?: Record<string, string>;
  sire_aptitude_summary?: string;
  sire_aptitude_score?: number;
  sire_aptitude_max_score?: number;
  sire_aptitude_notes?: string;
  broodmare_sire_name?: string;
  broodmare_sire_data_available?: boolean;
  broodmare_sire_aptitude_summary?: string;
  broodmare_sire_aptitude_score?: number;
  broodmare_sire_aptitude_max_score?: number;
};

export type RaceEntryResponse = {
  race_id: string;
  source_csv: string;
  start_time: string;
  weather: string;
  track_conditions: Record<string, string>;
  race_data01: string;
  race_data02: string;
  odds_updated_at?: string;
  body_updated_at?: string;
  horses: EntryHorse[];
  style_distribution: Record<string, number>;
  style_distribution_label: string;
  warnings: string[];
};

export type CourseStatsSummary = {
  course: string;
  winning_type: string;
  pace_note: string;
};

export type RaceCourseStatsResponse = {
  race_id: string;
  schema_version: string;
  source_url: string;
  sample_race_count: number;
  target: Record<string, unknown>;
  frame_stats: Array<Record<string, unknown>>;
  style_stats: Array<Record<string, unknown>>;
  popularity_stats: Array<Record<string, unknown>>;
  body_weight_stats?: Array<Record<string, unknown>>;
  pace_tendency: string;
  frame_markdown: string;
  summary: CourseStatsSummary;
};

export type BetRankingItem = {
  horse_name: string;
  umaban: string;
  waku: string;
  odds: number | null;
  style: string;
  score: number;
  baseline_score?: number | null;
  bias_bonus?: number;
  reason: string;
};

export type BetTicket = {
  type: string;
  selection: string;
  horse_names: string[];
  amount_yen: number;
  reason: string;
};

export type BetPlanResponse = {
  race_id: string;
  budget_yen: number;
  provisional_only: boolean;
  ranking: BetRankingItem[];
  tickets: BetTicket[];
  warnings: string[];
};

export type TrackBias = {
  frame_bias: Record<string, number>;
  style_bias: Record<string, number>;
  sample_size: number;
  fallback_used: boolean;
  summary_label: string;
  confidence: "high" | "medium" | "low";
};

export type SameDaySheetRace = {
  race: UpcomingRace;
  entry: RaceEntryResponse | null;
  course_stats: RaceCourseStatsResponse | null;
  bet_plan: BetPlanResponse | null;
  track_bias?: TrackBias | null;
  error: string;
};

export type SameDaySheetResponse = {
  generated_at: string;
  date: string;
  venue: string;
  race_count: number;
  track_bias_schema_version?: string;
  races: SameDaySheetRace[];
};

export type RaceCharacteristicsResponse = {
  race_key: string;
  race_id: string | null;
  race_name: string;
  grade: string;
  venue: string;
  distance: string;
  surface: string;
  characteristics: Record<string, string>;
};

export type RaceCacheResponse = {
  race_key: string;
  cache_path: string;
  exists: boolean;
  meta: Record<string, unknown>;
  data: Record<string, unknown>;
};

export type RaceCacheUpsertResponse = {
  race_key: string;
  cache_path: string;
  saved_at: string;
};

export type ProviderStatusItem = {
  configured: boolean;
  accounts_count?: number | null;
  default_max_tweets?: number | null;
};

export type ExternalProvidersResponse = {
  tavily: ProviderStatusItem;
  gemini: ProviderStatusItem;
  youtube: ProviderStatusItem;
  x: ProviderStatusItem;
};

export type YouTubeVideoItem = {
  video_id: string;
  title: string;
  description: string;
  channel_title: string;
  published_at: string;
  thumbnail_url: string;
  video_url: string;
};

export type YouTubeSearchResponse = {
  query: string;
  race_name: string;
  videos: YouTubeVideoItem[];
  total_fetched: number;
  total_after_filter: number;
};

export type YouTubeSummaryResponse = YouTubeSearchResponse & {
  summary: string;
};

export type HorseAnalysisItem = {
  horse: string;
  plus: string;
  minus: string;
  source_type: string;
  source_title: string;
  source_url: string;
};

export type YouTubeVideoConclusionItem = {
  head_pick: string;
  second_pick: string;
  dark_horse: string;
  danger_horse: string;
  bet_strategy: string;
  video_id: string;
  video_title: string;
  video_url: string;
};

export type YouTubeHorseAnalysisResponse = YouTubeSearchResponse & {
  analysis_items: HorseAnalysisItem[];
  video_conclusions: YouTubeVideoConclusionItem[];
  warnings: string[];
};

export type XAccountItem = {
  username: string;
  label: string;
};

export type XAccountsResponse = {
  accounts: XAccountItem[];
  default_max_tweets: number;
};

export type XTweetItem = {
  tweet_id: string;
  text: string;
  author_username: string;
  author_label: string;
  created_at: string;
  url: string;
  public_metrics: Record<string, unknown>;
};

export type XSearchResponse = {
  race_name: string;
  tweets: XTweetItem[];
  newest_id: string | null;
  dropped_count: number;
  used_queries: string[];
  accounts_count: number;
  default_max_tweets: number;
};

export type XSummaryResponse = XSearchResponse & {
  summary: string;
};

export type XHorseAnalysisResponse = XSearchResponse & {
  analysis_items: HorseAnalysisItem[];
  warnings: string[];
};

export type ExternalSnapshot = {
  youtubeSummary: YouTubeSummaryResponse | null;
  youtubeHorseAnalysis: YouTubeHorseAnalysisResponse | null;
  xSummary: XSummaryResponse | null;
  xHorseAnalysis: XHorseAnalysisResponse | null;
  webSummary: string | null;
  updatedAt: string | null;
};
