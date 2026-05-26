"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

export type HorseMark = "◎" | "〇" | "△" | "消";

export const HORSE_MARKS: HorseMark[] = ["◎", "〇", "△", "消"];
export const MARK_ORDER: Record<HorseMark | "", number> = {
  "◎": 0,
  "〇": 1,
  "△": 2,
  "": 3,
  "消": 4,
};

const STORAGE_KEY_PREFIX = "keiba:same-day:horse-marks:";
const MARK_EVENT = "keiba:same-day-marks-updated";
const TTL_MS = 7 * 24 * 60 * 60 * 1000;

type StoredMarks = {
  savedAt: number;
  marks: Record<string, HorseMark>;
};

function storageKey(raceId: string): string {
  return `${STORAGE_KEY_PREFIX}${raceId}`;
}

export function stableHorseMarkKey(umaban?: string | null, horseName?: string | null): string {
  const numberKey = String(umaban || "").trim().replace(/^0+/, "");
  if (numberKey) return numberKey;
  return String(horseName || "").trim();
}

function isHorseMark(value: unknown): value is HorseMark {
  return value === "◎" || value === "〇" || value === "△" || value === "消";
}

function readMarks(raceId: string): Record<string, HorseMark> {
  if (typeof window === "undefined" || !raceId) return {};
  try {
    const raw = window.localStorage.getItem(storageKey(raceId));
    if (!raw) return {};
    const payload = JSON.parse(raw) as StoredMarks;
    if (!payload || typeof payload.savedAt !== "number" || !payload.marks) return {};
    if (Date.now() - payload.savedAt > TTL_MS) {
      window.localStorage.removeItem(storageKey(raceId));
      return {};
    }
    return Object.fromEntries(
      Object.entries(payload.marks).filter(([, mark]) => isHorseMark(mark)),
    ) as Record<string, HorseMark>;
  } catch {
    return {};
  }
}

function writeMarks(raceId: string, marks: Record<string, HorseMark>): void {
  if (typeof window === "undefined" || !raceId) return;
  const cleanMarks = Object.fromEntries(
    Object.entries(marks).filter(([key, mark]) => key && isHorseMark(mark)),
  ) as Record<string, HorseMark>;
  if (Object.keys(cleanMarks).length === 0) {
    window.localStorage.removeItem(storageKey(raceId));
  } else {
    window.localStorage.setItem(storageKey(raceId), JSON.stringify({ savedAt: Date.now(), marks: cleanMarks }));
  }
  window.dispatchEvent(new Event(MARK_EVENT));
}

function subscribeMarks(callback: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(MARK_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(MARK_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

export function useHorseMarks(raceId: string) {
  const snapshot = useSyncExternalStore(
    subscribeMarks,
    () => JSON.stringify(readMarks(raceId)),
    () => "{}",
  );
  const marks = useMemo(() => {
    try {
      return JSON.parse(snapshot) as Record<string, HorseMark>;
    } catch {
      return {};
    }
  }, [snapshot]);

  const setMark = useCallback(
    (horseKey: string, mark: HorseMark | null) => {
      if (!raceId || !horseKey) return;
      const next = { ...readMarks(raceId) };
      if (!mark || next[horseKey] === mark) {
        delete next[horseKey];
      } else {
        next[horseKey] = mark;
      }
      writeMarks(raceId, next);
    },
    [raceId],
  );

  return { marks, setMark };
}

export function useHorseMarksMulti(raceIds: string[]) {
  const uniqueRaceIds = useMemo(() => Array.from(new Set(raceIds.filter(Boolean))).sort(), [raceIds]);
  const snapshot = useSyncExternalStore(
    subscribeMarks,
    () => JSON.stringify(Object.fromEntries(uniqueRaceIds.map((raceId) => [raceId, readMarks(raceId)]))),
    () => "{}",
  );
  const marksByRace = useMemo(() => {
    try {
      return JSON.parse(snapshot) as Record<string, Record<string, HorseMark>>;
    } catch {
      return {};
    }
  }, [snapshot]);

  return marksByRace;
}
