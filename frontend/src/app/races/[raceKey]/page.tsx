"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";

import { ExternalWorkbenchCard } from "@/components/mobile/external-workbench-card";
import { useToast } from "@/components/notifications/toast-stack";
import { BetSimulator } from "@/components/race/bet-simulator";
import { OddsSparkline } from "@/components/race/odds-sparkline";
import { RaceCountdown } from "@/components/race/race-countdown";
import { useOddsHistory, type OddsTrend } from "@/hooks/use-odds-history";
import {
  HORSE_MARKS,
  MARK_ORDER,
  type HorseMark,
  stableHorseMarkKey,
  useHorseMarks,
} from "@/hooks/use-horse-marks";
import {
  emptyPaddockNote,
  paddockNoteBonus,
  type HorsePaddockNote,
  type PaddockGrade,
  type PaddockNotes,
  usePaddockNotes,
} from "@/hooks/use-paddock-notes";
import { useRaceAutoRefresh } from "@/hooks/use-race-auto-refresh";
import { useRaceResearchNotes } from "@/hooks/use-race-research-notes";
import {
  getRaceCourseStats,
  getRaceEntry,
  getSameDayRaces,
  getSameDaySheet,
  getUpcomingRaces,
  parseResearchReport,
  postRaceBetPlan,
  resolveRaceId,
  refreshSameDaySheetVolatile,
} from "@/lib/api/client";
import type {
  BetRankingItem,
  BetPlanResponse,
  EntryHorse,
  ExternalSnapshot,
  RaceCourseStatsResponse,
  RaceEntryResponse,
  RecentRunDetail,
  ResearchParsed,
  ResearchParsedHorseNote,
  ResearchParsedMark,
  ResearchParsedScratch,
  ResearchParsedTicket,
  SameDaySheetRace,
  TrackBias,
  UpcomingRace,
} from "@/lib/api/types";
import { detectResearchDrift, type OddsDrift, type ResearchDrift } from "@/lib/research-drift";

type TabKey = "entry" | "features" | "research" | "bet" | "vote" | "external";

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
  trackBias?: TrackBias | null;
  externalSnapshot?: ExternalSnapshot | null;
};

const DETAIL_CACHE_PREFIX = "keiba:same-day:race-detail:v3:";
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

function formatBodyWeightBucket(value?: string | null): string {
  if (!value) return "";
  if (value === "~439") return "~439kg";
  if (value === "520+") return "520+kg";
  return `${value}kg`;
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

const SIRE_AXIS_LABEL: Record<string, string> = {
  surface: "芝ダ",
  distance: "距離",
  course_shape: "コース",
  going: "道悪",
};

const SIRE_MARK_RANK: Record<string, number> = {
  "◎": 4,
  "○": 3,
  "△": 2,
  "×": 1,
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

function raceDetailHref(race: UpcomingRace): string {
  const params = new URLSearchParams();
  if (race.race_id) params.set("race_id", race.race_id);
  if (race.date_iso) params.set("date", race.date_iso);
  if (race.venue) params.set("venue", race.venue);
  if (race.race_name) params.set("race_name", race.race_name);
  if (race.race_number) params.set("race_number", race.race_number);
  if (race.distance) params.set("distance", race.distance);
  if (race.surface) params.set("surface", race.surface);
  if (race.grade) params.set("grade", race.grade);
  const query = params.toString();
  return `/races/${encodeURIComponent(race.race_key)}${query ? `?${query}` : ""}`;
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
    trackBias: item.track_bias ?? null,
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

function findRaceItemInSheet(races: SameDaySheetRace[], meta: RaceMeta, raceKey: string): SameDaySheetRace | null {
  return (
    races.find((candidate) => {
      const candidateRace = candidate.race;
      return (
        (meta.race_id && candidateRace.race_id === meta.race_id) ||
        candidateRace.race_key === raceKey ||
        candidateRace.race_key === meta.race_key
      );
    }) ?? null
  );
}

function oddsByUmaban(entry: RaceEntryResponse | null): Record<string, number> {
  if (!entry) return {};
  return Object.fromEntries(
    entry.horses
      .map((horse) => [normalizeResearchUmaban(horse.umaban), horse.odds] as const)
      .filter(([umaban, odds]) => umaban && typeof odds === "number" && Number.isFinite(odds)),
  ) as Record<string, number>;
}

function startAtMs(dateIso: string, startTime: string): number | null {
  const time = String(startTime || "").match(/(\d{1,2}):(\d{2})/);
  if (!dateIso || !time) return null;
  const value = new Date(`${dateIso}T${time[1].padStart(2, "0")}:${time[2]}:00+09:00`).getTime();
  return Number.isFinite(value) ? value : null;
}

function shouldTrackOddsHistory(race: RaceMeta | null, entry: RaceEntryResponse | null): boolean {
  if (!race || !entry) return false;
  const startMs = startAtMs(race.date_iso, entry.start_time);
  return startMs == null || Date.now() < startMs;
}

function autoRefreshLabel(phase: string): string {
  if (phase === "30min") return "自動反映: 60秒間隔";
  if (phase === "5min") return "自動反映: 30秒間隔";
  if (phase === "1min") return "自動反映: 15秒間隔";
  return "";
}

function entryHasRecentRunDetailShape(entry: RaceEntryResponse): boolean {
  if (!entry.horses.length) return true;
  return entry.horses.every(
    (horse) =>
      "body_weight_bucket" in horse &&
      "body_weight_source" in horse &&
      "sire_name" in horse &&
      "sire_aptitude_summary" in horse &&
      "broodmare_sire_name" in horse &&
      "sire_aptitude_notes" in horse &&
      Array.isArray(horse.recent_run_details) &&
      horse.recent_run_details.every(
        (detail) =>
          "race_eval" in detail &&
          "body_weight" in detail &&
          "jockey" in detail &&
          "distance_m" in detail &&
          "carried_weight" in detail &&
          "race_time_grade" in detail &&
          "last3f_grade" in detail,
      ),
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

function stripPedigreeDisplayName(value: unknown): string {
  let text = value == null ? "" : String(value).replace(/\s+/g, " ").trim();
  if (!text) return "";
  const mixedName = text.match(/^([^A-Za-z]+?)\s+[A-Za-z].*$/);
  if (mixedName?.[1]) return mixedName[1].trim();
  text = text.replace(/\s*\([^)]*\)\s*$/, "").trim();
  return text;
}

function sireMarksText(marks?: Record<string, string>): string {
  const pairs = Object.entries(marks ?? {});
  if (!pairs.length) return "-";
  return pairs.map(([axis, mark]) => `${SIRE_AXIS_LABEL[axis] ?? axis}${mark}`).join(" / ");
}

function aptitudeScoreText(summary?: string, score?: number, maxScore?: number): string {
  if (!summary) return "-";
  return `${summary} ${score ?? 0}/${maxScore ?? 0}`;
}

function trackTextFromEntry(entry: RaceEntryResponse | null): string {
  const conditions = Object.entries(entry?.track_conditions ?? {}).filter(([, value]) => String(value || "").trim());
  const direct = conditions.length === 1
    ? String(conditions[0][1]).trim()
    : conditions.map(([key, value]) => `${key}:${value}`).join(" / ");
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
        ? `クラス ${detail.race_eval}`
        : "";
  const parts = [
    detail.venue ? `場所 ${detail.venue}` : "",
    detail.jockey || "",
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
  horseMarks,
}: {
  race: RaceMeta | null;
  entry: RaceEntryResponse | null;
  courseStats: RaceCourseStatsResponse | null;
  betPlan: BetPlanResponse | null;
  externalSnapshot: ExternalSnapshot | null;
  horseMarks: Record<string, HorseMark>;
}): string {
  const lines: string[] = [];
  const title = `${race?.race_number ? `${race.race_number} ` : ""}${race?.race_name || "レース詳細"}`;
  const hasMarks = entry?.horses.some((horse) => horseMarks[stableHorseMarkKey(horse.umaban, horse.horse_name)]) ?? false;

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
    lines.push(hasMarks ? "| 印 | 枠 | 馬番 | 馬名 | 騎手 | 単勝 | 脚質 | 斤量 | 馬体重 |" : "| 枠 | 馬番 | 馬名 | 騎手 | 単勝 | 脚質 | 斤量 | 馬体重 |");
    lines.push(hasMarks ? "|---|---|---:|---|---|---:|---|---:|---|" : "|---|---:|---|---|---:|---|---:|---|");
    entry.horses.forEach((horse) => {
      const mark = horseMarks[stableHorseMarkKey(horse.umaban, horse.horse_name)] || "";
      const bodyText = `${horse.body_weight || "-"}${horse.body_delta ? ` (${horse.body_delta})` : ""}${horse.body_weight_bucket ? ` / ${formatBodyWeightBucket(horse.body_weight_bucket)}` : ""}`;
      const base = `${mdCell(horse.waku)} | ${mdCell(horse.umaban)} | ${mdCell(horse.horse_name)} | ${mdCell(horse.jockey)} | ${mdCell(formatOdds(horse.odds))} | ${mdCell(horse.style)} | ${mdCell(horse.weight)} | ${mdCell(bodyText)}`;
      lines.push(hasMarks ? `| ${mdCell(mark)} | ${base} |` : `| ${base} |`);
    });
  } else {
    lines.push("未取得");
  }
  lines.push("");

  lines.push("## 血統適性");
  if (entry?.horses.length) {
    lines.push("| 馬番 | 馬名 | 父 | 母父 | 総合 | 父軸別 | 母父評価 | notes |");
    lines.push("|---:|---|---|---|---|---|---|---|");
    entry.horses.forEach((horse) => {
      lines.push(
        `| ${mdCell(horse.umaban)} | ${mdCell(horse.horse_name)} | ${mdCell(stripPedigreeDisplayName(horse.sire_name))} | ${mdCell(stripPedigreeDisplayName(horse.broodmare_sire_name))} | ${mdCell(aptitudeScoreText(horse.sire_aptitude_summary, horse.sire_aptitude_score, horse.sire_aptitude_max_score))} | ${mdCell(sireMarksText(horse.sire_aptitude_marks))} | ${mdCell(aptitudeScoreText(horse.broodmare_sire_aptitude_summary, horse.broodmare_sire_aptitude_score, horse.broodmare_sire_aptitude_max_score))} | ${mdCell(horse.sire_aptitude_notes)} |`,
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
  const [trackBias, setTrackBias] = useState<TrackBias | null>(null);
  const [externalSnapshot, setExternalSnapshot] = useState<ExternalSnapshot | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("entry");
  const [reportOpen, setReportOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cacheSavedAt, setCacheSavedAt] = useState<string | null>(null);
  const [loadedFromCache, setLoadedFromCache] = useState(false);
  const [prevRace, setPrevRace] = useState<UpcomingRace | null>(null);
  const [nextRace, setNextRace] = useState<UpcomingRace | null>(null);

  const status = statusText(loading || refreshing, error);
  const raceIdForMarks = searchParams.get("race_id") || race?.race_id || raceKey;
  const { toast } = useToast();
  const { marks: horseMarks, setMark: setHorseMark, setMarksBulk: setHorseMarksBulk } = useHorseMarks(raceIdForMarks);
  const { notes: paddockNotes, setNote: setPaddockNote, clearNote: clearPaddockNote } = usePaddockNotes(raceIdForMarks);
  const researchNotes = useRaceResearchNotes(raceIdForMarks);
  const {
    pushSnapshot: pushOddsSnapshot,
    getTrend: getOddsTrend,
    getSparkline: getOddsSparkline,
  } = useOddsHistory(raceIdForMarks);
  const horseNames = useMemo(() => entry?.horses.map((horse) => horse.horse_name).filter(Boolean) ?? [], [entry]);
  const researchMarkdown = useMemo(
    () => buildRaceResearchMarkdown({ race, entry, courseStats, betPlan, externalSnapshot, horseMarks }),
    [race, entry, courseStats, betPlan, externalSnapshot, horseMarks],
  );
  const researchDrift = useMemo(
    () => detectResearchDrift(researchNotes.parsed, entry, trackBias),
    [researchNotes.parsed, entry, trackBias],
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
        trackBias,
        externalSnapshot: snapshot,
      });
      if (savedAt) {
        setCacheSavedAt(savedAt);
      }
    },
    [race, entry, courseStats, betPlan, trackBias],
  );

  useEffect(() => {
    if (shouldTrackOddsHistory(race, entry)) {
      pushOddsSnapshot(oddsByUmaban(entry));
    }
  }, [entry, pushOddsSnapshot, race]);

  const applySameDaySheet = useCallback((sheet: { races: SameDaySheetRace[] }) => {
    if (!race) return false;
    const item = findRaceItemInSheet(sheet.races, race, raceKey);
    if (!item || !item.entry) return;
    const nextRace = metaFromUpcoming(item.race);
    const nextCourseStats = item.course_stats ?? courseStats;
    const nextBetPlan = item.bet_plan ?? betPlan;
    const nextTrackBias = item.track_bias ?? null;
    if (shouldTrackOddsHistory(nextRace, item.entry)) {
      pushOddsSnapshot(oddsByUmaban(item.entry));
    }
    setRace(nextRace);
    setEntry(item.entry);
    setCourseStats(nextCourseStats);
    setBetPlan(nextBetPlan);
    setTrackBias(nextTrackBias);
    setLoadedFromCache(false);
    const savedAt = writeDetailCache(nextRace, {
      race: nextRace,
      entry: item.entry,
      courseStats: nextCourseStats,
      betPlan: nextBetPlan,
      trackBias: nextTrackBias,
      externalSnapshot,
    });
    if (savedAt) setCacheSavedAt(savedAt);
    return true;
  }, [betPlan, courseStats, externalSnapshot, pushOddsSnapshot, race, raceKey]);

  const loadFromSameDayCache = useCallback(async () => {
    if (!race?.date_iso || !race.venue) return;
    const sheet = await getSameDaySheet(race.date_iso, race.venue, 3000, false);
    applySameDaySheet(sheet);
  }, [applySameDaySheet, race]);

  const refreshVolatileForCurrentRace = useCallback(async () => {
    if (!race?.date_iso || !race.venue) return;
    setRefreshing(true);
    setError(null);
    try {
      const sheet = await refreshSameDaySheetVolatile({
        date: race.date_iso,
        venue: race.venue,
        raceId: race.race_id,
        raceNumber: race.race_number,
        budgetYen: 3000,
      });
      const applied = applySameDaySheet(sheet);
      if (applied) {
        toast({
          kind: "odds",
          title: "最新キャッシュを反映",
          body: `${race.race_number || ""} ${race.race_name}`.trim(),
        });
      }
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "軽量更新に失敗しました");
    } finally {
      setRefreshing(false);
    }
  }, [applySameDaySheet, race, toast]);

  const autoRefresh = useRaceAutoRefresh({
    raceId: raceIdForMarks,
    startTime: entry?.start_time || "",
    dateIso: race?.date_iso || "",
    enabled: Boolean(race?.date_iso && race?.venue && entry?.start_time && !loading),
    onRefresh: loadFromSameDayCache,
    onDeadline: (phase) => {
      toast({
        kind: "deadline",
        title: phase === "5min" ? "発走5分前" : "発走1分前",
        body: race ? `${race.race_number || ""} ${race.race_name}`.trim() : undefined,
      });
    },
  });
  const notifiedCriticalOddsRef = useRef<Set<string>>(new Set());
  const notifiedDriftRef = useRef<string>("");
  const criticalOddsChanges = useMemo(
    () =>
      (entry?.horses ?? [])
        .map((horse) => {
          const trend = getOddsTrend(horse.umaban);
          return {
            umaban: normalizeResearchUmaban(horse.umaban) || horse.umaban || "",
            horseName: horse.horse_name,
            trend,
          };
        })
        .filter((item) => item.umaban && item.trend.direction !== "flat" && item.trend.severity === "critical"),
    [entry, getOddsTrend],
  );

  useEffect(() => {
    notifiedCriticalOddsRef.current = new Set();
    notifiedDriftRef.current = "";
  }, [raceIdForMarks]);

  useEffect(() => {
    criticalOddsChanges.forEach((change) => {
      const key = `${change.umaban}:${change.trend.prev ?? ""}:${change.trend.current ?? ""}`;
      if (notifiedCriticalOddsRef.current.has(key)) return;
      notifiedCriticalOddsRef.current.add(key);
      toast({
        kind: "odds",
        title: "オッズ急変",
        body: `${change.umaban}番 ${change.horseName} ${change.trend.prev?.toFixed(1) ?? "-"} -> ${change.trend.current?.toFixed(1) ?? "-"}`,
      });
    });
  }, [criticalOddsChanges, toast]);

  useEffect(() => {
    if (!researchDrift.has_warning) return;
    const key = `${raceIdForMarks}:${researchDrift.has_critical ? "critical" : "warn"}:${researchDrift.odds_drifts.length}:${researchDrift.bias_drift?.conflict ? "bias" : ""}`;
    if (notifiedDriftRef.current === key) return;
    notifiedDriftRef.current = key;
    toast({
      kind: "drift",
      title: "Deep Research 前提ズレ",
      body: researchDrift.has_critical ? "当日オッズが想定から大きく動いています" : "想定値と当日値にズレがあります",
    });
  }, [raceIdForMarks, researchDrift, toast]);

  async function loadAll(forceRefresh = false, baseMeta?: RaceMeta) {
    const meta = baseMeta ?? race ?? metaFromQuery(raceKey, searchParams);
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
          setTrackBias(cached.trackBias ?? null);
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
          setTrackBias(sheetCached.trackBias ?? null);
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
          setTrackBias(cached.trackBias ?? null);
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
          setTrackBias(sheetCached.trackBias ?? null);
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

      const entryResponse = await getRaceEntry(resolvedMeta.race_id, {
        venue: resolvedMeta.venue,
        distance: resolvedMeta.distance,
        surface: resolvedMeta.surface,
      });
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
      setTrackBias(null);
      const savedAt = writeDetailCache(resolvedMeta, {
        race: resolvedMeta,
        entry: entryResponse,
        courseStats: courseStatsResponse,
        betPlan: betResponse,
        trackBias: null,
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
      setEntry(null);
      setCourseStats(null);
      setBetPlan(null);
      setTrackBias(null);
      setExternalSnapshot(null);
      setCacheSavedAt(null);
      setLoadedFromCache(false);
      const queryMeta = metaFromQuery(raceKey, searchParams);
      if (queryMeta.race_id && queryMeta.venue) {
        if (mounted) setRace(queryMeta);
        return queryMeta;
      }
      try {
        const upcoming = await getUpcomingRaces(2, 120, 30);
        const found = upcoming.races.find((item) => item.race_key === raceKey);
        const nextMeta = found ? metaFromUpcoming(found) : queryMeta;
        if (mounted) {
          setRace(nextMeta);
        }
        return nextMeta;
      } catch {
        if (mounted) setRace(queryMeta);
        return queryMeta;
      }
    }
    void init().then((initialMeta) => {
      if (mounted) void loadAll(false, initialMeta);
    });
    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raceKey]);

  useEffect(() => {
    let mounted = true;
    async function loadSiblingRaces() {
      if (!race?.date_iso || !race.venue) {
        setPrevRace(null);
        setNextRace(null);
        return;
      }
      try {
        const response = await getSameDayRaces(race.date_iso, race.venue);
        const races = [...response.races].sort((a, b) => {
          const aNo = Number.parseInt(String(a.race_number || "").replace(/\D/g, ""), 10) || 0;
          const bNo = Number.parseInt(String(b.race_number || "").replace(/\D/g, ""), 10) || 0;
          return aNo - bNo;
        });
        const index = races.findIndex((item) => {
          return (
            (race.race_id && item.race_id === race.race_id) ||
            item.race_key === race.race_key ||
            (item.race_number && item.race_number === race.race_number)
          );
        });
        if (!mounted) return;
        setPrevRace(index > 0 ? races[index - 1] : null);
        setNextRace(index >= 0 && index < races.length - 1 ? races[index + 1] : null);
      } catch {
        if (!mounted) return;
        setPrevRace(null);
        setNextRace(null);
      }
    }
    void loadSiblingRaces();
    return () => {
      mounted = false;
    };
  }, [race]);

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

      {(prevRace || nextRace) ? (
        <div className="mt-3 grid grid-cols-2 gap-2">
          {prevRace ? (
            <Link
              href={raceDetailHref(prevRace)}
              className="min-h-11 rounded-xl border border-slate-300 bg-white px-3 py-3 text-center text-xs font-black text-slate-700"
            >
              ← 前のR {prevRace.race_number || ""}
            </Link>
          ) : (
            <span className="min-h-11 rounded-xl bg-slate-100 px-3 py-3 text-center text-xs font-bold text-slate-400">前のRなし</span>
          )}
          {nextRace ? (
            <Link
              href={raceDetailHref(nextRace)}
              className="min-h-11 rounded-xl bg-emerald-600 px-3 py-3 text-center text-xs font-black text-white"
            >
              次のR {nextRace.race_number || ""} →
            </Link>
          ) : (
            <span className="min-h-11 rounded-xl bg-slate-100 px-3 py-3 text-center text-xs font-bold text-slate-400">次のRなし</span>
          )}
        </div>
      ) : null}

      <section className="mt-3 overflow-hidden rounded-3xl bg-slate-950 text-white shadow-lg">
        <div className="bg-[radial-gradient(circle_at_20%_20%,rgba(16,185,129,.45),transparent_30%),linear-gradient(135deg,#0f172a,#1e293b)] p-5">
          <p className="text-xs font-bold text-emerald-200">当日レースモード</p>
          <h1 className="mt-2 text-2xl font-black tracking-tight">{heroTitle}</h1>
          <p className="mt-2 text-sm text-slate-200">
            {race?.date_str || race?.date_iso || "-"} / {race?.venue || "-"} / {race?.surface || ""}
            {race?.distance || ""}
          </p>
          {entry?.start_time ? <RaceCountdown startTime={entry.start_time} dateIso={race?.date_iso || ""} /> : null}
          {autoRefreshLabel(autoRefresh.phase) ? (
            <p className="mt-2 rounded-xl bg-white/10 px-3 py-2 text-[11px] font-bold text-slate-100">
              {autoRefreshLabel(autoRefresh.phase)}
              {autoRefresh.lastFetchedAt ? ` / ${new Date(autoRefresh.lastFetchedAt).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })}` : ""}
            </p>
          ) : null}
          {status ? <p className={`mt-3 rounded-xl px-3 py-2 text-xs ${error ? "bg-rose-500/20 text-rose-100" : "bg-white/10 text-slate-100"}`}>{status}</p> : null}
          {cacheSavedAt ? (
            <p className="mt-3 rounded-xl bg-white/10 px-3 py-2 text-xs text-slate-100">
              {loadedFromCache ? "保存済みデータを即表示中" : "このレース情報を端末に保存済み"} / {cacheSavedAt}
            </p>
          ) : null}
          <button
            type="button"
            onClick={() => {
              void refreshVolatileForCurrentRace();
            }}
            disabled={loading || refreshing}
            className="mt-4 min-h-12 w-full rounded-2xl bg-emerald-500 px-4 py-3 text-sm font-black text-slate-950 shadow-sm shadow-emerald-200 disabled:opacity-60"
          >
            {refreshing ? "更新中..." : "最新オッズ・基本情報を取得"}
          </button>
          {refreshing ? (
            <p className="mt-2 rounded-xl bg-emerald-400/15 px-3 py-2 text-xs font-bold text-emerald-100">
              最新情報を取得中です。完了までこの画面のままお待ちください。
            </p>
          ) : null}
          {error ? (
            <p className="mt-2 rounded-xl bg-rose-500/20 px-3 py-2 text-xs font-bold text-rose-100">
              通信に失敗した場合でも保存済みデータは表示できます。少し待って再実行してください。
            </p>
          ) : null}
        </div>
      </section>

      {reportOpen ? <ResearchMarkdownPanel markdown={researchMarkdown} /> : null}

      {criticalOddsChanges.length ? (
        <div className="mt-3 rounded-2xl bg-rose-50 px-3 py-2 text-xs font-bold text-rose-900 ring-1 ring-rose-100">
          急変:{" "}
          {criticalOddsChanges
            .map((change) => `${change.umaban}番 ${change.trend.prev?.toFixed(1) ?? "-"} -> ${change.trend.current?.toFixed(1) ?? "-"}`)
            .join(" / ")}
        </div>
      ) : null}

      {entry?.warnings.length ? (
        <div className="mt-3 space-y-2">
          {entry.warnings.map((warning) => (
            <p key={warning} className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {warning}
            </p>
          ))}
        </div>
      ) : null}

      <div className="sticky top-0 z-10 mt-4 grid grid-cols-6 gap-1 rounded-2xl bg-white p-1 shadow-sm ring-1 ring-slate-200">
        {[
          ["entry", "出馬表"],
          ["features", "特徴"],
          ["bet", "買い目"],
          ["vote", "投票"],
          ["external", "外部情報"],
          ["research", "事前"],
        ].sort(([a], [b]) => {
          const order: Record<string, number> = { entry: 0, features: 1, research: 2, bet: 3, vote: 4, external: 5 };
          return (order[a] ?? 99) - (order[b] ?? 99);
        }).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setActiveTab(key as TabKey)}
            className={`min-h-11 rounded-xl px-1 py-3 text-[10px] font-bold sm:text-xs ${
              activeTab === key ? "bg-slate-900 text-white" : "text-slate-600"
            }`}
          >
            {key === "external" ? "外部" : label}
          </button>
        ))}
      </div>

      {activeTab === "entry" ? (
        <EntryTab
          entry={entry}
          courseStats={courseStats}
          trackBias={trackBias}
          horseMarks={horseMarks}
          onMarkChange={setHorseMark}
          paddockNotes={paddockNotes}
          onPaddockNoteChange={setPaddockNote}
          onPaddockNoteClear={clearPaddockNote}
          researchParsed={researchNotes.parsed}
          researchDrift={researchDrift}
          getOddsTrend={getOddsTrend}
          getOddsSparkline={getOddsSparkline}
        />
      ) : null}
      {activeTab === "features" ? <FeaturesTab courseStats={courseStats} entry={entry} race={race} /> : null}
      {activeTab === "research" ? (
        <ResearchNotesTab
          raceId={raceIdForMarks}
          entry={entry}
          horseMarks={horseMarks}
          researchNotes={researchNotes}
          onMarksBulkChange={setHorseMarksBulk}
          onOpenBetTab={() => setActiveTab("bet")}
        />
      ) : null}
      {activeTab === "bet" ? (
        <BetTab
          betPlan={betPlan}
          entry={entry}
          paddockNotes={paddockNotes}
          researchParsed={researchNotes.parsed}
          researchDrift={researchDrift}
          isRestoringResearch={researchNotes.isRestoringBackup}
        />
      ) : null}
      {activeTab === "vote" ? <BetSimulator key={raceIdForMarks} raceId={raceIdForMarks} entry={entry} /> : null}
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

  function handleAiOpen(url: string, label: string) {
    let copyPromise: Promise<void> | null = null;
    try {
      copyPromise = navigator.clipboard.writeText(markdown);
    } catch {
      copyPromise = null;
    }
    const opened = window.open(url, "_blank", "noopener,noreferrer");
    if (!opened) {
      setCopyStatus("新しいタブを開けませんでした。ブラウザのポップアップ設定を確認してください。");
    }
    if (!copyPromise) {
      textareaRef.current?.focus();
      textareaRef.current?.select();
      setCopyStatus("自動コピー失敗。下のテキストを手動コピーしてください。");
      return;
    }
    void copyPromise
      .then(() => setCopyStatus(`${label}を開きました。Markdownもコピー済みです。`))
      .catch(() => {
        textareaRef.current?.focus();
        textareaRef.current?.select();
        setCopyStatus("自動コピー失敗。下のテキストを手動コピーしてください。");
      });
  }

  return (
    <section className="mt-3 rounded-3xl border border-emerald-200 bg-emerald-50 p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
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
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
        {[
          ["Claudeで質問", "https://claude.ai/new"],
          ["Geminiで質問", "https://gemini.google.com/app"],
          ["ChatGPTで質問", "https://chat.openai.com/"],
        ].map(([label, url]) => (
          <button
            key={label}
            type="button"
            onClick={() => handleAiOpen(url, label)}
            className="min-h-11 rounded-xl bg-slate-950 px-3 py-2 text-xs font-black text-white"
          >
            {label}
          </button>
        ))}
      </div>
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

type RaceResearchNotesStore = ReturnType<typeof useRaceResearchNotes>;

const RESEARCH_MARK_NORMALIZE: Record<string, HorseMark> = {
  "◎": "◎",
  "〇": "〇",
  "○": "〇",
  "▲": "〇",
  "△": "△",
  "☆": "△",
  "注": "△",
  "消": "消",
};

function normalizeResearchUmaban(value?: string | null): string {
  const normalized = String(value || "")
    .trim()
    .replace(/[０-９]/g, (char) => String.fromCharCode(char.charCodeAt(0) - 0xfee0))
    .replace(/[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱]/g, (char) => {
      const map: Record<string, string> = {
        "①": "1",
        "②": "2",
        "③": "3",
        "④": "4",
        "⑤": "5",
        "⑥": "6",
        "⑦": "7",
        "⑧": "8",
        "⑨": "9",
        "⑩": "10",
        "⑪": "11",
        "⑫": "12",
        "⑬": "13",
        "⑭": "14",
        "⑮": "15",
        "⑯": "16",
        "⑰": "17",
        "⑱": "18",
      };
      return map[char] || char;
    });
  const match = normalized.match(/\d+/);
  if (!match) return "";
  const parsed = Number.parseInt(match[0], 10);
  return Number.isFinite(parsed) && parsed > 0 ? String(parsed) : "";
}

function formatParsedTicket(ticket: ResearchParsedTicket): string {
  if (ticket.formation?.length) {
    return ticket.formation.map((row) => row.join("-")).join(" / ");
  }
  return ticket.horses.join(ticket.bet_type.includes("ボックス") ? "・" : "-");
}

type ResearchAiMark = {
  umaban: string;
  horse_name: string;
  mark: ResearchParsedMark["mark"] | "消";
  comment: string;
};

function researchAiMarkClass(mark: string): string {
  if (mark === "◎") return "bg-rose-100 text-rose-800";
  if (mark === "〇" || mark === "○" || mark === "▲") return "bg-orange-100 text-orange-800";
  if (mark === "△" || mark === "☆" || mark === "注") return "bg-emerald-100 text-emerald-800";
  if (mark === "消") return "bg-slate-200 text-slate-600";
  return "bg-amber-100 text-amber-800";
}

function buildResearchRawPreviewSections(text: string): Array<{ title: string; body: string }> {
  const normalized = text
    .replace(/\r\n/g, "\n")
    .replace(/\s+(展開予測|買い目|買わない理由がある馬|最大回収シナリオ)\s+/g, "\n$1\n")
    .trim();
  if (!normalized) return [];
  const headings = ["展開予測", "買い目", "買わない理由がある馬", "最大回収シナリオ"];
  const sections: Array<{ title: string; body: string }> = [];
  let currentTitle = "概要";
  let currentBody: string[] = [];
  normalized.split("\n").forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    if (headings.includes(trimmed)) {
      if (currentBody.length) sections.push({ title: currentTitle, body: currentBody.join("\n").trim() });
      currentTitle = trimmed;
      currentBody = [];
      return;
    }
    currentBody.push(trimmed);
  });
  if (currentBody.length) sections.push({ title: currentTitle, body: currentBody.join("\n").trim() });
  return sections;
}

function ResearchNotesTab({
  raceId,
  entry,
  horseMarks,
  researchNotes,
  onMarksBulkChange,
  onOpenBetTab,
}: {
  raceId: string;
  entry: RaceEntryResponse | null;
  horseMarks: Record<string, HorseMark>;
  researchNotes: RaceResearchNotesStore;
  onMarksBulkChange: (patch: Record<string, HorseMark | null>) => void;
  onOpenBetTab: () => void;
}) {
  const notesRef = useRef<HTMLTextAreaElement | null>(null);
  const { notes, savedAt, parsed, parsedAt, parseError, setNotes, clearNotes, setParsed, setParseError } = researchNotes;
  const [draft, setDraft] = useState(notes);
  const [status, setStatus] = useState<string | null>(null);
  const [parsing, setParsing] = useState(false);

  useEffect(() => {
    setDraft(notes);
  }, [notes]);

  function savedAtText(): string {
    if (!savedAt) return "未保存";
    return new Intl.DateTimeFormat("ja-JP", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(savedAt));
  }

  function parsedAtText(): string {
    if (!parsedAt) return "";
    return new Intl.DateTimeFormat("ja-JP", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(parsedAt));
  }

  async function saveAndParseDraft() {
    const text = draft.trimEnd();
    setNotes(text, "manual");
    setParsed(null);
    setParseError(null);
    setStatus(null);
    if (text.trim().length < 10) {
      setParseError("raw_text が短すぎます");
      setStatus("レポート本文をもう少し入力してください。");
      return;
    }
    setParsing(true);
    try {
      const parsedResult = await parseResearchReport(
        raceId,
        text,
        (entry?.horses ?? []).map((horse) => ({ umaban: horse.umaban || "", horse_name: horse.horse_name || "" })),
      );
      setParsed(parsedResult);
      setParseError(null);
      const appliedCount = applyParsedMarks(parsedResult);
      setStatus(`事前研究レポートを保存し、構造化しました。${appliedCount > 0 ? `印メモに${appliedCount}件反映済みです。` : "印メモの差分はありません。"}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "構造化に失敗しました";
      setParsed(null);
      setParseError(message);
      setStatus("レポートは保存しましたが、構造化に失敗しました。");
    } finally {
      setParsing(false);
    }
  }

  function clearDraft() {
    clearNotes();
    setDraft("");
    notesRef.current?.focus();
    setStatus("事前研究レポートをクリアしました。");
  }

  function applyParsedMarks(parsedInput: ResearchParsed): number {
    if (!entry) return 0;
    const horseByUmaban = new Map<string, EntryHorse>();
    entry.horses.forEach((horse) => {
      const umaban = normalizeResearchUmaban(horse.umaban);
      if (umaban) horseByUmaban.set(umaban, horse);
    });
    const desired = new Map<string, { mark: HorseMark; horseName: string }>();
    parsedInput.marks.forEach((mark) => {
      const umaban = normalizeResearchUmaban(mark.umaban);
      const normalizedMark = RESEARCH_MARK_NORMALIZE[mark.mark];
      if (umaban && normalizedMark) {
        desired.set(umaban, { mark: normalizedMark, horseName: mark.horse_name || horseByUmaban.get(umaban)?.horse_name || "" });
      }
    });
    parsedInput.scratched.forEach((scratch) => {
      const umaban = normalizeResearchUmaban(scratch.umaban);
      if (umaban) {
        desired.set(umaban, { mark: "消", horseName: scratch.horse_name || horseByUmaban.get(umaban)?.horse_name || "" });
      }
    });

    const patch: Record<string, HorseMark> = {};
    desired.forEach(({ mark, horseName }, umaban) => {
      const horse = horseByUmaban.get(umaban);
      const key = stableHorseMarkKey(umaban, horse?.horse_name || horseName);
      const current = horseMarks[key] || "";
      if (current === mark) return;
      patch[key] = mark;
    });

    const changeCount = Object.keys(patch).length;
    if (changeCount === 0) return 0;
    onMarksBulkChange(patch);
    return changeCount;
  }

  return (
    <section className="mt-4 space-y-4">
      {parsed ? (
        <div className="rounded-3xl border border-amber-200 bg-amber-50 p-4 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-sm font-black text-amber-950">AI構造化結果</p>
              <p className="mt-1 text-xs text-amber-800">
                印 {parsed.marks.length}件 / 買い目 {parsed.tickets.length}件 / 消し馬 {parsed.scratched.length}件
                {parsedAt ? ` / ${parsedAtText()}` : ""}
              </p>
            </div>
            <button
              type="button"
              onClick={onOpenBetTab}
              className="min-h-11 rounded-xl bg-slate-950 px-3 py-2 text-xs font-black text-white"
            >
              買い目を見る
            </button>
          </div>

          {parsed.pace_label || parsed.course_note ? (
            <div className="mt-3 grid grid-cols-1 gap-2">
              {parsed.pace_label ? (
                <div className="rounded-2xl bg-white/85 px-3 py-2 text-xs leading-5 text-amber-950">
                  <span className="font-black">展開</span>
                  <span className="ml-2">{parsed.pace_label}</span>
                </div>
              ) : null}
              {parsed.course_note ? (
                <div className="rounded-2xl bg-white/85 px-3 py-2 text-xs leading-5 text-amber-950">
                  <span className="font-black">コース</span>
                  <span className="ml-2">{parsed.course_note}</span>
                </div>
              ) : null}
            </div>
          ) : null}

          {parsed.marks.length ? (
            <div className="mt-4 overflow-hidden rounded-2xl bg-white/90 ring-1 ring-amber-100">
              <div className="grid grid-cols-[3rem_3rem_1fr] bg-amber-100/70 px-3 py-2 text-[11px] font-black text-amber-950">
                <span>馬番</span>
                <span>印</span>
                <span>コメント</span>
              </div>
              {parsed.marks.map((mark, index) => (
                <div
                  key={`${mark.umaban}-${mark.mark}-${index}`}
                  className="grid grid-cols-[3rem_3rem_1fr] items-start gap-0 border-t border-amber-100 px-3 py-2 text-xs text-amber-950"
                >
                  <span className="font-black">{normalizeResearchUmaban(mark.umaban) || mark.umaban}</span>
                  <span className="font-black">{mark.mark}</span>
                  <span className="min-w-0 leading-5">
                    {mark.horse_name ? <span className="font-black">{mark.horse_name}</span> : null}
                    {mark.comment ? <span className="ml-1 text-amber-800">{mark.comment}</span> : null}
                  </span>
                </div>
              ))}
            </div>
          ) : null}

          {parsed.tickets.length ? (
            <div className="mt-4 space-y-2">
              <p className="text-xs font-black text-amber-950">AI推奨買い目</p>
              {parsed.tickets.map((ticket, index) => (
                <div key={`${ticket.bet_type}-${index}`} className="rounded-2xl bg-white/90 px-3 py-2 text-xs text-amber-950 ring-1 ring-amber-100">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-amber-500 px-2 py-0.5 text-[10px] font-black text-white">{ticket.bet_type}</span>
                    <span className="font-black">{formatParsedTicket(ticket) || "-"}</span>
                    {ticket.amount_yen ? <span className="font-bold text-amber-700">{ticket.amount_yen.toLocaleString()}円</span> : null}
                  </div>
                  {ticket.reason ? <p className="mt-1 leading-5 text-amber-800">{ticket.reason}</p> : null}
                </div>
              ))}
            </div>
          ) : null}

          {parsed.scratched.length ? (
            <div className="mt-4 rounded-2xl bg-white/80 px-3 py-2 text-xs text-amber-950 ring-1 ring-amber-100">
              <p className="font-black">消し馬</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {parsed.scratched.map((item, index) => (
                  <span key={`${item.umaban}-${index}`} className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-bold text-slate-700">
                    {normalizeResearchUmaban(item.umaban) || item.umaban}番{item.horse_name ? ` ${item.horse_name}` : ""}
                    {item.reason ? `: ${item.reason}` : ""}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {parsed.max_payout_scenario ? (
            <p className="mt-4 rounded-2xl bg-white/85 px-3 py-2 text-xs leading-5 text-amber-900">
              <span className="font-black">最大回収シナリオ</span>
              <span className="ml-2">{parsed.max_payout_scenario}</span>
            </p>
          ) : null}
        </div>
      ) : null}

      {notes ? <ResearchRawPreview notes={notes} /> : null}

      <div className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-black text-slate-950">事前研究レポート</p>
            <p className="mt-1 text-xs text-slate-500">最終保存: {savedAtText()}</p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                void saveAndParseDraft();
              }}
              disabled={parsing}
              className="min-h-11 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-black text-white disabled:opacity-60"
            >
              {parsing ? "構造化中..." : "保存して構造化"}
            </button>
            <button type="button" onClick={clearDraft} className="min-h-11 rounded-xl bg-slate-100 px-4 py-2 text-xs font-black text-slate-700">
              クリア
            </button>
          </div>
        </div>
        <textarea
          ref={notesRef}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={20}
          className="mt-3 w-full rounded-2xl border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-800"
          placeholder="Deep Research のレポートをここに貼り付け"
        />
        {status ? <p className="mt-3 rounded-xl bg-emerald-50 px-3 py-2 text-xs text-emerald-800">{status}</p> : null}
        {parseError ? (
          <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs font-bold text-amber-800">
            構造化エラー: {parseError}
          </p>
        ) : null}
      </div>

    </section>
  );
}

function ResearchRawPreview({ notes }: { notes: string }) {
  const sections = buildResearchRawPreviewSections(notes);
  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm font-black text-slate-950">レポート本文プレビュー</p>
      <div className="mt-3 space-y-2">
        {sections.map((section) => (
          <details key={section.title} open={section.title !== "概要"} className="rounded-2xl bg-slate-50 px-3 py-2 ring-1 ring-slate-100">
            <summary className="cursor-pointer text-xs font-black text-slate-800">{section.title}</summary>
            <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-slate-700">{section.body}</p>
          </details>
        ))}
      </div>
    </div>
  );
}

type EntrySortKey = "mark" | "umaban" | "odds";

function oddsTrendClass(trend: OddsTrend): string {
  if (trend.severity === "critical") return "font-black text-rose-700";
  if (trend.severity === "warn") return "font-bold text-orange-600";
  return "text-slate-400";
}

function driftIcon(drift?: OddsDrift): string {
  if (!drift) return "";
  if (drift.severity === "critical") return "⚠";
  if (drift.severity === "warn") return "△";
  return "";
}

function bodyWeightTop3Rate(horse: EntryHorse, courseStats: RaceCourseStatsResponse | null): number | null {
  if (typeof horse.body_weight_top3_rate === "number") return horse.body_weight_top3_rate;
  const bucket = horse.body_weight_bucket;
  if (!bucket) return null;
  const row = courseStats?.body_weight_stats?.find((item) => String(item.label ?? "") === bucket);
  const value = row?.top3_rate;
  return typeof value === "number" ? value : null;
}

function EntryTab({
  entry,
  courseStats,
  trackBias,
  horseMarks,
  onMarkChange,
  paddockNotes,
  onPaddockNoteChange,
  onPaddockNoteClear,
  researchParsed,
  researchDrift,
  getOddsTrend,
  getOddsSparkline,
}: {
  entry: RaceEntryResponse | null;
  courseStats: RaceCourseStatsResponse | null;
  trackBias: TrackBias | null;
  horseMarks: Record<string, HorseMark>;
  onMarkChange: (horseKey: string, mark: HorseMark | null) => void;
  paddockNotes: PaddockNotes;
  onPaddockNoteChange: (horseKey: string, patch: Partial<Omit<HorsePaddockNote, "updatedAt">>) => void;
  onPaddockNoteClear: (horseKey: string) => void;
  researchParsed: ResearchParsed | null;
  researchDrift: ResearchDrift;
  getOddsTrend: (umaban: string) => OddsTrend;
  getOddsSparkline: (umaban: string) => number[];
}) {
  const [sortKey, setSortKey] = useState<EntrySortKey>("umaban");
  const [hideErased, setHideErased] = useState(false);
  if (!entry) {
    return <EmptyCard message="出馬表を取得中です。" />;
  }
  const horses = [...entry.horses]
    .filter((horse) => {
      const mark = horseMarks[stableHorseMarkKey(horse.umaban, horse.horse_name)] || "";
      return !(hideErased && mark === "消");
    })
    .sort((a, b) => {
      if (sortKey === "mark") {
        const markA = horseMarks[stableHorseMarkKey(a.umaban, a.horse_name)] || "";
        const markB = horseMarks[stableHorseMarkKey(b.umaban, b.horse_name)] || "";
        const markDiff = MARK_ORDER[markA] - MARK_ORDER[markB];
        if (markDiff !== 0) return markDiff;
      }
      if (sortKey === "odds") {
        const oddsA = typeof a.odds === "number" ? a.odds : Number.POSITIVE_INFINITY;
        const oddsB = typeof b.odds === "number" ? b.odds : Number.POSITIVE_INFINITY;
        const oddsDiff = oddsA - oddsB;
        if (oddsDiff !== 0) return oddsDiff;
      }
      return (Number.parseInt(a.umaban || "999", 10) || 999) - (Number.parseInt(b.umaban || "999", 10) || 999);
    });
  const aiAnalysisByUmaban = new Map<string, ResearchParsedHorseNote>();
  (researchParsed?.horse_notes ?? []).forEach((note) => {
    const umaban = normalizeResearchUmaban(note.umaban);
    if (umaban && note.text) aiAnalysisByUmaban.set(umaban, note);
  });
  const aiMarkByUmaban = new Map<string, ResearchAiMark>();
  (researchParsed?.marks ?? []).forEach((mark) => {
    const umaban = normalizeResearchUmaban(mark.umaban);
    if (!umaban) return;
    aiMarkByUmaban.set(umaban, {
      umaban,
      horse_name: mark.horse_name,
      mark: mark.mark,
      comment: mark.comment,
    });
  });
  (researchParsed?.scratched ?? []).forEach((scratch: ResearchParsedScratch) => {
    const umaban = normalizeResearchUmaban(scratch.umaban);
    if (!umaban) return;
    aiMarkByUmaban.set(umaban, {
      umaban,
      horse_name: scratch.horse_name,
      mark: "消",
      comment: scratch.reason,
    });
  });
  const driftByUmaban = new Map<string, OddsDrift>();
  researchDrift.odds_drifts.forEach((drift) => {
    driftByUmaban.set(normalizeResearchUmaban(drift.umaban), drift);
  });
  return (
    <section className="mt-3 space-y-3">
      <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p className="text-xs font-semibold text-slate-500">脚質分布</p>
        <p className="mt-1 text-lg font-black text-slate-900">{entry.style_distribution_label || "-"}</p>
        {trackBias?.summary_label ? (
          <div className="mt-2 rounded-2xl bg-indigo-50 px-3 py-2 text-xs text-indigo-800">
            <span className="font-black">バイアス:</span> {trackBias.summary_label}
            <span className="ml-2 text-[10px] opacity-70">
              ({trackBias.sample_size}R{trackBias.fallback_used ? " / 同会場他コース" : ""})
            </span>
          </div>
        ) : null}
        <p className="mt-1 text-xs text-slate-500">{entry.race_data01}</p>
      </div>
      <div className="rounded-2xl bg-white p-3 shadow-sm ring-1 ring-slate-200">
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs font-bold text-slate-600">
            並び替え
            <select
              value={sortKey}
              onChange={(event) => setSortKey(event.target.value as EntrySortKey)}
              className="ml-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-bold text-slate-800"
            >
              <option value="umaban">馬番順</option>
              <option value="mark">印順</option>
              <option value="odds">単勝順</option>
            </select>
          </label>
          <label className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-700">
            <input
              type="checkbox"
              checked={hideErased}
              onChange={(event) => setHideErased(event.target.checked)}
              className="h-4 w-4"
            />
            消した馬を非表示
          </label>
        </div>
      </div>
      {horses.map((horse) => (
        <HorseCard
          key={`${horse.umaban || horse.horse_name}-${horse.horse_name}`}
          horse={horse}
          mark={horseMarks[stableHorseMarkKey(horse.umaban, horse.horse_name)] || ""}
          top3Rate={bodyWeightTop3Rate(horse, courseStats)}
          onMarkChange={onMarkChange}
          paddockNote={paddockNotes[stableHorseMarkKey(horse.umaban, horse.horse_name)]}
          onPaddockNoteChange={onPaddockNoteChange}
          onPaddockNoteClear={onPaddockNoteClear}
          aiAnalysis={aiAnalysisByUmaban.get(normalizeResearchUmaban(horse.umaban))}
          aiMark={aiMarkByUmaban.get(normalizeResearchUmaban(horse.umaban))}
          oddsTrend={getOddsTrend(horse.umaban)}
          oddsSparkline={getOddsSparkline(horse.umaban)}
          oddsDrift={driftByUmaban.get(normalizeResearchUmaban(horse.umaban))}
        />
      ))}
    </section>
  );
}

function HorseCard({
  horse,
  mark,
  top3Rate,
  onMarkChange,
  paddockNote,
  onPaddockNoteChange,
  onPaddockNoteClear,
  aiAnalysis,
  aiMark,
  oddsTrend,
  oddsSparkline,
  oddsDrift,
}: {
  horse: EntryHorse;
  mark: HorseMark | "";
  top3Rate: number | null;
  onMarkChange: (horseKey: string, mark: HorseMark | null) => void;
  paddockNote?: HorsePaddockNote;
  onPaddockNoteChange: (horseKey: string, patch: Partial<Omit<HorsePaddockNote, "updatedAt">>) => void;
  onPaddockNoteClear: (horseKey: string) => void;
  aiAnalysis?: ResearchParsedHorseNote;
  aiMark?: ResearchAiMark;
  oddsTrend: OddsTrend;
  oddsSparkline: number[];
  oddsDrift?: OddsDrift;
}) {
  const horseKey = stableHorseMarkKey(horse.umaban, horse.horse_name);
  const hasRecentRuns = horse.recent_runs.some((run) => run.trim().length > 0);
  const currentPaddockNote = paddockNote ?? emptyPaddockNote();
  return (
    <article className={`rounded-3xl border border-l-8 border-slate-200 bg-white p-4 shadow-sm ${wakuBorderClass(horse.waku)}`}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500">
            <span className={`inline-flex min-w-8 items-center justify-center rounded-full border px-2 py-1 font-black ${wakuBadgeClass(horse.waku)}`}>
              {horse.waku || "-"}枠
            </span>
            <span>{horse.umaban || "-"}番 / {horse.jockey || "-"}</span>
          </p>
          <h2 className="mt-1 break-words text-lg font-black text-slate-950">{horse.horse_name}</h2>
          <p className="mt-1 break-words text-xs text-slate-500">
            {horse.sex_age || "-"} / 斤量 {horse.weight || "-"} / 馬体重 {horse.body_weight || "-"}
            {horse.body_delta ? ` (${horse.body_delta})` : ""}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <div className="mb-2 flex justify-end">
            {mark ? (
              <span className={`inline-flex h-9 min-w-9 items-center justify-center rounded-full px-2 text-sm font-black ${mark === "消" ? "bg-slate-200 text-slate-500" : "bg-rose-100 text-rose-700"}`}>
                {mark}
              </span>
            ) : (
              <span className="inline-flex h-9 min-w-9 items-center justify-center rounded-full bg-slate-100 px-2 text-xs font-bold text-slate-400">
                無印
              </span>
            )}
          </div>
          <p className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-black text-emerald-700">{horse.style || "-"}</p>
          <p className="mt-2 text-lg font-black tabular-nums text-slate-900">
            {formatOdds(horse.odds)}
            {oddsTrend.direction !== "flat" ? (
              <span className={`ml-1 text-xs ${oddsTrendClass(oddsTrend)}`}>
                {oddsTrend.direction === "up" ? "↑" : "↓"}
                {oddsTrend.prev != null ? `${oddsTrend.prev.toFixed(1)}->` : ""}
              </span>
            ) : null}
          </p>
          <div className="mt-1 flex justify-end text-slate-400">
            <OddsSparkline values={oddsSparkline} />
          </div>
          <p className="text-[10px] text-slate-500">単勝</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {HORSE_MARKS.map((candidate) => (
          <button
            key={candidate}
            type="button"
            onClick={() => onMarkChange(horseKey, candidate)}
            className={`h-9 min-w-9 rounded-xl px-2 text-sm font-black ${
              mark === candidate ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"
            }`}
          >
            {candidate}
          </button>
        ))}
        <button
          type="button"
          onClick={() => onMarkChange(horseKey, null)}
          className="h-9 min-w-9 rounded-xl bg-white px-2 text-xs font-black text-slate-500 ring-1 ring-slate-200"
        >
          ×
        </button>
      </div>
      {aiMark || aiAnalysis ? (
        <div className="mt-3 rounded-2xl bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200">
          <div className="flex flex-wrap items-center gap-2">
            {aiMark ? (
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-black ${researchAiMarkClass(aiMark.mark)}`}>
                AI{aiMark.mark}{driftIcon(oddsDrift)}
              </span>
            ) : (
              <span className="rounded-full bg-amber-500 px-2 py-0.5 text-[10px] font-black text-white">AI</span>
            )}
            <span className="font-black">{aiAnalysis?.label || "AI分析"}</span>
          </div>
          {aiMark?.comment ? <p className="mt-2 whitespace-pre-wrap leading-5">{aiMark.comment}</p> : null}
          {aiAnalysis?.text ? <p className="mt-1 whitespace-pre-wrap leading-5 text-amber-800">{aiAnalysis.text}</p> : null}
        </div>
      ) : null}
      <PaddockMemoControls
        note={currentPaddockNote}
        onChange={(patch) => onPaddockNoteChange(horseKey, patch)}
        onClear={() => onPaddockNoteClear(horseKey)}
      />
      {horse.body_weight_bucket ? (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-[11px] font-bold text-slate-600">
          <span className="rounded-full bg-slate-100 px-2 py-1">
            馬体重帯 {formatBodyWeightBucket(horse.body_weight_bucket)}
            {horse.body_weight_source === "previous" ? "（前走）" : ""}
          </span>
          {typeof top3Rate === "number" ? (
            <span className="rounded-full bg-emerald-50 px-2 py-1 text-emerald-700">同条件 複勝率{top3Rate.toFixed(0)}%</span>
          ) : null}
        </p>
      ) : null}
      <div className="mt-3 space-y-2">
        {hasRecentRuns ? (
          horse.recent_runs.map((run, idx) => (
            <RecentRunLine
              key={`${horse.horse_name}-run-${idx}`}
              label={idx === 0 ? "前走" : `${idx + 1}走前`}
              run={run}
              last3f={horse.last3fs[idx]}
              detail={horse.recent_run_details?.[idx]}
            />
          ))
        ) : (
          <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-500">
            初出走または競走成績なし
          </div>
        )}
      </div>
    </article>
  );
}

const PADDOCK_GRADE_OPTIONS: Array<{ value: PaddockGrade; label: string; className: string }> = [
  { value: "good", label: "◎", className: "bg-rose-100 text-rose-800" },
  { value: "ok", label: "○", className: "bg-emerald-100 text-emerald-800" },
  { value: "watch", label: "△", className: "bg-amber-100 text-amber-800" },
  { value: "bad", label: "×", className: "bg-slate-200 text-slate-600" },
];

function gradeButtonClass(active: boolean, colorClass: string): string {
  return active
    ? `${colorClass} ring-2 ring-slate-900/10`
    : "bg-white text-slate-500 ring-1 ring-slate-200";
}

function PaddockGradePicker({
  label,
  value,
  onChange,
}: {
  label: string;
  value: PaddockGrade;
  onChange: (value: PaddockGrade) => void;
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      <span className="mr-1 text-[11px] font-black text-slate-600">{label}</span>
      {PADDOCK_GRADE_OPTIONS.map((option) => (
        <button
          key={`${label}-${option.value}`}
          type="button"
          onClick={() => onChange(value === option.value ? "" : option.value)}
          className={`h-8 min-w-8 rounded-xl px-2 text-xs font-black ${gradeButtonClass(value === option.value, option.className)}`}
          aria-pressed={value === option.value}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function PaddockMemoControls({
  note,
  onChange,
  onClear,
}: {
  note: HorsePaddockNote;
  onChange: (patch: Partial<Omit<HorsePaddockNote, "updatedAt">>) => void;
  onClear: () => void;
}) {
  const bonus = paddockNoteBonus(note);
  const currentGrade = note.paddock || note.returnHorse;
  const hasValue = Boolean(currentGrade || note.memo.trim());
  return (
    <div className="mt-3 rounded-2xl bg-slate-50 p-3 ring-1 ring-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-black text-slate-700">パドック/返し馬</p>
        {bonus.bonus ? (
          <span className={`rounded-full px-2 py-1 text-[11px] font-black ${bonus.bonus > 0 ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"}`}>
            現地{bonus.bonus > 0 ? "+" : ""}
            {Math.round(bonus.bonus * 100)}
          </span>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2">
        <PaddockGradePicker
          label="総合印"
          value={currentGrade}
          onChange={(paddock) => onChange({ paddock, returnHorse: "" })}
        />
      </div>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row">
        <input
          type="text"
          value={note.memo}
          onChange={(event) => onChange({ memo: event.target.value })}
          className="min-h-10 min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800"
          placeholder="気配メモ"
          maxLength={160}
        />
        {hasValue ? (
          <button
            type="button"
            onClick={onClear}
            className="min-h-10 rounded-xl bg-white px-3 text-xs font-black text-slate-500 ring-1 ring-slate-200"
          >
            クリア
          </button>
        ) : null}
      </div>
    </div>
  );
}

const RATING_CHIP_COLOR: Record<string, string> = {
  S: "bg-rose-100 text-rose-800",
  A: "bg-orange-100 text-orange-800",
  B: "bg-emerald-100 text-emerald-800",
  C: "bg-slate-200 text-slate-700",
  D: "bg-slate-100 text-slate-500",
};

function ratingChipColor(grade: string | undefined): string {
  return RATING_CHIP_COLOR[grade || ""] || "bg-slate-100 text-slate-400";
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
  const raceTimeGrade = detail?.race_time_grade || "-";
  const last3fGrade = detail?.last3f_grade || "-";
  const hasDetailChips = Boolean(detail);
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
        {detail ? (
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-black ${ratingChipColor(last3fGrade)}`}>
            上{last3fGrade}
          </span>
        ) : null}
      </div>
      {hasDetailChips ? (
        <div className="mb-1 flex flex-wrap gap-1">
          {detail?.venue ? (
            <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-bold text-indigo-700">
              {detail.venue}
            </span>
          ) : null}
          {detail?.jockey ? (
            <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[11px] font-bold text-violet-700">
              {detail.jockey}
            </span>
          ) : null}
          {detail?.race_time ? (
            <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-bold text-slate-700 ring-1 ring-slate-200">
              {detail.race_time}
            </span>
          ) : null}
          {detail ? (
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-black ${ratingChipColor(raceTimeGrade)}`}>
              走{raceTimeGrade}
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

function FeaturesTab({
  courseStats,
  entry,
  race,
}: {
  courseStats: RaceCourseStatsResponse | null;
  entry: RaceEntryResponse | null;
  race: RaceMeta | null;
}) {
  if (!courseStats) {
    return <EmptyCard message="レース特徴を取得中です。" />;
  }
  const rankedHorses = [...(entry?.horses ?? [])]
    .filter((horse) => horse.sire_data_available && horse.sire_aptitude_summary)
    .sort((a, b) => {
      const aRatio = (a.sire_aptitude_score ?? 0) / Math.max(1, a.sire_aptitude_max_score ?? 0);
      const bRatio = (b.sire_aptitude_score ?? 0) / Math.max(1, b.sire_aptitude_max_score ?? 0);
      if (bRatio !== aRatio) return bRatio - aRatio;
      const aBroodmareRatio = (a.broodmare_sire_aptitude_score ?? 0) / Math.max(1, a.broodmare_sire_aptitude_max_score ?? 0);
      const bBroodmareRatio = (b.broodmare_sire_aptitude_score ?? 0) / Math.max(1, b.broodmare_sire_aptitude_max_score ?? 0);
      if (bBroodmareRatio !== aBroodmareRatio) return bBroodmareRatio - aBroodmareRatio;
      return (SIRE_MARK_RANK[b.sire_aptitude_summary ?? ""] ?? 0) - (SIRE_MARK_RANK[a.sire_aptitude_summary ?? ""] ?? 0);
    });
  const unregisteredSires = Array.from(
    new Set(
      (entry?.horses ?? [])
        .flatMap((horse) => [
          horse.sire_name && !horse.sire_data_available ? stripPedigreeDisplayName(horse.sire_name) : "",
          horse.broodmare_sire_name && !horse.broodmare_sire_data_available ? stripPedigreeDisplayName(horse.broodmare_sire_name) : "",
        ])
        .filter(Boolean),
    ),
  );
  const conditionLabel = `${race?.surface || ""}${race?.distance || ""} / ${race?.venue || "-"} / ${trackTextFromEntry(entry) || "馬場未取得"}`;

  return (
    <section className="mt-3 space-y-3">
      <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p className="text-xs font-semibold text-slate-500">コース特徴</p>
        <p className="mt-1 text-sm font-semibold text-slate-900">{courseStats.summary.course}</p>
        <p className="mt-2 rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {courseStats.summary.winning_type || "傾向データ不足"}
        </p>
        <p className="mt-2 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {courseStats.summary.pace_note}
        </p>
      </div>
      <div className="rounded-3xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p className="text-sm font-black text-slate-950">血統適性ランキング</p>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          本レース条件（{conditionLabel}）で関連する適性軸のみ評価しています。経験則ベースの参考情報です。
        </p>
        {rankedHorses.length ? (
          <div className="mt-3 space-y-2">
            {rankedHorses.map((horse) => (
              <div key={`${horse.umaban}-${horse.horse_name}-sire`} className="rounded-2xl bg-slate-50 px-3 py-2">
                <div className="flex items-start justify-between gap-2">
                  <span className="min-w-0 text-sm text-slate-800">
                    <span className="mr-1 text-lg font-black text-slate-950">{horse.sire_aptitude_summary}</span>
                    <span className="font-bold">{horse.umaban || "-"} {horse.horse_name}</span>
                    <span className="block text-xs text-slate-500">
                      父: {stripPedigreeDisplayName(horse.sire_name) || "-"}
                      {horse.broodmare_sire_name ? ` / 母父: ${stripPedigreeDisplayName(horse.broodmare_sire_name) || "-"}` : ""}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs font-bold text-slate-500">
                    {horse.sire_aptitude_score ?? 0}/{horse.sire_aptitude_max_score ?? 0}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1 text-xs">
                  {Object.entries(horse.sire_aptitude_marks ?? {}).map(([axis, mark]) => (
                    <span key={axis} className="rounded-full bg-white px-2 py-0.5 font-bold text-slate-700 ring-1 ring-slate-200">
                      {SIRE_AXIS_LABEL[axis] ?? axis}{mark}
                    </span>
                  ))}
                  {horse.broodmare_sire_aptitude_summary ? (
                    <span className="rounded-full bg-white px-2 py-0.5 font-bold text-slate-700 ring-1 ring-slate-200">
                      母父{horse.broodmare_sire_aptitude_summary}
                    </span>
                  ) : null}
                </div>
                {horse.sire_aptitude_notes ? (
                  <p className="mt-2 text-xs leading-5 text-slate-500">{horse.sire_aptitude_notes}</p>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-3 rounded-2xl bg-slate-50 px-3 py-2 text-xs text-slate-500">
            血統DBに登録済みの種牡馬がまだ見つかっていません。事前キャッシュ生成後に表示されます。
          </p>
        )}
        {unregisteredSires.length > 0 ? (
          <p className="mt-3 text-xs leading-5 text-amber-700">
            血統データ未登録（事前追加推奨）: {unregisteredSires.join("、")}
          </p>
        ) : null}
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
      <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p className="text-sm font-black text-slate-900">馬体重別成績割合</p>
        {courseStats.body_weight_stats?.length ? (
          <div className="mt-3 space-y-2">
            {courseStats.body_weight_stats.map((row) => (
              <div key={String(row.label)} className="grid grid-cols-5 gap-1 rounded-xl bg-slate-50 px-2 py-2 text-center text-[11px] text-slate-700">
                <span className="font-black text-slate-900">{formatBodyWeightBucket(String(row.label ?? "")) || "-"}</span>
                <span>1着 {String(row.win_rate ?? "0")}%</span>
                <span>複勝 {String(row.top3_rate ?? "0")}%</span>
                <span>外 {String(row.outside_top3_rate ?? "0")}%</span>
                <span>{String(row.starts ?? "0")}頭</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">
            馬体重別成績はサンプル不足または未取得です。
          </p>
        )}
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

type PaddockAdjustedRankingItem = BetRankingItem & {
  adjusted_score: number;
  paddock_bonus: number;
  paddock_reason: string;
};

function adjustRankingWithPaddockNotes(
  ranking: BetRankingItem[],
  entry: RaceEntryResponse | null,
  paddockNotes: PaddockNotes,
): PaddockAdjustedRankingItem[] {
  const horseKeyByRankingKey = new Map<string, string>();
  (entry?.horses ?? []).forEach((horse) => {
    const horseKey = stableHorseMarkKey(horse.umaban, horse.horse_name);
    horseKeyByRankingKey.set(`${horse.umaban || ""}::${horse.horse_name || ""}`, horseKey);
    horseKeyByRankingKey.set(`::${horse.horse_name || ""}`, horseKey);
  });
  return ranking
    .map((item) => {
      const horseKey =
        horseKeyByRankingKey.get(`${item.umaban || ""}::${item.horse_name || ""}`) ??
        horseKeyByRankingKey.get(`::${item.horse_name || ""}`) ??
        stableHorseMarkKey(item.umaban, item.horse_name);
      const noteBonus = paddockNoteBonus(paddockNotes[horseKey]);
      return {
        ...item,
        paddock_bonus: noteBonus.bonus,
        paddock_reason: noteBonus.reason,
        adjusted_score: Number((item.score + noteBonus.bonus).toFixed(3)),
      };
    })
    .sort((a, b) => {
      if (b.adjusted_score !== a.adjusted_score) return b.adjusted_score - a.adjusted_score;
      return b.score - a.score;
    });
}

function BetTab({
  betPlan,
  entry,
  paddockNotes,
  researchParsed,
  researchDrift,
  isRestoringResearch,
}: {
  betPlan: BetPlanResponse | null;
  entry: RaceEntryResponse | null;
  paddockNotes: PaddockNotes;
  researchParsed: ResearchParsed | null;
  researchDrift: ResearchDrift;
  isRestoringResearch: boolean;
}) {
  if (!betPlan) {
    return <EmptyCard message="買い目候補を取得中です。" />;
  }
  const adjustedRanking = adjustRankingWithPaddockNotes(betPlan.ranking, entry, paddockNotes);
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
          {adjustedRanking.slice(0, 8).map((item, idx) => (
            <div key={`${item.horse_name}-${idx}`} className="flex items-center justify-between rounded-xl bg-slate-50 px-3 py-2">
              <div>
                <p className="text-sm font-black text-slate-900">
                  {idx + 1}. {item.horse_name}
                </p>
                <p className="text-xs text-slate-500">
                  {item.umaban || "-"}番 / {item.style || "-"} / {item.reason}
                  {item.paddock_reason ? ` / 現地${item.paddock_reason}` : ""}
                </p>
              </div>
              <div className="shrink-0 text-right">
                {item.paddock_bonus ? (
                  <p className={`text-[10px] font-black ${item.paddock_bonus > 0 ? "text-emerald-700" : "text-rose-700"}`}>
                    現地{item.paddock_bonus > 0 ? "+" : ""}
                    {Math.round(item.paddock_bonus * 100)}
                  </p>
                ) : null}
                <p className="text-sm font-black text-emerald-700">{formatCandidateIndex(item.adjusted_score)}</p>
                <p className="text-[10px] font-bold text-slate-400">候補指数</p>
              </div>
            </div>
          ))}
        </div>
      </div>
      <ResearchDriftSummary drift={researchDrift} />
      {researchParsed ? <ResearchAiEvaluation parsed={researchParsed} /> : null}
      {!researchParsed && isRestoringResearch ? (
        <div className="rounded-2xl bg-amber-50 p-4 text-xs font-bold text-amber-900 shadow-sm ring-1 ring-amber-100">
          Deep Research のサーバーバックアップを確認中...
        </div>
      ) : null}
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

function ResearchDriftSummary({ drift }: { drift: ResearchDrift }) {
  if (!drift.has_warning) return null;
  return (
    <div className="rounded-2xl bg-amber-100 p-4 text-xs text-amber-950 shadow-sm ring-1 ring-amber-300">
      <p className="text-sm font-black">⚠ Deep Research 前提のズレ検知</p>
      {drift.odds_drifts
        .filter((item) => item.severity === "warn" || item.severity === "critical")
        .map((item) => (
          <p key={`${item.umaban}-${item.assumed_odds}-${item.current_odds}`} className="mt-2 leading-5">
            {item.umaban}番 想定 {item.assumed_odds.toFixed(1)} -&gt; 当日 {item.current_odds.toFixed(1)} ({item.ratio > 0 ? "+" : ""}
            {(item.ratio * 100).toFixed(0)}%
            {item.recalc_ev != null ? `, EV ${item.assumed_ev?.toFixed(2) ?? "-"}->${item.recalc_ev.toFixed(2)}` : ""})
          </p>
        ))}
      {drift.bias_drift?.conflict ? (
        <p className="mt-2 leading-5">
          想定「{drift.bias_drift.assumed}」 vs 当日「{drift.bias_drift.current || "-"}」
        </p>
      ) : null}
    </div>
  );
}

function ResearchAiEvaluation({ parsed }: { parsed: ResearchParsed }) {
  const hasContent =
    parsed.pace_label ||
    parsed.course_note ||
    parsed.tickets.length > 0 ||
    parsed.scratched.length > 0 ||
    parsed.max_payout_scenario;
  if (!hasContent) return null;
  return (
    <div className="rounded-2xl bg-amber-50 p-4 shadow-sm ring-1 ring-amber-200">
      <p className="text-sm font-black text-amber-950">AI 評価（Deep Research）</p>
      {parsed.pace_label ? <p className="mt-2 text-xs leading-5 text-amber-900">展開: {parsed.pace_label}</p> : null}
      {parsed.course_note ? <p className="mt-1 text-xs leading-5 text-amber-900">コース: {parsed.course_note}</p> : null}
      {parsed.tickets.length ? (
        <div className="mt-3 space-y-2">
          <p className="text-xs font-black text-amber-900">AI推奨買い目</p>
          {parsed.tickets.map((ticket, index) => (
            <div key={`${ticket.bet_type}-${index}`} className="rounded-xl bg-white/80 px-3 py-2 text-xs text-amber-950">
              <span className="font-black">{ticket.bet_type}</span> {formatParsedTicket(ticket)}
              {ticket.amount_yen ? ` / ${ticket.amount_yen}円` : ""}
              {ticket.reason ? <p className="mt-1 text-[11px] leading-4 text-amber-800">{ticket.reason}</p> : null}
            </div>
          ))}
        </div>
      ) : null}
      {parsed.scratched.length ? (
        <div className="mt-3 rounded-xl bg-white/70 px-3 py-2 text-xs text-amber-950">
          <span className="font-black">消し馬:</span>{" "}
          {parsed.scratched.map((item) => `${item.umaban}番${item.horse_name ? ` ${item.horse_name}` : ""}`).join(" / ")}
        </div>
      ) : null}
      {parsed.max_payout_scenario ? (
        <p className="mt-3 rounded-xl bg-white/70 px-3 py-2 text-xs leading-5 text-amber-900">
          最大回収シナリオ: {parsed.max_payout_scenario}
        </p>
      ) : null}
    </div>
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
