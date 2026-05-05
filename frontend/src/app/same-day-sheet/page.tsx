import { SameDaySheetClient } from "@/components/mobile/same-day-sheet-client";
import type { SameDaySheetResponse } from "@/lib/api/types";

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

async function getSheet(date: string, venue: string, refresh: boolean): Promise<SameDaySheetResponse> {
  const backendUrl = (process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
  const params = new URLSearchParams({ date, venue, budget_yen: "3000" });
  if (refresh) params.set("refresh", "true");

  const response = await fetch(`${backendUrl}/api/v1/races/same-day-sheet?${params.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`全Rシートの取得に失敗しました HTTP ${response.status}`);
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

  return <SameDaySheetClient date={date} venue={venue} sheet={sheet} error={error} />;
}
