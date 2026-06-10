"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type PollingPhase = "off" | "30min" | "5min" | "1min" | "post";
type DeadlinePhase = "5min" | "1min";

type Props = {
  raceId: string;
  startTime: string;
  dateIso: string;
  enabled?: boolean;
  onRefresh: () => Promise<void> | void;
  onDeadline?: (phase: DeadlinePhase) => void;
};

const VIBRATE_PREFIX = "keiba:same-day:vibrate-fired:";

function startAtMs(dateIso: string, startTime: string): number | null {
  const time = String(startTime || "").match(/(\d{1,2}):(\d{2})/);
  if (!dateIso || !time) return null;
  const hour = time[1].padStart(2, "0");
  const minute = time[2];
  const value = new Date(`${dateIso}T${hour}:${minute}:00+09:00`).getTime();
  return Number.isFinite(value) ? value : null;
}

function phaseFromRemaining(remainingMs: number | null): PollingPhase {
  if (remainingMs == null) return "off";
  if (remainingMs <= 0) return "post";
  if (remainingMs <= 60 * 1000) return "1min";
  if (remainingMs <= 5 * 60 * 1000) return "5min";
  if (remainingMs <= 30 * 60 * 1000) return "30min";
  return "off";
}

function intervalForPhase(phase: PollingPhase): number | null {
  if (phase === "30min") return 60 * 1000;
  if (phase === "5min") return 30 * 1000;
  if (phase === "1min") return 15 * 1000;
  return null;
}

function vibrateKey(raceId: string, phase: DeadlinePhase): string {
  return `${VIBRATE_PREFIX}${raceId}:${phase}`;
}

function fireDeadlineOnce(raceId: string, phase: DeadlinePhase, onDeadline?: (phase: DeadlinePhase) => void): void {
  if (typeof window === "undefined" || !raceId) return;
  const key = vibrateKey(raceId, phase);
  if (window.localStorage.getItem(key)) return;
  window.localStorage.setItem(key, String(Date.now()));
  if (phase === "5min") navigator.vibrate?.([200, 100, 200]);
  if (phase === "1min") navigator.vibrate?.([400, 100, 400, 100, 400]);
  onDeadline?.(phase);
}

export function useRaceAutoRefresh({ raceId, startTime, dateIso, enabled = true, onRefresh, onDeadline }: Props) {
  const [phase, setPhase] = useState<PollingPhase>("off");
  const [lastFetchedAt, setLastFetchedAt] = useState<number | null>(null);
  const onRefreshRef = useRef(onRefresh);
  const onDeadlineRef = useRef(onDeadline);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const inFlightRef = useRef(false);
  const startMs = useMemo(() => startAtMs(dateIso, startTime), [dateIso, startTime]);

  useEffect(() => {
    onRefreshRef.current = onRefresh;
  }, [onRefresh]);

  useEffect(() => {
    onDeadlineRef.current = onDeadline;
  }, [onDeadline]);

  const runRefresh = useCallback(async () => {
    if (!enabled || !raceId || inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      await onRefreshRef.current();
      setLastFetchedAt(Date.now());
      console.debug("[same-day-auto-refresh] fetched", { raceId, phase });
    } finally {
      inFlightRef.current = false;
    }
  }, [enabled, phase, raceId]);

  useEffect(() => {
    if (!enabled || !raceId || !startMs) {
      setPhase("off");
      return;
    }
    const tick = () => {
      const remaining = startMs - Date.now();
      const nextPhase = phaseFromRemaining(remaining);
      setPhase((current) => {
        if (current !== nextPhase) {
          console.debug("[same-day-auto-refresh] phase", { raceId, phase: nextPhase });
        }
        return nextPhase;
      });
      if (remaining > 0 && remaining <= 5 * 60 * 1000) {
        fireDeadlineOnce(raceId, "5min", onDeadlineRef.current);
      }
      if (remaining > 0 && remaining <= 60 * 1000) {
        fireDeadlineOnce(raceId, "1min", onDeadlineRef.current);
      }
    };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [enabled, raceId, startMs]);

  useEffect(() => {
    const clearPolling = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
    const startPolling = (immediate: boolean) => {
      clearPolling();
      const intervalMs = intervalForPhase(phase);
      if (!enabled || !raceId || !intervalMs || document.visibilityState === "hidden") return;
      // same-day-sheet refresh is intentionally reused for Phase 1. It is heavier than
      // a single-race endpoint; future work can elect one tab via BroadcastChannel.
      if (immediate) void runRefresh();
      intervalRef.current = setInterval(() => {
        void runRefresh();
      }, intervalMs);
    };
    const handleVisibility = () => {
      if (document.visibilityState === "hidden") {
        clearPolling();
        return;
      }
      startPolling(true);
    };
    startPolling(true);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      clearPolling();
    };
  }, [enabled, phase, raceId, runRefresh]);

  return { phase, lastFetchedAt };
}
