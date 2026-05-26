"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

const STORAGE_KEY_PREFIX = "keiba:same-day:research-notes:";
const NOTES_EVENT = "keiba:same-day-research-notes-updated";
const TTL_MS = 7 * 24 * 60 * 60 * 1000;

type StoredNotes = {
  savedAt: number;
  notes: string;
  source?: "gemini" | "chatgpt" | "manual";
};

function storageKey(raceId: string): string {
  return `${STORAGE_KEY_PREFIX}${raceId}`;
}

function emptySnapshot(): StoredNotes {
  return { savedAt: 0, notes: "" };
}

function readNotes(raceId: string): StoredNotes {
  if (typeof window === "undefined" || !raceId) return emptySnapshot();
  try {
    const raw = window.localStorage.getItem(storageKey(raceId));
    if (!raw) return emptySnapshot();
    const payload = JSON.parse(raw) as StoredNotes;
    if (!payload || typeof payload.savedAt !== "number" || typeof payload.notes !== "string") return emptySnapshot();
    if (Date.now() - payload.savedAt > TTL_MS) {
      window.localStorage.removeItem(storageKey(raceId));
      return emptySnapshot();
    }
    return payload;
  } catch {
    return emptySnapshot();
  }
}

function writeNotes(raceId: string, notes: string, source: StoredNotes["source"] = "manual"): void {
  if (typeof window === "undefined" || !raceId) return;
  const text = notes.trimEnd();
  if (!text) {
    window.localStorage.removeItem(storageKey(raceId));
  } else {
    window.localStorage.setItem(storageKey(raceId), JSON.stringify({ savedAt: Date.now(), notes: text, source }));
  }
  window.dispatchEvent(new Event(NOTES_EVENT));
}

function subscribeNotes(callback: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(NOTES_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(NOTES_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

export function useRaceResearchNotes(raceId: string) {
  const snapshot = useSyncExternalStore(
    subscribeNotes,
    () => JSON.stringify(readNotes(raceId)),
    () => JSON.stringify(emptySnapshot()),
  );
  const stored = useMemo(() => {
    try {
      return JSON.parse(snapshot) as StoredNotes;
    } catch {
      return emptySnapshot();
    }
  }, [snapshot]);

  const setNotes = useCallback(
    (text: string, source: StoredNotes["source"] = "manual") => {
      writeNotes(raceId, text, source);
    },
    [raceId],
  );

  const clearNotes = useCallback(() => {
    writeNotes(raceId, "");
  }, [raceId]);

  return {
    notes: stored.notes || "",
    savedAt: stored.savedAt || null,
    setNotes,
    clearNotes,
  };
}

