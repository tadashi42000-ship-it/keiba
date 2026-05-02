import Link from "next/link";

import type { BetRankingItem, SameDaySheetRace, SameDaySheetResponse } from "@/lib/api/types";

export const dynamic = "force-dynamic";

type SearchParams = Record<string, string | string[] | undefined>;

function firstValue(value: string | string[] | undefined, fallback: string): string {
  if (Array.isArray(value)) return value[0] ?? fallback;
  return value ?? fallback;
}

function todayIso(): string {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
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

function wakuNumber(value: string): string {
  const match = String(value || "").match(/\d+/);
  return match?.[0] ?? "";
}

function wakuBadgeClass(value: string): string {
  return WAKU_BADGE_CLASS[wakuNumber(value)] ?? "border-slate-300 bg-slate-100 text-slate-700";
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

async function getSheet(date: string, venue: string, refresh: boolean): Promise<SameDaySheetResponse> {
  const backendUrl = (process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
  const params = new URLSearchParams({ date, venue, budget_yen: "3000" });
  if (refresh) params.set("refresh", "true");

  const response = await fetch(`${backendUrl}/api/v1/races/same-day-sheet?${params.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`全Rシート取得失敗: HTTP ${response.status}`);
  }
  return (await response.json()) as SameDaySheetResponse;
}

export default async function SameDaySheetPage({
  searchParams,
}: {
  searchParams?: Promise<SearchParams>;
}) {
  const params = (await searchParams) ?? {};
  const date = firstValue(params.date, todayIso());
  const venue = firstValue(params.venue, "東京");
  const refresh = firstValue(params.refresh, "") === "true";

  let sheet: SameDaySheetResponse | null = null;
  let error: string | null = null;
  try {
    sheet = await getSheet(date, venue, refresh);
  } catch (fetchError) {
    error = fetchError instanceof Error ? fetchError.message : "全Rシートの取得に失敗しました";
  }

  const totalWarnings =
    sheet?.races.reduce((count, item) => {
      const entryWarnings = item.entry?.warnings.length ?? 0;
      const betWarnings = item.bet_plan?.warnings.length ?? 0;
      return count + entryWarnings + betWarnings + (item.error ? 1 : 0);
    }, 0) ?? 0;

  const refreshHref = `/same-day-sheet?date=${encodeURIComponent(date)}&venue=${encodeURIComponent(venue)}&refresh=true`;

  return (
    <main className="mx-auto min-h-screen w-full max-w-md bg-slate-50 px-4 pb-10 pt-5">
      <div className="flex items-center justify-between gap-3">
        <Link href="/" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-700">
          トップへ戻る
        </Link>
        <Link
          href={`/same-day-sheet?date=${encodeURIComponent(date)}&venue=${encodeURIComponent(venue)}`}
          className="rounded-xl bg-emerald-500 px-3 py-2 text-xs font-black text-slate-950"
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
            className="col-span-2 mt-1 rounded-xl bg-slate-900 px-3 py-2 text-xs font-black text-white"
          >
            この条件で表示
          </button>
        </form>
        {error ? <p className="mt-2 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p> : null}
        <Link
          href={refreshHref}
          className="mt-3 block rounded-xl border border-slate-300 bg-white px-3 py-2 text-center text-xs font-black text-slate-700"
        >
          オッズ・馬体重公開後に全Rを再生成
        </Link>
      </section>

      <div className="mt-4 space-y-3">
        {sheet?.races.map((item) => (
          <RaceSheetCard key={item.race.race_key} item={item} />
        ))}
      </div>
    </main>
  );
}

function RaceSheetCard({ item }: { item: SameDaySheetRace }) {
  const entry = item.entry;
  const betPlan = item.bet_plan;
  const ranking = betPlan?.ranking.slice(0, 4) ?? [];
  const oddsCount = entry?.horses.filter((horse) => horse.odds !== null).length ?? 0;
  const bodyCount = entry?.horses.filter((horse) => horse.body_weight).length ?? 0;

  return (
    <article className="rounded-3xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-black text-slate-950">{raceTitle(item)}</h2>
          <p className="mt-1 text-xs text-slate-500">
            発走 {entry?.start_time || "-"} / {entry?.horses.length ?? 0}頭 / {item.race.grade}
          </p>
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

      <div className="mt-4 space-y-2">
        {ranking.map((rankingItem, idx) => (
          <RankingRow key={`${rankingItem.horse_name}-${idx}`} item={rankingItem} index={idx + 1} />
        ))}
      </div>

      <Link
        href={raceDetailHref(item)}
        className="mt-4 block rounded-2xl bg-slate-900 px-4 py-3 text-center text-sm font-black text-white"
      >
        このRの詳細を見る
      </Link>
    </article>
  );
}

function RankingRow({ item, index }: { item: BetRankingItem; index: number }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-slate-50 px-3 py-2">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-sm font-black text-slate-950">
          <span>{index}. {item.horse_name}</span>
          {item.waku ? (
            <span className={`inline-flex min-w-7 items-center justify-center rounded-full border px-2 py-0.5 text-[11px] font-black ${wakuBadgeClass(item.waku)}`}>
              {item.waku}枠
            </span>
          ) : null}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          {item.umaban || "-"}番 / {item.style || "-"} / 単勝 {formatOdds(item.odds)}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p className="text-sm font-black text-emerald-700">{formatCandidateIndex(item.score)}</p>
        <p className="text-[10px] font-bold text-slate-400">候補指数</p>
      </div>
    </div>
  );
}
