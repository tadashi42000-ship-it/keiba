"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { getSameDayRaces } from "@/lib/api/client";
import type { UpcomingRace } from "@/lib/api/types";

import { StatusCard } from "./status-card";

function todayIso(): string {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function raceLabel(race: UpcomingRace): string {
  const number = race.race_number ? `${race.race_number} ` : "";
  return `${number}${race.race_name} (${race.surface}${race.distance})`;
}

function raceDetailHref(race: UpcomingRace): string {
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

export function RaceWorkbenchCard() {
  const [date, setDate] = useState(todayIso());
  const [venue, setVenue] = useState("");
  const [races, setRaces] = useState<UpcomingRace[]>([]);
  const [venues, setVenues] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const visibleRaces = useMemo(() => {
    if (!venue) return races;
    return races.filter((race) => race.venue === venue);
  }, [races, venue]);

  async function loadSameDayRaces() {
    setLoading(true);
    setError(null);
    try {
      const response = await getSameDayRaces(date);
      setRaces(response.races);
      setVenues(response.venues);
      if (!venue && response.venues.length > 0) {
        setVenue(response.venues[0]);
      }
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "当日レース一覧の取得に失敗しました");
    } finally {
      setLoading(false);
    }
  }

  return (
    <StatusCard
      title="当日レースモード"
      description="現地で30分前に確認する出馬表・脚質・買い目候補"
      status={loading ? "loading" : error ? "error" : "ok"}
    >
      <div className="space-y-4">
        <div className="rounded-2xl bg-slate-50 p-3">
          <div className="grid grid-cols-1 gap-2">
            <label className="text-xs font-semibold text-slate-600">
              開催日
              <input
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-3 text-base"
              />
            </label>
            <button
              type="button"
              onClick={() => {
                void loadSameDayRaces();
              }}
              className="rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white disabled:opacity-60"
              disabled={loading}
            >
              {loading ? "取得中..." : "当日レース一覧を取得"}
            </button>
          </div>
          {error ? <p className="mt-2 text-xs text-rose-700">{error}</p> : null}
          <p className="mt-2 text-xs text-slate-500">取得件数: {races.length}件</p>
        </div>

        {venues.length > 0 ? (
          <div className="flex gap-2 overflow-x-auto pb-1">
            {venues.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setVenue(item)}
                className={`shrink-0 rounded-full border px-3 py-2 text-sm font-semibold ${
                  venue === item
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-300 bg-white text-slate-700"
                }`}
              >
                {item}
              </button>
            ))}
          </div>
        ) : null}

        {venue && visibleRaces.length > 0 ? (
          <Link
            href={`/same-day-sheet?date=${encodeURIComponent(date)}&venue=${encodeURIComponent(venue)}`}
            className="block rounded-2xl bg-sky-600 px-4 py-3 text-center text-sm font-black text-white"
          >
            {venue}の全Rシートを見る
          </Link>
        ) : null}

        {races.length === 0 && !loading ? (
          <p className="rounded-xl border border-dashed border-slate-300 p-3 text-sm text-slate-500">
            開催日を選んで「当日レース一覧を取得」を押してください。
          </p>
        ) : null}

        <div className="space-y-2">
          {visibleRaces.map((race) => {
            const unresolved = !race.race_id;
            return (
              <div key={race.race_key} className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-black text-slate-900">{raceLabel(race)}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {race.date_str} / {race.venue} / {race.grade}
                    </p>
                  </div>
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">
                    {race.race_number || "-"}
                  </span>
                </div>
                {unresolved ? (
                  <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    race_id未解決です。開催情報の公開後に再取得してください。
                  </p>
                ) : (
                  <Link
                    href={raceDetailHref(race)}
                    className="mt-3 block rounded-xl bg-emerald-600 px-4 py-3 text-center text-sm font-bold text-white"
                  >
                    このレースを開く
                  </Link>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </StatusCard>
  );
}
