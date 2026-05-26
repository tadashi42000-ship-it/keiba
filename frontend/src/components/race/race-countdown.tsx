"use client";

import { useEffect, useMemo, useState } from "react";

type RaceCountdownProps = {
  startTime: string;
  dateIso: string;
};

function parseRaceStart(dateIso: string, startTime: string): number | null {
  if (!dateIso || !/^\d{4}-\d{2}-\d{2}$/.test(dateIso)) return null;
  if (!startTime || !/^\d{1,2}:\d{2}$/.test(startTime)) return null;
  const [hourText, minuteText] = startTime.split(":");
  const hour = Number.parseInt(hourText, 10);
  const minute = Number.parseInt(minuteText, 10);
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null;
  const normalized = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  const timestamp = new Date(`${dateIso}T${normalized}:00+09:00`).getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

function labelAndClass(diffMs: number): { label: string; className: string } {
  if (diffMs <= 0) {
    return {
      label: "発走済み",
      className: "bg-slate-100 text-slate-600 ring-slate-200",
    };
  }
  if (diffMs <= 60_000) {
    return {
      label: `残り ${Math.ceil(diffMs / 1000)}秒`,
      className: "animate-pulse bg-rose-100 text-rose-800 ring-rose-200",
    };
  }
  const minutes = Math.ceil(diffMs / 60_000);
  if (minutes < 5) {
    return {
      label: `残り ${minutes}分`,
      className: "bg-orange-100 text-orange-800 ring-orange-200",
    };
  }
  if (minutes <= 10) {
    return {
      label: `残り ${minutes}分`,
      className: "bg-amber-100 text-amber-800 ring-amber-200",
    };
  }
  return {
    label: `残り ${minutes}分`,
    className: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  };
}

export function RaceCountdown({ startTime, dateIso }: RaceCountdownProps) {
  const raceStart = useMemo(() => parseRaceStart(dateIso, startTime), [dateIso, startTime]);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!startTime) return null;
  if (raceStart == null) {
    return (
      <p className="mt-1 text-sm font-bold text-emerald-200">
        発走 {startTime}
      </p>
    );
  }

  const diffMs = raceStart - now;
  const status = labelAndClass(diffMs);

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <span className="text-sm font-bold text-emerald-100">発走 {startTime}</span>
      <span className={`rounded-full px-3 py-1 text-xs font-black ring-1 ${status.className}`}>
        {status.label}
      </span>
    </div>
  );
}

