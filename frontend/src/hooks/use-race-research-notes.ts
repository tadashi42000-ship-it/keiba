"use client";

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { getResearchNotesBackup, putResearchNotesBackup } from "@/lib/api/client";
import type { ResearchNotesBackup, ResearchParsed } from "@/lib/api/types";

const STORAGE_KEY_PREFIX = "keiba:same-day:research-notes:";
const NOTES_EVENT = "keiba:same-day-research-notes-updated";
const TTL_MS = 7 * 24 * 60 * 60 * 1000;

type StoredNotes = {
  savedAt: number;
  notes: string;
  source?: "gemini" | "chatgpt" | "manual";
  parsed?: ResearchParsed | null;
  parsed_at?: number | null;
  parse_error?: string | null;
};

const backupInFlight = new Set<string>();

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

function writeStoredNotes(raceId: string, payload: StoredNotes, options: { backup?: boolean } = { backup: true }): void {
  if (typeof window === "undefined" || !raceId) return;
  if (!payload.notes.trim()) {
    window.localStorage.removeItem(storageKey(raceId));
  } else {
    window.localStorage.setItem(storageKey(raceId), JSON.stringify(payload));
    if (options.backup !== false) {
      void backupStoredNotes(raceId, payload);
    }
  }
  window.dispatchEvent(new Event(NOTES_EVENT));
}

function writeNotes(raceId: string, notes: string, source: StoredNotes["source"] = "manual"): void {
  const text = notes.trimEnd();
  if (!text) {
    writeStoredNotes(raceId, { savedAt: 0, notes: "" });
    return;
  }
  const current = readNotes(raceId);
  writeStoredNotes(raceId, { ...current, savedAt: Date.now(), notes: text, source });
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
  const [isRestoringBackup, setIsRestoringBackup] = useState(false);
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

  useEffect(() => {
    if (!raceId) {
      window.setTimeout(() => setIsRestoringBackup(false), 0);
      return;
    }
    let cancelled = false;
    const setRestoreState = (value: boolean) => {
      window.setTimeout(() => {
        if (!cancelled) setIsRestoringBackup(value);
      }, 0);
    };
    const local = readNotes(raceId);
    if (local.notes.trim()) {
      setRestoreState(false);
      void backupStoredNotes(raceId, local);
      return;
    }
    setRestoreState(true);
    void getResearchNotesBackup(raceId)
      .then((backup) => {
        if (cancelled || !backup.exists || !backup.notes?.trim()) return;
        writeStoredNotes(
          raceId,
          {
            savedAt: backup.savedAt || Date.now(),
            notes: backup.notes,
            source: backup.source || "manual",
            parsed: backup.parsed || null,
            parsed_at: backup.parsed_at || null,
            parse_error: backup.parse_error || null,
          },
          { backup: false },
        );
      })
      .catch(() => {
        // Backup is best-effort. Local editing must continue offline.
      })
      .finally(() => {
        if (!cancelled) setIsRestoringBackup(false);
      });
    return () => {
      cancelled = true;
    };
  }, [raceId]);

  const setNotes = useCallback(
    (text: string, source: StoredNotes["source"] = "manual") => {
      writeNotes(raceId, text, source);
    },
    [raceId],
  );

  const clearNotes = useCallback(() => {
    writeNotes(raceId, "");
  }, [raceId]);

  const setParsed = useCallback(
    (parsed: ResearchParsed | null) => {
      const current = readNotes(raceId);
      if (!current.notes) return;
      writeStoredNotes(raceId, {
        ...current,
        parsed,
        parsed_at: parsed ? Date.now() : null,
        parse_error: null,
      });
    },
    [raceId],
  );

  const setParseError = useCallback(
    (message: string | null) => {
      const current = readNotes(raceId);
      if (!current.notes) return;
      writeStoredNotes(raceId, {
        ...current,
        parse_error: message,
      });
    },
    [raceId],
  );

  return {
    notes: stored.notes || "",
    savedAt: stored.savedAt || null,
    parsed: stored.parsed || null,
    parsedAt: stored.parsed_at || null,
    parseError: stored.parse_error || null,
    isRestoringBackup,
    setNotes,
    clearNotes,
    setParsed,
    setParseError,
  };
}

async function backupStoredNotes(raceId: string, payload: StoredNotes): Promise<void> {
  if (!raceId || !payload.notes.trim()) return;
  const key = `${raceId}:${payload.savedAt}:${payload.parsed_at || 0}:${payload.notes.length}`;
  if (backupInFlight.has(key)) return;
  backupInFlight.add(key);
  const body: ResearchNotesBackup = {
    savedAt: payload.savedAt || Date.now(),
    notes: payload.notes,
    source: payload.source || "manual",
    parsed: payload.parsed || null,
    parsed_at: payload.parsed_at || null,
    parse_error: payload.parse_error || null,
  };
  try {
    await putResearchNotesBackup(raceId, body);
  } catch {
    // Best-effort backup. Avoid blocking the on-site workflow.
  } finally {
    backupInFlight.delete(key);
  }
}
