"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { stableHorseMarkKey, useHorseMarksMulti, type HorseMark } from "@/hooks/use-horse-marks";
import type {
  BetPlanResponse,
  BetRankingItem,
  ExternalSnapshot,
  RaceCourseStatsResponse,
  RaceEntryResponse,
  SameDaySheetRace,
  SameDaySheetResponse,
  TrackBias,
  UpcomingRace,
} from "@/lib/api/types";

type SameDaySheetClientProps = {
  date: string;
  venue: string;
  sheet: SameDaySheetResponse | null;
  error: string | null;
};

type RaceDetailCachePayload = {
  savedAt: string;
  savedAtIso?: string;
  serverGeneratedAt?: string;
  race: UpcomingRace;
  entry: RaceEntryResponse | null;
  courseStats: RaceCourseStatsResponse | null;
  betPlan: BetPlanResponse | null;
  trackBias?: TrackBias | null;
  externalSnapshot?: ExternalSnapshot | null;
};

const DETAIL_CACHE_PREFIX = "keiba:same-day:race-detail:v3:";
const DETAIL_CACHE_EVENT = "keiba:same-day-detail-cache-updated";
const DETAIL_CACHE_TTL_DAYS = 7;

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

function formatOdds(value: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "未公開";
  return value.toFixed(1);
}

function formatCandidateIndex(value: number): string {
  if (!Number.isFinite(value)) return "-";
  return `${Math.round(value * 100)}`;
}

function formatOptionalIndex(value?: number | null): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return formatCandidateIndex(value);
}

function shoshoFlagLabels(flags?: { label: string }[]): string {
  return flags?.map((flag) => flag.label).filter(Boolean).join("・") || "";
}

function raceShapeText(shape?: Record<string, unknown>): string {
  const parts: string[] = [];
  const pace = shape?.pace_pattern;
  const hatsuran = shape?.hatsuran_do;
  if (typeof pace === "string" && pace) parts.push(`展開 ${pace}`);
  if (typeof hatsuran === "number" && Number.isFinite(hatsuran)) parts.push(`波乱${Math.round(hatsuran * 100)}%`);
  return parts.join(" / ");
}

function oddsRecalcText(entry: RaceEntryResponse | null): string {
  const updatedAt = entry?.odds_updated_at || entry?.body_updated_at;
  return updatedAt ? `買い目は最新オッズで再計算 ${updatedAt}` : "買い目はキャッシュ済みオッズで計算";
}

function biasConfidenceLabel(confidence?: string): string {
  if (confidence === "high") return "高";
  if (confidence === "medium") return "中";
  if (confidence === "provisional") return "暫定";
  return "サンプル不足";
}

function biasConfidenceClass(confidence?: string): string {
  if (confidence === "high") return "bg-emerald-100 text-emerald-800";
  if (confidence === "medium") return "bg-sky-100 text-sky-800";
  if (confidence === "provisional") return "bg-amber-100 text-amber-800";
  return "bg-slate-100 text-slate-600";
}

function wakuNumber(value: string): string {
  const match = String(value || "").match(/\d+/);
  return match?.[0] ?? "";
}

function wakuBadgeClass(value: string): string {
  return WAKU_BADGE_CLASS[wakuNumber(value)] ?? "border-slate-300 bg-slate-100 text-slate-700";
}

function detailCacheKey(race: UpcomingRace): string {
  return `${DETAIL_CACHE_PREFIX}${race.race_id || race.race_key}`;
}

function raceTitle(item: SameDaySheetRace): string {
  const race = item.race;
  return `${race.race_number || "-"} ${race.race_name} (${race.surface}${race.distance})`;
}

function raceDetailHref(item: SameDaySheetRace): string {
  const race = item.race;
  const params = new URLSearchParams({
    mode: "same-day",
    race_id: race.race_id ?? "",
    date: race.date_iso,
    venue: race.venue,
    race_name: race.race_name,
    race_number: race.race_number ?? "",
    distance: race.distance,
    surface: race.surface,
    grade: race.grade,
  });
  return `/races/${encodeURIComponent(race.race_key)}?${params.toString()}`;
}

function detailCacheFromItem(item: SameDaySheetRace, savedAt: string, savedAtIso: string, serverGeneratedAt?: string): RaceDetailCachePayload {
  return {
    savedAt,
    savedAtIso,
    serverGeneratedAt,
    race: item.race,
    entry: item.entry,
    courseStats: item.course_stats,
    betPlan: item.bet_plan,
    trackBias: item.track_bias ?? null,
    externalSnapshot: null,
  };
}

function freshnessMs(value?: string): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function readDetailCache(item: SameDaySheetRace): RaceDetailCachePayload | null {
  try {
    const raw = window.localStorage.getItem(detailCacheKey(item.race));
    if (!raw) return null;
    const payload = JSON.parse(raw) as RaceDetailCachePayload;
    if (!payload?.entry) return null;
    return payload;
  } catch {
    return null;
  }
}

function mergeDetailCache(item: SameDaySheetRace, serverGeneratedAt?: string): SameDaySheetRace {
  const cached = readDetailCache(item);
  if (!cached) return item;
  if (serverGeneratedAt && !cached.serverGeneratedAt) {
    return item;
  }
  if (freshnessMs(serverGeneratedAt) > freshnessMs(cached.serverGeneratedAt || cached.savedAtIso)) {
    return item;
  }
  return {
    ...item,
    entry: cached.entry,
    course_stats: cached.courseStats,
    bet_plan: cached.betPlan,
    track_bias: cached.trackBias ?? item.track_bias,
  };
}

function latestRaceUpdatedAt(item: SameDaySheetRace): string {
  const entry = item.entry;
  if (!entry) return "";
  return entry.odds_updated_at || entry.body_updated_at || "";
}

function saveAllDetails(races: SameDaySheetRace[], serverGeneratedAt?: string): number {
  const now = new Date();
  const savedAt = now.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  const savedAtIso = now.toISOString();
  let count = 0;
  for (const item of races) {
    if (!item.entry) continue;
    const existing = readDetailCache(item);
    const payload = detailCacheFromItem(item, savedAt, savedAtIso, serverGeneratedAt);
    payload.externalSnapshot = existing?.externalSnapshot ?? null;
    window.localStorage.setItem(detailCacheKey(item.race), JSON.stringify(payload));
    count += 1;
  }
  window.dispatchEvent(new Event(DETAIL_CACHE_EVENT));
  return count;
}

function subscribeDetailCache(callback: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(DETAIL_CACHE_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(DETAIL_CACHE_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

function detailCacheSnapshot(): string {
  if (typeof window === "undefined") return "server";
  try {
    return Object.keys(window.localStorage)
      .filter((key) => key.startsWith(DETAIL_CACHE_PREFIX))
      .sort()
      .map((key) => `${key}:${window.localStorage.getItem(key)?.length ?? 0}`)
      .join("|");
  } catch {
    return "unavailable";
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
    // Keep the page usable even when localStorage is blocked.
  }
}

export function SameDaySheetClient({ date, venue, sheet, error }: SameDaySheetClientProps) {
  const [saveMessage, setSaveMessage] = useState("");
  const [refreshingVolatile, setRefreshingVolatile] = useState(false);
  const cacheSnapshot = useSyncExternalStore(subscribeDetailCache, detailCacheSnapshot, () => "server");
  useEffect(() => {
    cleanupOldDetailCaches();
  }, []);
  const races = useMemo(() => {
    void cacheSnapshot;
    const base = sheet?.races ?? [];
    if (typeof window === "undefined" || cacheSnapshot === "server") return base;
    return base.map((item) => mergeDetailCache(item, sheet?.generated_at));
  }, [sheet, cacheSnapshot]);
  const raceIds = useMemo(() => races.map((item) => item.race.race_id || item.race.race_key), [races]);
  const marksByRace = useHorseMarksMulti(raceIds);

  const totalWarnings = useMemo(
    () =>
      races.reduce((count, item) => {
        const entryWarnings = item.entry?.warnings.length ?? 0;
        const betWarnings = item.bet_plan?.warnings.length ?? 0;
        return count + entryWarnings + betWarnings + (item.error ? 1 : 0);
      }, 0),
    [races],
  );
  function handleSaveAll() {
    try {
      const count = saveAllDetails(races, sheet?.generated_at);
      setSaveMessage(`${count}R分をこの端末に保存しました`);
    } catch {
      setSaveMessage("端末保存に失敗しました。ブラウザの空き容量を確認してください。");
    }
  }

  async function handleVolatileRefreshAll() {
    setRefreshingVolatile(true);
    setSaveMessage("");
    try {
      const params = new URLSearchParams({ date, venue, budget_yen: "3000" });
      const response = await fetch(`/api/v1/races/same-day-sheet/refresh-volatile?${params.toString()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      window.location.href = `/same-day-sheet?date=${encodeURIComponent(date)}&venue=${encodeURIComponent(venue)}`;
    } catch (refreshError) {
      setSaveMessage(refreshError instanceof Error ? `軽量更新に失敗しました: ${refreshError.message}` : "軽量更新に失敗しました");
      setRefreshingVolatile(false);
    }
  }

  return (
    <main className="mx-auto min-h-screen w-full max-w-md bg-slate-50 px-4 pb-10 pt-5">
      <div className="flex items-center justify-between gap-3">
        <Link href="/" className="min-h-11 rounded-xl border border-slate-300 bg-white px-3 py-3 text-xs font-bold text-slate-700">
          トップへ戻る
        </Link>
        <Link
          href={`/same-day-sheet?date=${encodeURIComponent(date)}&venue=${encodeURIComponent(venue)}`}
          className="min-h-11 rounded-xl bg-emerald-500 px-3 py-3 text-xs font-black text-slate-950"
        >
          シート読込
        </Link>
      </div>

      <section className="mt-4 rounded-3xl bg-slate-950 p-5 text-white shadow-lg">
        <p className="text-xs font-black text-emerald-200">現地用 全Rシート</p>
        <h1 className="mt-2 text-2xl font-black">
          {venue} {date}
        </h1>
        <p className="mt-2 text-sm text-slate-200">
          候補馬を先に見て、直前はオッズと馬体重だけ更新するための一覧です。
        </p>
        {sheet ? (
          <p className="mt-3 rounded-2xl bg-white/10 px-3 py-2 text-xs text-slate-100">
            {sheet.race_count}R / 生成 {sheet.generated_at} / 注意 {totalWarnings}件
          </p>
        ) : null}
      </section>

      <section className="mt-3 rounded-2xl bg-white p-3 shadow-sm ring-1 ring-slate-200">
        <form action="/same-day-sheet" className="grid grid-cols-2 gap-2">
          <label className="text-xs font-bold text-slate-600">
            開催日
            <input
              type="date"
              name="date"
              defaultValue={date}
              className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-base"
            />
          </label>
          <label className="text-xs font-bold text-slate-600">
            会場
            <input
              name="venue"
              defaultValue={venue}
              className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-base"
            />
          </label>
          <button
            type="submit"
            className="col-span-2 mt-1 min-h-12 rounded-xl bg-slate-900 px-4 py-3 text-sm font-black text-white"
          >
            この条件で表示
          </button>
        </form>
        {error ? <p className="mt-2 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p> : null}
        <button
          type="button"
          onClick={() => {
            void handleVolatileRefreshAll();
          }}
          disabled={refreshingVolatile}
          className="mt-3 block min-h-12 w-full rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-center text-sm font-black text-amber-900 disabled:opacity-60"
        >
          オッズ・馬体重公開後に全Rを軽量更新
        </button>
        <button
          type="button"
          onClick={handleSaveAll}
          disabled={!races.length}
          className="mt-2 min-h-12 w-full rounded-xl bg-emerald-500 px-4 py-3 text-sm font-black text-slate-950 shadow-sm shadow-emerald-200 disabled:opacity-50"
        >
          全R詳細をこの端末に保存
        </button>
        {saveMessage ? <p className="mt-2 rounded-xl bg-emerald-50 px-3 py-2 text-xs text-emerald-800">{saveMessage}</p> : null}
      </section>

      <div className="mt-4 space-y-3">
        {races.map((item) => (
          <RaceSheetCard
            key={item.race.race_key}
            item={item}
            horseMarks={marksByRace[item.race.race_id || item.race.race_key] || {}}
          />
        ))}
      </div>
    </main>
  );
}

function RaceSheetCard({ item, horseMarks }: { item: SameDaySheetRace; horseMarks: Record<string, HorseMark> }) {
  const entry = item.entry;
  const betPlan = item.bet_plan;
  const ranking = betPlan?.ranking.slice(0, 4) ?? [];
  const oddsCount = entry?.horses.filter((horse) => horse.odds !== null).length ?? 0;
  const bodyCount = entry?.horses.filter((horse) => horse.body_weight).length ?? 0;
  const updatedAt = latestRaceUpdatedAt(item);
  const shapeText = raceShapeText(betPlan?.recommendations?.race_shape);
  const abilityTicket = betPlan?.tickets?.[0] ?? null;
  const valueTicket = betPlan?.recommendations?.tickets?.[0] ?? null;
  const abilityFallback = abilityTicket ? null : ranking[0] ?? null;

  return (
    <article className="rounded-3xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-black text-slate-950">{raceTitle(item)}</h2>
          <p className="mt-1 text-xs text-slate-500">
            発走 {entry?.start_time || "-"} / {entry?.horses.length ?? 0}頭 / {item.race.grade}
          </p>
          {updatedAt ? <p className="mt-1 text-[11px] font-bold text-emerald-700">更新 {updatedAt}</p> : null}
        </div>
        <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-black text-white">
          {item.race.race_number || "-"}
        </span>
      </div>

      {item.error ? <p className="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700">{item.error}</p> : null}

      <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
        <div className="rounded-2xl bg-emerald-50 px-2 py-2 text-emerald-800">
          <p className="font-black">脚質</p>
          <p className="mt-1">{entry?.style_distribution_label || "-"}</p>
        </div>
        <div className="rounded-2xl bg-sky-50 px-2 py-2 text-sky-800">
          <p className="font-black">オッズ</p>
          <p className="mt-1">{oddsCount}頭</p>
        </div>
        <div className="rounded-2xl bg-amber-50 px-2 py-2 text-amber-800">
          <p className="font-black">馬体重</p>
          <p className="mt-1">{bodyCount}頭</p>
        </div>
      </div>

      {entry?.warnings.length ? (
        <div className="mt-3 space-y-1">
          {entry.warnings.map((warning) => (
            <p key={warning} className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {warning}
            </p>
          ))}
        </div>
      ) : null}

      {item.track_bias?.summary_label ? (
        <div className="mt-3 rounded-2xl bg-indigo-50 px-3 py-2 text-xs text-indigo-800">
          <span className={`mr-2 rounded-full px-2 py-0.5 text-[10px] font-black ${biasConfidenceClass(item.track_bias.confidence)}`}>
            {biasConfidenceLabel(item.track_bias.confidence)}
          </span>
          <span className="font-black">バイアス:</span> {item.track_bias.summary_label}
          <span className="ml-2 text-[10px] opacity-70">
            ({item.track_bias.sample_size}R{item.track_bias.fallback_used ? " / 同会場他コース" : ""})
          </span>
        </div>
      ) : null}

      <div className="mt-4 space-y-2">
        {ranking.map((rankingItem, idx) => (
          <RankingRow
            key={`${rankingItem.horse_name}-${idx}`}
            item={rankingItem}
            index={idx + 1}
            mark={horseMarks[stableHorseMarkKey(rankingItem.umaban, rankingItem.horse_name)] || ""}
          />
        ))}
      </div>

      {betPlan ? (
        <div className="mt-3 space-y-1 rounded-2xl bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
          <p className="font-black text-emerald-800">{oddsRecalcText(entry)}</p>
          <p className="line-clamp-1">
            <span className="font-black">能力上位:</span>{" "}
            {abilityTicket ? (
              <>
                {abilityTicket.type} <span className="text-emerald-700">{abilityTicket.selection}</span>
              </>
            ) : abilityFallback ? (
              <>
                {abilityFallback.umaban || "-"}番 {abilityFallback.horse_name}
              </>
            ) : (
              "詳細で確認"
            )}
          </p>
          <p className="line-clamp-1">
            <span className="font-black">妙味推奨:</span>{" "}
            {valueTicket ? (
              <>
                {valueTicket.type} {valueTicket.point_note || ""}
                <span className="ml-1 text-emerald-700">{valueTicket.selection}</span>
              </>
            ) : (
              betPlan.recommendations?.note || "詳細で確認"
            )}
          </p>
          {shapeText ? <p className="line-clamp-1 text-[10px] font-bold text-emerald-700">{shapeText}</p> : null}
        </div>
      ) : null}

      <Link
        href={raceDetailHref(item)}
        className="mt-4 block rounded-2xl bg-slate-900 px-4 py-3 text-center text-sm font-black text-white"
      >
        このRの詳細を見る
      </Link>
    </article>
  );
}

function RankingRow({ item, index, mark }: { item: BetRankingItem; index: number; mark: HorseMark | "" }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-slate-50 px-3 py-2">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-sm font-black text-slate-950">
          {item.is_value_top5 ? <span className="text-amber-500">★</span> : null}
          <span>
            {index}. {item.horse_name}
          </span>
          {mark ? (
            <span className={`inline-flex min-w-7 items-center justify-center rounded-full px-2 py-0.5 text-[11px] font-black ${mark === "消" ? "bg-slate-200 text-slate-500" : "bg-rose-100 text-rose-700"}`}>
              {mark}
            </span>
          ) : null}
          {item.waku ? (
            <span className={`inline-flex min-w-7 items-center justify-center rounded-full border px-2 py-0.5 text-[11px] font-black ${wakuBadgeClass(item.waku)}`}>
              {item.waku}枠
            </span>
          ) : null}
          {item.danger_flags?.length ? (
            <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-black text-rose-700">⚠</span>
          ) : null}
          {item.value_flags?.length ? (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-black text-amber-800">🎯</span>
          ) : null}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          {item.umaban || "-"}番 / {item.style || "-"} / 単勝 {formatOdds(item.odds)}
        </p>
        {(item.danger_flags?.length || item.value_flags?.length) ? (
          <p className="mt-1 line-clamp-1 text-[10px] font-semibold text-slate-500">
            {[shoshoFlagLabels(item.value_flags), shoshoFlagLabels(item.danger_flags)].filter(Boolean).join(" / ")}
          </p>
        ) : null}
      </div>
      <div className="shrink-0 text-right">
        <p className="text-sm font-black text-emerald-700">{formatCandidateIndex(item.score)}</p>
        <p className="text-[10px] font-black text-amber-700">妙 {formatOptionalIndex(item.value_score)}</p>
        {item.bias_bonus ? (
          <p className={`text-[10px] font-black ${item.bias_bonus > 0 ? "text-emerald-700" : "text-rose-700"}`}>
            {item.bias_bonus > 0 ? "+" : ""}
            {(item.bias_bonus * 100).toFixed(0)}
          </p>
        ) : null}
        <p className="text-[10px] font-bold text-slate-400">候補指数</p>
      </div>
    </div>
  );
}
