"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

const STORAGE_KEY_PREFIX = "keiba:same-day:odds-history:";
const ODDS_HISTORY_EVENT = "keiba:same-day-odds-history-updated";
const TTL_MS = 6 * 60 * 60 * 1000;
const MAX_SNAPSHOTS = 10;

export type OddsSnapshot = {
  at: number;
  odds: Record<string, number>;
};

type OddsHistoryStore = {
  savedAt: number;
  snapshots: OddsSnapshot[];
};

export type OddsTrend = {
  current: number | null;
  prev: number | null;
  delta: number;
  ratio: number;
  direction: "up" | "down" | "flat";
  severity: "minor" | "warn" | "critical";
};

function storageKey(raceId: string): string {
  return `${STORAGE_KEY_PREFIX}${raceId}`;
}

export function oddsHash(odds: Record<string, number>): string {
  return Object.entries(odds)
    .filter(([key, value]) => key && Number.isFinite(value))
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([key, value]) => `${key}:${value.toFixed(2)}`)
    .join("|");
}

function emptyStore(): OddsHistoryStore {
  return { savedAt: 0, snapshots: [] };
}

function readStore(raceId: string): OddsHistoryStore {
  if (typeof window === "undefined" || !raceId) return emptyStore();
  try {
    const raw = window.localStorage.getItem(storageKey(raceId));
    if (!raw) return emptyStore();
    const payload = JSON.parse(raw) as OddsHistoryStore;
    if (!payload || typeof payload.savedAt !== "number" || !Array.isArray(payload.snapshots)) return emptyStore();
    if (Date.now() - payload.savedAt > TTL_MS) {
      window.localStorage.removeItem(storageKey(raceId));
      return emptyStore();
    }
    const snapshots = payload.snapshots
      .filter((snapshot) => snapshot && typeof snapshot.at === "number" && snapshot.odds && typeof snapshot.odds === "object")
      .map((snapshot) => ({
        at: snapshot.at,
        odds: Object.fromEntries(
          Object.entries(snapshot.odds)
            .map(([key, value]) => [String(key).replace(/^0+/, ""), Number(value)] as const)
            .filter(([key, value]) => key && Number.isFinite(value)),
        ),
      }))
      .filter((snapshot) => Object.keys(snapshot.odds).length > 0)
      .slice(-MAX_SNAPSHOTS);
    return { savedAt: payload.savedAt, snapshots };
  } catch {
    return emptyStore();
  }
}

function writeStore(raceId: string, snapshots: OddsSnapshot[]): void {
  if (typeof window === "undefined" || !raceId) return;
  const clean = snapshots
    .map((snapshot) => ({
      at: snapshot.at,
      odds: Object.fromEntries(
        Object.entries(snapshot.odds)
          .map(([key, value]) => [String(key).replace(/^0+/, ""), Number(value)] as const)
          .filter(([key, value]) => key && Number.isFinite(value)),
      ),
    }))
    .filter((snapshot) => Object.keys(snapshot.odds).length > 0)
    .slice(-MAX_SNAPSHOTS);
  if (!clean.length) {
    window.localStorage.removeItem(storageKey(raceId));
  } else {
    window.localStorage.setItem(storageKey(raceId), JSON.stringify({ savedAt: Date.now(), snapshots: clean }));
  }
  window.dispatchEvent(new Event(ODDS_HISTORY_EVENT));
}

function subscribeOddsHistory(callback: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(ODDS_HISTORY_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(ODDS_HISTORY_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

function trendFromValues(values: number[]): OddsTrend {
  const current = values.length ? values[values.length - 1] : null;
  const prev = values.length >= 2 ? values[values.length - 2] : null;
  if (current == null || prev == null || prev <= 0) {
    return { current, prev, delta: 0, ratio: 0, direction: "flat", severity: "minor" };
  }
  const delta = current - prev;
  const ratio = delta / prev;
  const abs = Math.abs(ratio);
  const direction = abs < 0.001 ? "flat" : delta > 0 ? "up" : "down";
  const severity = abs >= 0.2 ? "critical" : abs >= 0.1 ? "warn" : "minor";
  return { current, prev, delta, ratio, direction, severity };
}

export function useOddsHistory(raceId: string) {
  const snapshot = useSyncExternalStore(
    subscribeOddsHistory,
    () => JSON.stringify(readStore(raceId)),
    () => JSON.stringify(emptyStore()),
  );
  const store = useMemo(() => {
    try {
      return JSON.parse(snapshot) as OddsHistoryStore;
    } catch {
      return emptyStore();
    }
  }, [snapshot]);

  const pushSnapshot = useCallback(
    (oddsByUmaban: Record<string, number>) => {
      if (!raceId) return false;
      const clean = Object.fromEntries(
        Object.entries(oddsByUmaban)
          .map(([key, value]) => [String(key).replace(/^0+/, ""), Number(value)] as const)
          .filter(([key, value]) => key && Number.isFinite(value)),
      );
      if (!Object.keys(clean).length) return false;
      const current = readStore(raceId);
      const last = current.snapshots[current.snapshots.length - 1];
      if (last && oddsHash(last.odds) === oddsHash(clean)) return false;
      writeStore(raceId, [...current.snapshots, { at: Date.now(), odds: clean }]);
      return true;
    },
    [raceId],
  );

  const getSparkline = useCallback(
    (umaban: string) => {
      const key = String(umaban || "").replace(/^0+/, "");
      if (!key) return [];
      return store.snapshots
        .map((item) => item.odds[key])
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
    },
    [store.snapshots],
  );

  const getTrend = useCallback((umaban: string) => trendFromValues(getSparkline(umaban)), [getSparkline]);

  return {
    snapshots: store.snapshots,
    pushSnapshot,
    getTrend,
    getSparkline,
  };
}
