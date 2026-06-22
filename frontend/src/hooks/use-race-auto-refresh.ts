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
const LEADER_PREFIX = "keiba:same-day:auto-refresh-leader:";
const CHANNEL_PREFIX = "keiba-same-day-auto-refresh:";

type LeaderLease = {
  tabId: string;
  expiresAt: number;
};

type RefreshMessage = {
  type: "refreshed";
  raceId: string;
  tabId: string;
  at: number;
};

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

function leaderKey(raceId: string): string {
  return `${LEADER_PREFIX}${raceId}`;
}

function readLeaderLease(raceId: string): LeaderLease | null {
  if (typeof window === "undefined" || !raceId) return null;
  try {
    const raw = window.localStorage.getItem(leaderKey(raceId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LeaderLease>;
    if (!parsed.tabId || typeof parsed.expiresAt !== "number") return null;
    return { tabId: parsed.tabId, expiresAt: parsed.expiresAt };
  } catch {
    return null;
  }
}

function writeLeaderLease(raceId: string, lease: LeaderLease): void {
  if (typeof window === "undefined" || !raceId) return;
  window.localStorage.setItem(leaderKey(raceId), JSON.stringify(lease));
}

function createTabId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function useRaceAutoRefresh({ raceId, startTime, dateIso, enabled = true, onRefresh, onDeadline }: Props) {
  const [phase, setPhase] = useState<PollingPhase>("off");
  const [lastFetchedAt, setLastFetchedAt] = useState<number | null>(null);
  const [isPollingLeader, setIsPollingLeader] = useState(false);
  const onRefreshRef = useRef(onRefresh);
  const onDeadlineRef = useRef(onDeadline);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const channelRef = useRef<BroadcastChannel | null>(null);
  const inFlightRef = useRef(false);
  const tabIdRef = useRef<string>("");
  const startMs = useMemo(() => startAtMs(dateIso, startTime), [dateIso, startTime]);

  useEffect(() => {
    onRefreshRef.current = onRefresh;
  }, [onRefresh]);

  useEffect(() => {
    onDeadlineRef.current = onDeadline;
  }, [onDeadline]);

  const acquireLeadership = useCallback(
    (leaseMs: number) => {
      if (typeof window === "undefined" || !raceId) return true;
      if (!("BroadcastChannel" in window)) {
        setIsPollingLeader(true);
        return true;
      }
      const tabId = tabIdRef.current;
      const now = Date.now();
      const current = readLeaderLease(raceId);
      if (!current || current.expiresAt <= now || current.tabId === tabId) {
        writeLeaderLease(raceId, { tabId, expiresAt: now + leaseMs });
        setIsPollingLeader(true);
        return true;
      }
      setIsPollingLeader(false);
      return false;
    },
    [raceId],
  );

  const runRefresh = useCallback(async () => {
    if (!enabled || !raceId || inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      await onRefreshRef.current();
      const fetchedAt = Date.now();
      setLastFetchedAt(fetchedAt);
      channelRef.current?.postMessage({
        type: "refreshed",
        raceId,
        tabId: tabIdRef.current,
        at: fetchedAt,
      } satisfies RefreshMessage);
      console.debug("[same-day-auto-refresh] fetched", { raceId, phase, leader: isPollingLeader });
    } finally {
      inFlightRef.current = false;
    }
  }, [enabled, isPollingLeader, phase, raceId]);

  useEffect(() => {
    tabIdRef.current = createTabId();
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || !raceId || !("BroadcastChannel" in window)) return;
    const channel = new BroadcastChannel(`${CHANNEL_PREFIX}${raceId}`);
    channelRef.current = channel;
    channel.onmessage = (event: MessageEvent<RefreshMessage>) => {
      const message = event.data;
      if (!message || message.type !== "refreshed" || message.raceId !== raceId || message.tabId === tabIdRef.current) return;
      if (document.visibilityState === "hidden" || inFlightRef.current) return;
      inFlightRef.current = true;
      void Promise.resolve(onRefreshRef.current())
        .then(() => setLastFetchedAt(message.at))
        .finally(() => {
          inFlightRef.current = false;
        });
    };
    return () => {
      channel.close();
      if (channelRef.current === channel) channelRef.current = null;
    };
  }, [raceId]);

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
      const leaseMs = Math.max(intervalMs * 2, 20 * 1000);
      const refreshIfLeader = () => {
        if (acquireLeadership(leaseMs)) void runRefresh();
      };
      if (immediate) refreshIfLeader();
      intervalRef.current = setInterval(() => {
        refreshIfLeader();
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
  }, [acquireLeadership, enabled, phase, raceId, runRefresh]);

  return { phase, lastFetchedAt, isPollingLeader };
}
