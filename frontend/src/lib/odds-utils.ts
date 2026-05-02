import type { OddsHorse } from "@/lib/api/types";

export type OddsSortKey = "oddsAsc" | "oddsDesc" | "umabanAsc" | "nameAsc";
export type OddsLimit = "5" | "10" | "18" | "all";

export function parseOdds(value: number | null): number {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return Number.POSITIVE_INFINITY;
  }
  return value;
}

export function parseUmaban(value: string | null): number {
  if (!value) {
    return Number.POSITIVE_INFINITY;
  }
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    return Number.POSITIVE_INFINITY;
  }
  return parsed;
}

export function formatOdds(value: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(1);
}

export function oddsSortLabel(sortKey: OddsSortKey): string {
  if (sortKey === "oddsAsc") return "オッズ低い順";
  if (sortKey === "oddsDesc") return "オッズ高い順";
  if (sortKey === "umabanAsc") return "馬番順";
  return "馬名順";
}

export function filterAndSortOdds(
  horses: OddsHorse[] | undefined,
  options: {
    oddsSort: OddsSortKey;
    oddsLimit: OddsLimit;
    horseFilter: string;
    onlyWithOdds: boolean;
  },
): OddsHorse[] {
  let rows: OddsHorse[] = horses ? [...horses] : [];

  if (options.onlyWithOdds) {
    rows = rows.filter((horse) => Number.isFinite(parseOdds(horse.odds)));
  }

  const keyword = options.horseFilter.trim().toLowerCase();
  if (keyword) {
    rows = rows.filter((horse) => horse.horse_name.toLowerCase().includes(keyword));
  }

  rows.sort((a, b) => {
    if (options.oddsSort === "oddsAsc") return parseOdds(a.odds) - parseOdds(b.odds);
    if (options.oddsSort === "oddsDesc") return parseOdds(b.odds) - parseOdds(a.odds);
    if (options.oddsSort === "umabanAsc") return parseUmaban(a.umaban) - parseUmaban(b.umaban);
    return a.horse_name.localeCompare(b.horse_name, "ja");
  });

  if (options.oddsLimit === "all") {
    return rows;
  }

  const count = Number.parseInt(options.oddsLimit, 10);
  if (Number.isNaN(count)) {
    return rows;
  }
  return rows.slice(0, count);
}
