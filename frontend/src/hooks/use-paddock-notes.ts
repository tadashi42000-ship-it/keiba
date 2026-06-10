"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

export type PaddockGrade = "" | "good" | "ok" | "watch" | "bad";

export type HorsePaddockNote = {
  paddock: PaddockGrade;
  returnHorse: PaddockGrade;
  memo: string;
  updatedAt: number;
};

export type PaddockNotes = Record<string, HorsePaddockNote>;

const STORAGE_KEY_PREFIX = "keiba:same-day:paddock-notes:";
const PADDOCK_EVENT = "keiba:same-day-paddock-notes-updated";
const TTL_MS = 7 * 24 * 60 * 60 * 1000;

const EMPTY_NOTE: HorsePaddockNote = {
  paddock: "",
  returnHorse: "",
  memo: "",
  updatedAt: 0,
};

function storageKey(raceId: string): string {
  return `${STORAGE_KEY_PREFIX}${raceId}`;
}

function isPaddockGrade(value: unknown): value is PaddockGrade {
  return value === "" || value === "good" || value === "ok" || value === "watch" || value === "bad";
}

function cleanNote(value: unknown): HorsePaddockNote | null {
  if (!value || typeof value !== "object") return null;
  const note = value as Partial<HorsePaddockNote>;
  const paddock = isPaddockGrade(note.paddock) ? note.paddock : "";
  const returnHorse = isPaddockGrade(note.returnHorse) ? note.returnHorse : "";
  const memo = typeof note.memo === "string" ? note.memo.slice(0, 160) : "";
  const updatedAt = typeof note.updatedAt === "number" ? note.updatedAt : 0;
  if (!paddock && !returnHorse && !memo.trim()) return null;
  return { paddock, returnHorse, memo, updatedAt };
}

function readNotes(raceId: string): PaddockNotes {
  if (typeof window === "undefined" || !raceId) return {};
  try {
    const raw = window.localStorage.getItem(storageKey(raceId));
    if (!raw) return {};
    const payload = JSON.parse(raw) as { savedAt?: number; notes?: Record<string, unknown> };
    if (!payload || typeof payload.savedAt !== "number" || !payload.notes) return {};
    if (Date.now() - payload.savedAt > TTL_MS) {
      window.localStorage.removeItem(storageKey(raceId));
      return {};
    }
    return Object.fromEntries(
      Object.entries(payload.notes)
        .map(([key, note]) => [key, cleanNote(note)] as const)
        .filter((entry): entry is [string, HorsePaddockNote] => Boolean(entry[0] && entry[1])),
    );
  } catch {
    return {};
  }
}

function writeNotes(raceId: string, notes: PaddockNotes): void {
  if (typeof window === "undefined" || !raceId) return;
  const cleanNotes = Object.fromEntries(
    Object.entries(notes)
      .map(([key, note]) => [key, cleanNote(note)] as const)
      .filter((entry): entry is [string, HorsePaddockNote] => Boolean(entry[0] && entry[1])),
  );
  if (Object.keys(cleanNotes).length === 0) {
    window.localStorage.removeItem(storageKey(raceId));
  } else {
    window.localStorage.setItem(storageKey(raceId), JSON.stringify({ savedAt: Date.now(), notes: cleanNotes }));
  }
  window.dispatchEvent(new Event(PADDOCK_EVENT));
}

function subscribeNotes(callback: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(PADDOCK_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(PADDOCK_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

export function emptyPaddockNote(): HorsePaddockNote {
  return { ...EMPTY_NOTE };
}

export function paddockGradeLabel(grade: PaddockGrade): string {
  switch (grade) {
    case "good":
      return "◎";
    case "ok":
      return "○";
    case "watch":
      return "△";
    case "bad":
      return "×";
    default:
      return "-";
  }
}

export function paddockNoteBonus(note?: HorsePaddockNote | null): { bonus: number; reason: string } {
  if (!note) return { bonus: 0, reason: "" };
  const grade = note.paddock || note.returnHorse;
  const gradeBonus: Record<PaddockGrade, number> = { "": 0, good: 0.05, ok: 0.025, watch: -0.025, bad: -0.05 };
  const bonus = Number((gradeBonus[grade] ?? 0).toFixed(3));
  return { bonus, reason: grade ? `気配${paddockGradeLabel(grade)}` : "" };
}

export function usePaddockNotes(raceId: string) {
  const snapshot = useSyncExternalStore(
    subscribeNotes,
    () => JSON.stringify(readNotes(raceId)),
    () => "{}",
  );
  const notes = useMemo(() => {
    try {
      return JSON.parse(snapshot) as PaddockNotes;
    } catch {
      return {};
    }
  }, [snapshot]);

  const setNote = useCallback(
    (horseKey: string, patch: Partial<Omit<HorsePaddockNote, "updatedAt">>) => {
      if (!raceId || !horseKey) return;
      const current = readNotes(raceId);
      const nextNote = cleanNote({ ...EMPTY_NOTE, ...current[horseKey], ...patch, updatedAt: Date.now() });
      const next = { ...current };
      if (nextNote) {
        next[horseKey] = nextNote;
      } else {
        delete next[horseKey];
      }
      writeNotes(raceId, next);
    },
    [raceId],
  );

  const clearNote = useCallback(
    (horseKey: string) => {
      if (!raceId || !horseKey) return;
      const next = { ...readNotes(raceId) };
      delete next[horseKey];
      writeNotes(raceId, next);
    },
    [raceId],
  );

  return { notes, setNote, clearNote };
}
