"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";

import { ExternalWorkbenchCard } from "@/components/mobile/external-workbench-card";
import {
  getRaceCourseStats,
  getRaceEntry,
  getSameDaySheet,
  getUpcomingRaces,
  postRaceBetPlan,
  resolveRaceId,
} from "@/lib/api/client";
import type {
  BetPlanResponse,
  EntryHorse,
  ExternalSnapshot,
  RaceCourseStatsResponse,
  RaceEntryResponse,
  RecentRunDetail,
  SameDaySheetRace,
  UpcomingRace,
} from "@/lib/api/types";

type TabKey = "entry" | "features" | "bet" | "external";

type RaceMeta = {
  race_key: string;
  race_id: string | null;
  race_name: string;
  race_number: string;
  date_iso: string;
  date_str: string;
  venue: string;
  distance: string;
  surface: string;
  grade: string;
};

type RaceDetailCachePayload = {
  savedAt: string;
  race: RaceMeta;
  entry: RaceEntryResponse | null;
  courseStats: RaceCourseStatsResponse | null;
  betPlan: BetPlanResponse | null;
  externalSnapshot?: ExternalSnapshot | null;
};

const DETAIL_CACHE_PREFIX = "keiba:same-day:race-detail:";
const DETAIL_CACHE_EVENT = "keiba:same-day-detail-cache-updated";
const DETAIL_CACHE_TTL_DAYS = 7;

function statusText(loading: boolean, error: string | null): string {
  if (loading) return "取得中...";
  if (error) return error;
  return "";
}

function formatOdds(value: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "未公開";
  return value.toFixed(1);
}

function formatCandidateIndex(value: number): string {
  if (!Number.isFinite(value)) return "-";
  return `${Math.round(value * 100)}`;
}

const WAKU_BADGE_CLASS: Record<string, string> = {
  "1": "border-slate-400 bg-white text-slate-950",
  "2": "border-slate-950 bg-slate-950 text-white",
  "3": "border-red-600 bg-red-600 text-white",
  "4": "border-blue-600 bg-blue-600 text-white",
  "5": "border-yellow-400 bg-yellow-300 text-slate-950",
  "6": "border-emerald-600 bg-emerald-600 text-white",
  "7": "border-orange-500 bg-orange-500 text-white",
  "8": "border-pink-400 bg-pink-300 text-slate-950",
};

const WAKU_BORDER_CLASS: Record<string, string> = {
  "1": "border-l-slate-300",
  "2": "border-l-slate-950",
  "3": "border-l-red-600",
  "4": "border-l-blue-600",
  "5": "border-l-yellow-400",
  "6": "border-l-emerald-600",
  "7": "border-l-orange-500",
  "8": "border-l-pink-400",
};

function wakuNumber(value: string): string {
  const match = String(value || "").match(/\d+/);
  return match?.[0] ?? "";
}

function wakuBadgeClass(value: string): string {
  return WAKU_BADGE_CLASS[wakuNumber(value)] ?? "border-slate-300 bg-slate-100 text-slate-700";
}

function wakuBorderClass(value: string): string {
  return WAKU_BORDER_CLASS[wakuNumber(value)] ?? "border-l-slate-200";
}

function metaFromQuery(raceKey: string, searchParams: URLSearchParams): RaceMeta {
  return {
    race_key: raceKey,
    race_id: searchParams.get("race_id") || null,
    race_name: searchParams.get("race_name") || "レース",
    race_number: searchParams.get("race_number") || "",
    date_iso: searchParams.get("date") || "",
    date_str: searchParams.get("date") || "",
    venue: searchParams.get("venue") || "",
    distance: searchParams.get("distance") || "",
    surface: searchParams.get("surface") || "",
    grade: searchParams.get("grade") || "平場",
  };
}

function metaFromUpcoming(race: UpcomingRace): RaceMeta {
  return {
    race_key: race.race_key,
    race_id: race.race_id,
    race_name: race.race_name,
    race_number: race.race_number ?? "",
    date_iso: race.date_iso,
    date_str: race.date_str,
    venue: race.venue,
    distance: race.distance,
    surface: race.surface,
    grade: race.grade,
  };
}

function sameDaySheetHref(meta: RaceMeta | null, searchParams: URLSearchParams): string {
  const date = meta?.date_iso || searchParams.get("date") || "";
  const venue = meta?.venue || searchParams.get("venue") || "";
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (venue) params.set("venue", venue);
  const query = params.toString();
  return `/same-day-sheet${query ? `?${query}` : ""}`;
}

function detailCacheKey(meta: RaceMeta, raceKey: string): string {
  return `${DETAIL_CACHE_PREFIX}${meta.race_id || raceKey}`;
}

function readDetailCache(meta: RaceMeta, raceKey: string): RaceDetailCachePayload | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(detailCacheKey(meta, raceKey));
    if (!raw) return null;
    const payload = JSON.parse(raw) as RaceDetailCachePayload;
    if (!payload || !payload.race || !payload.entry) return null;
    if (!entryHasRecentRunDetailShape(payload.entry)) return null;
    return payload;
  } catch {
    return null;
  }
}

function writeDetailCache(meta: RaceMeta, payload: Omit<RaceDetailCachePayload, "savedAt">): string | null {
  if (typeof window === "undefined") return null;
  const savedAt = new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  try {
    window.localStorage.setItem(
      detailCacheKey(meta, meta.race_key),
      JSON.stringify({ ...payload, savedAt }),
    );
    window.dispatchEvent(new Event(DETAIL_CACHE_EVENT));
    return savedAt;
  } catch {
    return null;
  }
}

function cleanupOldDetailCaches(): void {
  if (typeof window === "undefined") return;
  const ttlMs = DETAIL_CACHE_TTL_DAYS * 24 * 60 * 60 * 1000;
  const now = Date.now();
  try {
    Object.keys(window.localStorage)
      .filter((key) => key.startsWith(DETAIL_CACHE_PREFIX))
      .forEach((key) => {
        const raw = window.localStorage.getItem(key);
        if (!raw) return;
        try {
          const payload = JSON.parse(raw) as RaceDetailCachePayload;
          const raceDateMs = payload?.race?.date_iso ? new Date(`${payload.race.date_iso}T00:00:00+09:00`).getTime() : Number.NaN;
          if (Number.isFinite(raceDateMs) && now - raceDateMs > ttlMs) {
            window.localStorage.removeItem(key);
          }
        } catch {
          window.localStorage.removeItem(key);
        }
      });
  } catch {
    // localStorage may be unavailable in private mode; keep the detail page usable.
  }
}

function detailPayloadFromSheetItem(item: SameDaySheetRace): Omit<RaceDetailCachePayload, "savedAt"> {
  const meta = metaFromUpcoming(item.race);
  return {
    race: meta,
    entry: item.entry,
    courseStats: item.course_stats,
    betPlan: item.bet_plan,
    externalSnapshot: null,
  };
}

async function readDetailFromSheetCache(meta: RaceMeta, raceKey: string): Promise<Omit<RaceDetailCachePayload, "savedAt"> | null> {
  if (!meta.date_iso || !meta.venue) return null;
  try {
    const sheet = await getSameDaySheet(meta.date_iso, meta.venue, 3000, false);
    const item = sheet.races.find((candidate) => {
      const candidateRace = candidate.race;
      return (
        (meta.race_id && candidateRace.race_id === meta.race_id) ||
        candidateRace.race_key === raceKey ||
        candidateRace.race_key === meta.race_key
      );
    });
    if (!item || !item.entry) return null;
    if (!entryHasRecentRunDetailShape(item.entry)) return null;
    return detailPayloadFromSheetItem(item);
  } catch {
    return null;
  }
}

function entryHasRecentRunDetailShape(entry: RaceEntryResponse): boolean {
  if (!entry.horses.length) return true;
  return entry.horses.every(
    (horse) =>
      Array.isArray(horse.recent_run_details) &&
      horse.recent_run_details.every((detail) => "race_eval" in detail),
  );
}

function mdCell(value: unknown): string {
  const text = value == null || value === "" ? "-" : String(value);
  return text.replace(/\|/g, "/").replace(/\r?\n/g, " ").trim() || "-";
}

function mdText(value: unknown, fallback = "未取得"): string {
  const text = value == null ? "" : String(value).trim();
  return text || fallback;
}

function trackTextFromEntry(entry: RaceEntryResponse | null): string {
  const direct = Object.entries(entry?.track_conditions ?? {})
    .map(([key, value]) => `${key}:${value}`)
    .join(" / ");
  if (direct) return direct;
  const raceData = entry?.race_data01 ?? "";
  const match = raceData.match(/馬場\s*[:：]\s*([^\s/]+)/);
  return match?.[1] ?? "";
}

function formatRunDetail(detail?: RecentRunDetail): string {
  if (!detail) return "詳細未取得";
  const evalText =
    detail.time_index != null
      ? `指数${detail.time_index} ${detail.race_eval || detail.race_level || ""}`.trim()
      : detail.race_eval
        ? `評価 ${detail.race_eval}`
        : "";
  const parts = [
    detail.venue ? `場所 ${detail.venue}` : "",
    detail.race_time ? `走破タイム ${detail.race_time}` : "",
    evalText,
    detail.margin ? `着差${detail.margin}` : "",
    detail.last3f ? `上り${detail.last3f}` : "",
    detail.corner ? `通過${detail.corner}` : "",
    detail.field_size ? `${detail.field_size}頭` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" / ") : "詳細未取得";
}

function buildRaceResearchMarkdown({
  race,
  entry,
  courseStats,
  betPlan,
  externalSnapshot,
}: {
  race: RaceMeta | null;
  entry: RaceEntryResponse | null;
  courseStats: RaceCourseStatsResponse | null;
  betPlan: BetPlanResponse | null;
  externalSnapshot: ExternalSnapshot | null;
}): string {
  const lines: string[] = [];
  const title = `${race?.race_number ? `${race.race_number} ` : ""}${race?.race_name || "レース詳細"}`;

  lines.push("# AI共有用レース分析資料");
  lines.push("");
  lines.push("## レース情報");
  lines.push(`- レース: ${mdText(title)}`);
  lines.push(`- 日付: ${mdText(race?.date_str || race?.date_iso)}`);
  lines.push(`- 会場: ${mdText(race?.venue)}`);
  lines.push(`- 条件: ${mdText(`${race?.surface || ""}${race?.distance || ""}`)}`);
  lines.push(`- グレード: ${mdText(race?.grade)}`);
  lines.push(`- 発走: ${mdText(entry?.start_time)}`);
  lines.push(`- 天気: ${mdText(entry?.weather)}`);
  lines.push(`- 馬場: ${mdText(trackTextFromEntry(entry))}`);
  lines.push("");

  lines.push("## 出馬表");
  if (entry?.horses.length) {
    lines.push("| 枠 | 馬番 | 馬名 | 騎手 | 単勝 | 脚質 | 斤量 | 馬体重 |");
    lines.push("|---|---:|---|---|---:|---|---:|---|");
    entry.horses.forEach((horse) => {
      lines.push(
        `| ${mdCell(horse.waku)} | ${mdCell(horse.umaban)} | ${mdCell(horse.horse_name)} | ${mdCell(horse.jockey)} | ${mdCell(formatOdds(horse.odds))} | ${mdCell(horse.style)} | ${mdCell(horse.weight)} | ${mdCell(`${horse.body_weight || "-"}${horse.body_delta ? ` (${horse.body_delta})` : ""}`)} |`,
      );
    });
  } else {
    lines.push("未取得");
  }
  lines.push("");

  lines.push("## 近3走・指数");
  if (entry?.horses.length) {
    entry.horses.forEach((horse) => {
      lines.push(`### ${mdText(horse.umaban, "-")} ${mdText(horse.horse_name)}`);
      const runs = horse.recent_runs.length ? horse.recent_runs : ["", "", ""];
      runs.slice(0, 3).forEach((run, idx) => {
        const label = idx === 0 ? "前走" : `${idx + 1}走前`;
        lines.push(`- ${label}: ${mdText(run)} / ${formatRunDetail(horse.recent_run_details?.[idx])}`);
      });
      lines.push("");
    });
  } else {
    lines.push("未取得");
    lines.push("");
  }

  lines.push("## コース特徴");
  if (courseStats) {
    lines.push(`- コース要約: ${mdText(courseStats.summary.course)}`);
    lines.push(`- 脚質傾向: ${mdText(courseStats.summary.winning_type)}`);
    lines.push(`- ペース傾向: ${mdText(courseStats.summary.pace_note || courseStats.pace_tendency)}`);
    lines.push(`- 参照レース数: ${mdText(courseStats.sample_race_count)}`);
    lines.push("");
    lines.push("### 枠別成績");
    lines.push("| 枠 | 1着率 | 複勝率 | 圏外率 | 頭数 |");
    lines.push("|---|---:|---:|---:|---:|");
    courseStats.frame_stats.forEach((row) => {
      lines.push(
        `| ${mdCell(row.label)} | ${mdCell(row.win_rate)}% | ${mdCell(row.top3_rate)}% | ${mdCell(row.outside_top3_rate)}% | ${mdCell(row.starts)} |`,
      );
    });
  } else {
    lines.push("未取得");
  }
  lines.push("");

  lines.push("## 候補馬ランキング");
  if (betPlan?.ranking.length) {
    lines.push("| 順位 | 馬番 | 馬名 | 単勝 | 脚質 | 候補指数 | 理由 |");
    lines.push("|---:|---:|---|---:|---|---:|---|");
    betPlan.ranking.forEach((item, idx) => {
      lines.push(
        `| ${idx + 1} | ${mdCell(item.umaban)} | ${mdCell(item.horse_name)} | ${mdCell(formatOdds(item.odds))} | ${mdCell(item.style)} | ${mdCell(formatCandidateIndex(item.score))} | ${mdCell(item.reason)} |`,
      );
    });
  } else {
    lines.push("未取得");
  }
  lines.push("");

  lines.push("## 買い目");
  if (betPlan?.tickets.length) {
    lines.push(`- 予算: ${betPlan.budget_yen.toLocaleString("ja-JP")}円`);
    lines.push(`- 暫定表示: ${betPlan.provisional_only ? "はい" : "いいえ"}`);
    lines.push("| 券種 | 買い目 | 金額 | 理由 |");
    lines.push("|---|---|---:|---|");
    betPlan.tickets.forEach((ticket) => {
      lines.push(`| ${mdCell(ticket.type)} | ${mdCell(ticket.selection)} | ${mdCell(`${ticket.amount_yen}円`)} | ${mdCell(ticket.reason)} |`);
    });
  } else {
    lines.push("未取得");
  }
  if (betPlan?.warnings.length) {
    lines.push("");
    lines.push("### 買い目生成時の警告");
    betPlan.warnings.forEach((warning) => lines.push(`- ${warning}`));
  }
  lines.push("");

  lines.push("## 外部情報");
  lines.push("### YouTube");
  if (externalSnapshot?.youtubeSummary || externalSnapshot?.youtubeHorseAnalysis) {
    if (externalSnapshot.youtubeSummary) {
      lines.push(`- 検索語: ${mdText(externalSnapshot.youtubeSummary.query)}`);
      lines.push(`- 要約: ${mdText(externalSnapshot.youtubeSummary.summary)}`);
      lines.push("- 取得動画:");
      externalSnapshot.youtubeSummary.videos.forEach((video) => {
        lines.push(`  - ${video.title} / ${video.channel_title} / ${video.video_url}`);
      });
    }
    if (externalSnapshot.youtubeHorseAnalysis?.video_conclusions.length) {
      lines.push("");
      lines.push("#### 動画ごとの結論");
      externalSnapshot.youtubeHorseAnalysis.video_conclusions.forEach((item) => {
        lines.push(`- ${mdText(item.video_title)}: 本命=${mdText(item.head_pick, "-")} / 対抗=${mdText(item.second_pick, "-")} / 単穴=${mdText(item.dark_horse, "-")} / 危険=${mdText(item.danger_horse, "-")} / ${mdText(item.bet_strategy, "-")}`);
      });
    }
    if (externalSnapshot.youtubeHorseAnalysis?.analysis_items.length) {
      lines.push("");
      lines.push("#### 馬別分析");
      externalSnapshot.youtubeHorseAnalysis.analysis_items.forEach((item) => {
        lines.push(`- ${mdText(item.horse)}: + ${mdText(item.plus, "-")} / - ${mdText(item.minus, "-")} / ${mdText(item.source_title, "-")} ${mdText(item.source_url, "")}`);
      });
    }
  } else {
    lines.push("未取得");
  }
  lines.push("");

  lines.push("### X");
  if (externalSnapshot?.xSummary || externalSnapshot?.xHorseAnalysis) {
    if (externalSnapshot.xSummary) {
      lines.push(`- 要約: ${mdText(externalSnapshot.xSummary.summary)}`);
      lines.push(`- 取得ツイート: ${externalSnapshot.xSummary.tweets.length}件 / 除外 ${externalSnapshot.xSummary.dropped_count}件`);
      externalSnapshot.xSummary.tweets.slice(0, 10).forEach((tweet) => {
        lines.push(`  - @${tweet.author_username}: ${tweet.text.replace(/\r?\n/g, " ")} ${tweet.url}`);
      });
    }
    if (externalSnapshot.xHorseAnalysis?.analysis_items.length) {
      lines.push("");
      lines.push("#### 馬別分析");
      externalSnapshot.xHorseAnalysis.analysis_items.forEach((item) => {
        lines.push(`- ${mdText(item.horse)}: + ${mdText(item.plus, "-")} / - ${mdText(item.minus, "-")} / ${mdText(item.source_title, "-")} ${mdText(item.source_url, "")}`);
      });
    }
  } else {
    lines.push("未取得");
  }
  lines.push("");

  lines.push("### Web");
  lines.push(externalSnapshot?.webSummary || "未取得");
  lines.push("");
  lines.push("---");
  lines.push("注: この資料はアプリ内で取得済みの情報をAI分析へ渡すためのコピー用Markdownです。");

  return lines.join("\n");
}

export default function RaceDetailPage() {
  const params = useParams<{ raceKey: string }>();
  const searchParams = useSearchParams();
  const raceKey = decodeURIComponent(params.raceKey ?? "");
  const [race, setRace] = useState<RaceMeta | null>(null);
  const [entry, setEntry] = useState<RaceEntryResponse | null>(null);
  const [courseStats, setCourseStats] = useState<RaceCourseStatsResponse | null>(null);
  const [betPlan, setBetPlan] = useState<BetPlanResponse | null>(null);
  const [externalSnapshot, setExternalSnapshot] = useState<ExternalSnapshot | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("entry");
  const [reportOpen, setReportOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cacheSavedAt, setCacheSavedAt] = useState<string | null>(null);
  const [loadedFromCache, setLoadedFromCache] = useState(false);

  const status = statusText(loading || refreshing, error);
  const horseNames = useMemo(() => entry?.horses.map((horse) => horse.horse_name).filter(Boolean) ?? [], [entry]);
  const researchMarkdown = useMemo(
    () => buildRaceResearchMarkdown({ race, entry, courseStats, betPlan, externalSnapshot }),
    [race, entry, courseStats, betPlan, externalSnapshot],
  );

  const handleExternalSnapshotChange = useCallback(
    (snapshot: ExternalSnapshot) => {
      setExternalSnapshot(snapshot);
      if (!race || !entry) return;
      const savedAt = writeDetailCache(race, {
        race,
        entry,
        courseStats,
        betPlan,
        externalSnapshot: snapshot,
      });
      if (savedAt) {
        setCacheSavedAt(savedAt);
      }
    },
    [race, entry, courseStats, betPlan],
  );

  async function loadAll(forceRefresh = false) {
    const meta = race ?? metaFromQuery(raceKey, searchParams);
    if (forceRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      let resolvedMeta = meta;
      if (!forceRefresh) {
        const cached = readDetailCache(resolvedMeta, raceKey);
        if (cached) {
          setRace(cached.race);
          setEntry(cached.entry);
          setCourseStats(cached.courseStats);
          setBetPlan(cached.betPlan);
          setExternalSnapshot(cached.externalSnapshot ?? null);
          setCacheSavedAt(cached.savedAt);
          setLoadedFromCache(true);
          setLoading(false);
          setRefreshing(false);
          return;
        }
        const sheetCached = await readDetailFromSheetCache(resolvedMeta, raceKey);
        if (sheetCached) {
          setRace(sheetCached.race);
          setEntry(sheetCached.entry);
          setCourseStats(sheetCached.courseStats);
          setBetPlan(sheetCached.betPlan);
          setExternalSnapshot(sheetCached.externalSnapshot ?? null);
          const savedAt = writeDetailCache(sheetCached.race, sheetCached);
          setCacheSavedAt(savedAt);
          setLoadedFromCache(true);
          setLoading(false);
          setRefreshing(false);
          return;
        }
      }
      if (!resolvedMeta.race_id) {
        const resolved = await resolveRaceId(raceKey);
        resolvedMeta = { ...resolvedMeta, race_id: resolved.race_id };
      }
      if (!forceRefresh) {
        const cached = readDetailCache(resolvedMeta, raceKey);
        if (cached) {
          setRace(cached.race);
          setEntry(cached.entry);
          setCourseStats(cached.courseStats);
          setBetPlan(cached.betPlan);
          setExternalSnapshot(cached.externalSnapshot ?? null);
          setCacheSavedAt(cached.savedAt);
          setLoadedFromCache(true);
          setLoading(false);
          setRefreshing(false);
          return;
        }
        const sheetCached = await readDetailFromSheetCache(resolvedMeta, raceKey);
        if (sheetCached) {
          setRace(sheetCached.race);
          setEntry(sheetCached.entry);
          setCourseStats(sheetCached.courseStats);
          setBetPlan(sheetCached.betPlan);
          setExternalSnapshot(sheetCached.externalSnapshot ?? null);
          const savedAt = writeDetailCache(sheetCached.race, sheetCached);
          setCacheSavedAt(savedAt);
          setLoadedFromCache(true);
          setLoading(false);
          setRefreshing(false);
          return;
        }
      }
      if (!resolvedMeta.race_id) {
        throw new Error("race_id未解決です。レース一覧を再取得してください。");
      }
      setRace(resolvedMeta);

      const entryResponse = await getRaceEntry(resolvedMeta.race_id);
      setEntry(entryResponse);

      let courseStatsResponse: RaceCourseStatsResponse | null = null;
      if (resolvedMeta.venue && resolvedMeta.distance && resolvedMeta.surface) {
        courseStatsResponse = await getRaceCourseStats(
          resolvedMeta.race_id,
          resolvedMeta.venue,
          resolvedMeta.distance,
          resolvedMeta.surface,
        );
        setCourseStats(courseStatsResponse);
      }

      const betResponse = await postRaceBetPlan(resolvedMeta.race_id);
      setBetPlan(betResponse);
      const savedAt = writeDetailCache(resolvedMeta, {
        race: resolvedMeta,
        entry: entryResponse,
        courseStats: courseStatsResponse,
        betPlan: betResponse,
        externalSnapshot,
      });
      setCacheSavedAt(savedAt);
      setLoadedFromCache(false);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "レース情報の取得に失敗しました");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    cleanupOldDetailCaches();
    let mounted = true;
    async function init() {
      setLoading(true);
      setError(null);
      const queryMeta = metaFromQuery(raceKey, searchParams);
      if (queryMeta.race_id && queryMeta.venue) {
        if (mounted) setRace(queryMeta);
        return;
      }
      try {
        const upcoming = await getUpcomingRaces(2, 120, 30);
        const found = upcoming.races.find((item) => item.race_key === raceKey);
        if (mounted) {
          setRace(found ? metaFromUpcoming(found) : queryMeta);
        }
      } catch {
        if (mounted) setRace(queryMeta);
      }
    }
    void init().then(() => {
      if (mounted) void loadAll(false);
    });
    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raceKey]);

  const heroTitle = useMemo(() => {
    if (!race) return "レース詳細";
    const number = race.race_number ? `${race.race_number} ` : "";
    return `${number}${race.race_name}`;
  }, [race]);

  return (
    <main className="mx-auto min-h-screen w-full max-w-md px-4 pb-10 pt-6">
      <div className="flex flex-wrap gap-2">
        <Link
          href={sameDaySheetHref(race, searchParams)}
          className="min-h-11 rounded-xl bg-slate-900 px-3 py-3 text-xs font-black text-white"
        >
          全R一覧へ戻る
        </Link>
        <Link href="/" className="min-h-11 rounded-xl border border-slate-300 bg-white px-3 py-3 text-xs font-semibold text-slate-700">
          トップへ戻る
        </Link>
        <button
          type="button"
          onClick={() => setReportOpen((current) => !current)}
          className="min-h-11 rounded-xl border border-emerald-300 bg-emerald-50 px-3 py-3 text-xs font-black text-emerald-800"
        >
          AI共有用Markdown
        </button>
      </div>

      <section className="mt-3 overflow-hidden rounded-3xl bg-slate-950 text-white shadow-lg">
        <div className="bg-[radial-gradient(circle_at_20%_20%,rgba(16,185,129,.45),transparent_30%),linear-gradient(135deg,#0f172a,#1e293b)] p-5">
          <p className="text-xs font-bold text-emerald-200">当日レースモード</p>
          <h1 className="mt-2 text-2xl font-black tracking-tight">{heroTitle}</h1>
          <p className="mt-2 text-sm text-slate-200">
            {race?.date_str || race?.date_iso || "-"} / {race?.venue || "-"} / {race?.surface || ""}
            {race?.distance || ""}
          </p>
          {entry?.start_time ? <p className="mt-1 text-sm font-bold text-emerald-200">発走 {entry.start_time}</p> : null}
          {status ? <p className={`mt-3 rounded-xl px-3 py-2 text-xs ${error ? "bg-rose-500/20 text-rose-100" : "bg-white/10 text-slate-100"}`}>{status}</p> : null}
          {cacheSavedAt ? (
            <p className="mt-3 rounded-xl bg-white/10 px-3 py-2 text-xs text-slate-100">
              {loadedFromCache ? "保存済みデータを即表示中" : "このレース情報を端末に保存済み"} / {cacheSavedAt}
            </p>
          ) : null}
          <button
            type="button"
            onClick={() => {
              void loadAll(true);
            }}
            disabled={loading || refreshing}
            className="mt-4 min-h-12 w-full rounded-2xl bg-emerald-500 px-4 py-3 text-sm font-black text-slate-950 shadow-sm shadow-emerald-200 disabled:opacity-60"
          >
            {refreshing ? "更新中..." : "最新オッズ・基本情報を取得"}
          </button>
          {refreshing ? (
            <p className="mt-2 rounded-xl bg-emerald-400/15 px-3 py-2 text-xs font-bold text-emerald-100">
              ?????????????????????????????
            </p>
          ) : null}
          {error ? (
            <p className="mt-2 rounded-xl bg-rose-500/20 px-3 py-2 text-xs font-bold text-rose-100">
              ???????????????????????????????????????????
            </p>
          ) : null}
        </div>
      </section>

      {reportOpen ? <ResearchMarkdownPanel markdown={researchMarkdown} /> : null}

      {entry?.warnings.length ? (
        <div className="mt-3 space-y-2">
          {entry.warnings.map((warning) => (
            <p key={warning} className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {warning}
            </p>
          ))}
        </div>
      ) : null}

      <div className="sticky top-0 z-10 mt-4 grid grid-cols-4 gap-1 rounded-2xl bg-white p-1 shadow-sm ring-1 ring-slate-200">
        {[
          ["entry", "出馬表"],
          ["features", "特徴"],
          ["bet", "買い目"],
          ["external", "外部情報"],
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setActiveTab(key as TabKey)}
            className={`min-h-11 rounded-xl px-2 py-3 text-xs font-bold ${
              activeTab === key ? "bg-slate-900 text-white" : "text-slate-600"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === "entry" ? <EntryTab entry={entry} /> : null}
      {activeTab === "features" ? <FeaturesTab courseStats={courseStats} /> : null}
      {activeTab === "bet" ? <BetTab betPlan={betPlan} /> : null}
      {activeTab === "external" ? (
        <ExternalTab
          race={race}
          horseNames={horseNames}
          externalSnapshot={externalSnapshot}
          onExternalSnapshotChange={handleExternalSnapshotChange}
        />
      ) : null}
    </main>
  );
}

function ResearchMarkdownPanel({ markdown }: { markdown: string }) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopyStatus("コピーしました");
    } catch {
      textareaRef.current?.focus();
      textareaRef.current?.select();
      setCopyStatus("自動コピーできませんでした。本文を選択してコピーしてください。");
    }
  }

  return (
    <section className="mt-3 rounded-3xl border border-emerald-200 bg-emerald-50 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-black text-emerald-950">AI共有用Markdown</p>
          <p className="mt-1 text-xs text-emerald-800">
            ChatGPT/GeminiのDeep Researchへ貼り付けるための整理済み資料です。
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            void handleCopy();
          }}
          className="min-h-11 shrink-0 rounded-xl bg-emerald-600 px-3 py-2 text-xs font-black text-white"
        >
          コピーする
        </button>
      </div>
      {copyStatus ? <p className="mt-2 rounded-xl bg-white/70 px-3 py-2 text-xs text-emerald-900">{copyStatus}</p> : null}
      <textarea
        ref={textareaRef}
        readOnly
        value={markdown}
        rows={14}
        className="mt-3 w-full rounded-2xl border border-emerald-200 bg-white p-3 font-mono text-xs leading-5 text-slate-800"
      />
    </section>
  );
}

function EntryTab({ entry }: { entry: RaceEntryResponse | null }) {
  if (!entry) {
    return <EmptyCard message="出馬表を取得中です。" />;
  }
  return (
    <section className="mt-3 space-y-3">
      <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p className="text-xs font-semibold text-slate-500">脚質分布</p>
        <p className="mt-1 text-lg font-black text-slate-900">{entry.style_distribution_label || "-"}</p>
        <p className="mt-1 text-xs text-slate-500">{entry.race_data01}</p>
      </div>
      {entry.horses.map((horse) => (
        <HorseCard key={`${horse.umaban || horse.horse_name}-${horse.horse_name}`} horse={horse} />
      ))}
    </section>
  );
}

function HorseCard({ horse }: { horse: EntryHorse }) {
  return (
    <article className={`rounded-3xl border border-l-8 border-slate-200 bg-white p-4 shadow-sm ${wakuBorderClass(horse.waku)}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500">
            <span className={`inline-flex min-w-8 items-center justify-center rounded-full border px-2 py-1 font-black ${wakuBadgeClass(horse.waku)}`}>
              {horse.waku || "-"}枠
            </span>
            <span>{horse.umaban || "-"}番 / {horse.jockey || "-"}</span>
          </p>
          <h2 className="mt-1 text-lg font-black text-slate-950">{horse.horse_name}</h2>
          <p className="mt-1 text-xs text-slate-500">
            {horse.sex_age || "-"} / 斤量 {horse.weight || "-"} / 馬体重 {horse.body_weight || "-"}
            {horse.body_delta ? ` (${horse.body_delta})` : ""}
          </p>
        </div>
        <div className="text-right">
          <p className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-black text-emerald-700">{horse.style || "-"}</p>
          <p className="mt-2 text-lg font-black text-slate-900">{formatOdds(horse.odds)}</p>
          <p className="text-[10px] text-slate-500">単勝</p>
        </div>
      </div>
      <div className="mt-3 space-y-2">
        {horse.recent_runs.map((run, idx) => (
          <RecentRunLine
            key={`${horse.horse_name}-run-${idx}`}
            label={idx === 0 ? "前走" : `${idx + 1}走前`}
            run={run}
            last3f={horse.last3fs[idx]}
            detail={horse.recent_run_details?.[idx]}
          />
        ))}
      </div>
    </article>
  );
}

function raceLevelColor(level: string): string {
  switch (level) {
    case "S":
    case "G1":
      return "bg-purple-100 text-purple-800";
    case "A":
    case "G2":
      return "bg-blue-100 text-blue-800";
    case "B":
    case "G3":
      return "bg-emerald-50 text-emerald-700";
    case "C":
    case "L":
    case "OP":
      return "bg-yellow-50 text-yellow-700";
    case "D":
      return "bg-slate-100 text-slate-500";
    default:
      return "bg-slate-100 text-slate-400";
  }
}

function RecentRunLine({
  label,
  run,
  last3f,
  detail,
}: {
  label: string;
  run: string;
  last3f?: string;
  detail?: RecentRunDetail;
}) {
  const text = run || "-";
  const match = text.match(/^(\d{2}\/\d{2}\/\d{2})\s+(\d{1,2})\s+(.+)$/);
  const evalText =
    detail?.time_index != null
      ? `指数${detail.time_index} ${detail.race_eval || detail.race_level || ""}`.trim()
      : detail?.race_eval
        ? `評価${detail.race_eval}`
        : "";
  const evalLevel = detail?.race_eval || detail?.race_level || "";
  const hasDetailChips = Boolean(detail?.venue || detail?.race_time || evalText || detail?.margin);
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-700">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <span className="font-bold text-slate-900">{label}</span>
        {match ? (
          <>
            <span className="text-slate-500">{match[1]}</span>
            <span className="rounded-full bg-slate-900 px-2 py-0.5 text-[11px] font-black text-white">
              {match[2]}着
            </span>
          </>
        ) : null}
        {last3f ? <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-bold text-emerald-700">上り {last3f}</span> : null}
      </div>
      {hasDetailChips ? (
        <div className="mb-1 flex flex-wrap gap-1">
          {detail?.venue ? (
            <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-bold text-indigo-700">
              {detail.venue}
            </span>
          ) : null}
          {detail?.race_time ? (
            <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-bold text-slate-700 ring-1 ring-slate-200">
              {detail.race_time}
            </span>
          ) : null}
          {evalText ? (
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-black ${raceLevelColor(evalLevel)}`}>
              {evalText}
            </span>
          ) : null}
          {detail?.margin ? (
            <span className="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-bold text-sky-700">
              着差{detail.margin}
            </span>
          ) : null}
        </div>
      ) : null}
      <p>{match ? match[3] : text}</p>
    </div>
  );
}

function FeaturesTab({ courseStats }: { courseStats: RaceCourseStatsResponse | null }) {
  if (!courseStats) {
    return <EmptyCard message="レース特徴を取得中です。" />;
  }
  return (
    <section className="mt-3 space-y-3">
      <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p className="text-xs font-semibold text-slate-500">コース特徴</p>
        <p className="mt-1 text-sm font-semibold text-slate-900">{courseStats.summary.course}</p>
        <p className="mt-2 rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {courseStats.summary.winning_type || "脚質データ不足"}
        </p>
        <p className="mt-2 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {courseStats.summary.pace_note}
        </p>
      </div>
      <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p className="text-sm font-black text-slate-900">枠別成績割合</p>
        <div className="mt-3 space-y-2">
          {courseStats.frame_stats.map((row) => (
            <div key={String(row.label)} className="grid grid-cols-5 gap-1 rounded-xl bg-slate-50 px-2 py-2 text-center text-[11px] text-slate-700">
              <span className="font-black text-slate-900">{String(row.label ?? "-")}</span>
              <span>1着 {String(row.win_rate ?? "0")}%</span>
              <span>複勝 {String(row.top3_rate ?? "0")}%</span>
              <span>外 {String(row.outside_top3_rate ?? "0")}%</span>
              <span>{String(row.starts ?? "0")}頭</span>
            </div>
          ))}
        </div>
      </div>
      {courseStats.source_url ? (
        <a
          href={courseStats.source_url}
          className="block rounded-2xl border border-slate-300 bg-white px-4 py-3 text-center text-sm font-bold text-slate-700"
          target="_blank"
          rel="noreferrer"
        >
          netkeiba参照元を開く
        </a>
      ) : null}
    </section>
  );
}

function BetTab({ betPlan }: { betPlan: BetPlanResponse | null }) {
  if (!betPlan) {
    return <EmptyCard message="買い目候補を取得中です。" />;
  }
  return (
    <section className="mt-3 space-y-3">
      {betPlan.provisional_only ? (
        <p className="rounded-2xl bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-800">
          馬番/枠番が未確定のため、正式な買い目ではなく暫定候補ランキングを表示しています。
        </p>
      ) : null}
      {betPlan.warnings.map((warning) => (
        <p key={warning} className="rounded-xl bg-slate-100 px-3 py-2 text-xs text-slate-700">
          {warning}
        </p>
      ))}
      <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p className="text-sm font-black text-slate-900">候補馬ランキング</p>
        <div className="mt-3 space-y-2">
          {betPlan.ranking.slice(0, 8).map((item, idx) => (
            <div key={`${item.horse_name}-${idx}`} className="flex items-center justify-between rounded-xl bg-slate-50 px-3 py-2">
              <div>
                <p className="text-sm font-black text-slate-900">
                  {idx + 1}. {item.horse_name}
                </p>
                <p className="text-xs text-slate-500">
                  {item.umaban || "-"}番 / {item.style || "-"} / {item.reason}
                </p>
              </div>
              <div className="shrink-0 text-right">
                <p className="text-sm font-black text-emerald-700">{formatCandidateIndex(item.score)}</p>
                <p className="text-[10px] font-bold text-slate-400">候補指数</p>
              </div>
            </div>
          ))}
        </div>
      </div>
      {!betPlan.provisional_only && betPlan.tickets.length > 0 ? (
        <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
          <p className="text-sm font-black text-slate-900">正式買い目</p>
          <div className="mt-3 space-y-2">
            {betPlan.tickets.map((ticket, idx) => (
              <div key={`${ticket.type}-${ticket.selection}-${idx}`} className="rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
                <span className="font-black">{ticket.type}</span> {ticket.selection} / {ticket.amount_yen}円
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ExternalTab({
  race,
  horseNames,
  externalSnapshot,
  onExternalSnapshotChange,
}: {
  race: RaceMeta | null;
  horseNames: string[];
  externalSnapshot: ExternalSnapshot | null;
  onExternalSnapshotChange: (snapshot: ExternalSnapshot) => void;
}) {
  return (
    <section className="mt-3 space-y-3">
      <p className="rounded-2xl bg-sky-50 px-4 py-3 text-sm text-sky-800">
        当日モードではYouTube/X/Web検索は自動実行しません。必要な場合だけ手動で実行してください。
        検索語には「{race?.date_iso || "日付"} {race?.venue || "会場"} {race?.race_number || "R番号"} {race?.race_name || "レース名"}」を含めるのがおすすめです。
      </p>
      <ExternalWorkbenchCard
        initialRaceName={race?.race_name || ""}
        initialHorseNames={horseNames}
        initialSnapshot={externalSnapshot}
        onSnapshotChange={onExternalSnapshotChange}
      />
    </section>
  );
}

function EmptyCard({ message }: { message: string }) {
  return (
    <div className="mt-3 rounded-2xl border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-500">
      {message}
    </div>
  );
}
