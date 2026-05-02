import type {
  BetPlanResponse,
  ExternalProvidersResponse,
  FetchCsvResponse,
  HealthResponse,
  OddsResponse,
  RaceCacheResponse,
  RaceCacheUpsertResponse,
  RaceCharacteristicsResponse,
  RaceCourseStatsResponse,
  RaceEntryResponse,
  ResolveRaceIdResponse,
  SameDayRacesResponse,
  SameDaySheetResponse,
  SampleResponse,
  UpcomingRacesResponse,
  XAccountsResponse,
  XHorseAnalysisResponse,
  XSearchResponse,
  XSummaryResponse,
  YouTubeHorseAnalysisResponse,
  YouTubeSearchResponse,
  YouTubeSummaryResponse,
} from "./types";

const configuredApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";
const API_BASE_URL =
  configuredApiBaseUrl && !/localhost|127\.0\.0\.1/.test(configuredApiBaseUrl)
    ? configuredApiBaseUrl
    : "";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });

  if (!response.ok) {
    throw await buildApiError(response);
  }

  return (await response.json()) as T;
}

async function postJson<T>(path: string, body: object): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw await buildApiError(response);
  }

  return (await response.json()) as T;
}

async function buildApiError(response: Response): Promise<Error> {
  const prefix = `API request failed: ${response.status}`;
  try {
    const body = (await response.json()) as Record<string, unknown>;
    const detail = body?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return new Error(`${prefix} (${detail})`);
    }
    return new Error(prefix);
  } catch {
    try {
      const text = (await response.text()).trim();
      if (text) {
        return new Error(`${prefix} (${text.slice(0, 200)})`);
      }
    } catch {
      // no-op
    }
    return new Error(prefix);
  }
}

export function getHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>("/health");
}

export function getSample(): Promise<SampleResponse> {
  return fetchJson<SampleResponse>("/api/v1/sample");
}

export function getUpcomingRaces(
  monthsAhead = 2,
  daysAhead = 14,
  daysBack = 7,
): Promise<UpcomingRacesResponse> {
  return fetchJson<UpcomingRacesResponse>(
    `/api/v1/races/upcoming?months_ahead=${monthsAhead}&days_ahead=${daysAhead}&days_back=${daysBack}`,
  );
}

export function resolveRaceId(raceKey: string): Promise<ResolveRaceIdResponse> {
  return fetchJson<ResolveRaceIdResponse>(
    `/api/v1/races/resolve-id?race_key=${encodeURIComponent(raceKey)}`,
  );
}

export function fetchRaceCsv(raceId: string): Promise<FetchCsvResponse> {
  return postJson<FetchCsvResponse>("/api/v1/races/fetch-csv", { race_id: raceId });
}

export function getRaceOdds(raceId: string): Promise<OddsResponse> {
  return fetchJson<OddsResponse>(`/api/v1/races/${raceId}/odds`);
}

export function getSameDayRaces(date: string, venue?: string): Promise<SameDayRacesResponse> {
  const params = new URLSearchParams({ date });
  if (venue) params.set("venue", venue);
  return fetchJson<SameDayRacesResponse>(`/api/v1/races/same-day?${params.toString()}`);
}

export function getSameDaySheet(
  date: string,
  venue: string,
  budgetYen = 3000,
  refresh = false,
): Promise<SameDaySheetResponse> {
  const params = new URLSearchParams({ date, venue, budget_yen: String(budgetYen) });
  if (refresh) params.set("refresh", "true");
  return fetchJson<SameDaySheetResponse>(`/api/v1/races/same-day-sheet?${params.toString()}`);
}

export function getRaceEntry(raceId: string): Promise<RaceEntryResponse> {
  return fetchJson<RaceEntryResponse>(`/api/v1/races/${raceId}/entry`);
}

export function getRaceCourseStats(
  raceId: string,
  venue: string,
  distance: string,
  surface: string,
): Promise<RaceCourseStatsResponse> {
  const params = new URLSearchParams({ venue, distance, surface });
  return fetchJson<RaceCourseStatsResponse>(`/api/v1/races/${raceId}/course-stats?${params.toString()}`);
}

export function postRaceBetPlan(raceId: string, budgetYen = 3000): Promise<BetPlanResponse> {
  return postJson<BetPlanResponse>(`/api/v1/races/${raceId}/bet-plan`, { budget_yen: budgetYen });
}

export function getRaceCharacteristics(raceKey: string): Promise<RaceCharacteristicsResponse> {
  return fetchJson<RaceCharacteristicsResponse>(
    `/api/v1/races/characteristics?race_key=${encodeURIComponent(raceKey)}`,
  );
}

export function getRaceCache(raceKey: string): Promise<RaceCacheResponse> {
  return fetchJson<RaceCacheResponse>(`/api/v1/races/cache?race_key=${encodeURIComponent(raceKey)}`);
}

export function putRaceCache(raceKey: string, payload: Record<string, unknown>): Promise<RaceCacheUpsertResponse> {
  return postJson<RaceCacheUpsertResponse>(`/api/v1/races/cache?race_key=${encodeURIComponent(raceKey)}`, {
    payload,
  });
}

export function getExternalProviders(): Promise<ExternalProvidersResponse> {
  return fetchJson<ExternalProvidersResponse>("/api/v1/external/providers");
}

export function getXAccounts(): Promise<XAccountsResponse> {
  return fetchJson<XAccountsResponse>("/api/v1/external/x/accounts");
}

export function postYouTubeSearch(
  query: string,
  raceName: string,
  maxResults = 5,
): Promise<YouTubeSearchResponse> {
  return postJson<YouTubeSearchResponse>("/api/v1/external/youtube/search", {
    query,
    race_name: raceName,
    max_results: maxResults,
  });
}

export function postYouTubeSummary(
  query: string,
  raceName: string,
  maxResults = 5,
): Promise<YouTubeSummaryResponse> {
  return postJson<YouTubeSummaryResponse>("/api/v1/external/youtube/summary", {
    query,
    race_name: raceName,
    max_results: maxResults,
  });
}

export function postYouTubeHorseAnalysis(
  query: string,
  raceName: string,
  horseNames: string[],
  maxResults = 5,
): Promise<YouTubeHorseAnalysisResponse> {
  return postJson<YouTubeHorseAnalysisResponse>("/api/v1/external/youtube/horse-analysis", {
    query,
    race_name: raceName,
    horse_names: horseNames,
    max_results: maxResults,
  });
}

export function postXSearch(raceName: string, maxTweets = 30, sinceId?: string): Promise<XSearchResponse> {
  return postJson<XSearchResponse>("/api/v1/external/x/search", {
    race_name: raceName,
    max_tweets: maxTweets,
    since_id: sinceId ?? null,
  });
}

export function postXSummary(raceName: string, maxTweets = 30, sinceId?: string): Promise<XSummaryResponse> {
  return postJson<XSummaryResponse>("/api/v1/external/x/summary", {
    race_name: raceName,
    max_tweets: maxTweets,
    since_id: sinceId ?? null,
  });
}

export function postXHorseAnalysis(
  raceName: string,
  horseNames: string[],
  maxTweets = 30,
  sinceId?: string,
): Promise<XHorseAnalysisResponse> {
  return postJson<XHorseAnalysisResponse>("/api/v1/external/x/horse-analysis", {
    race_name: raceName,
    horse_names: horseNames,
    max_tweets: maxTweets,
    since_id: sinceId ?? null,
  });
}


