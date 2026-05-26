"use client";

import { useMemo, useState } from "react";

import { MARK_ORDER, stableHorseMarkKey, useHorseMarks } from "@/hooks/use-horse-marks";
import type { EntryHorse } from "@/lib/api/types";
import { type BetHorse, type BetType, simulateBet } from "@/lib/bet-calculator";

const BET_TYPES: BetType[] = ["単勝", "複勝", "馬連", "馬単", "3連複", "3連単", "ワイド"];

type BetSimulatorProps = {
  raceId: string;
  entry: {
    horses: EntryHorse[];
  } | null;
};

function yen(value: number): string {
  return `${Math.round(value).toLocaleString("ja-JP")}円`;
}

function selectedHorseLabel(horse: EntryHorse): string {
  return `${horse.umaban || "-"} ${horse.horse_name}`;
}

export function BetSimulator({ raceId, entry }: BetSimulatorProps) {
  const { marks } = useHorseMarks(raceId);
  const horses = useMemo(() => entry?.horses ?? [], [entry]);
  const initialKeys = useMemo(
    () =>
      horses
        .filter((horse) => {
          const mark = marks[stableHorseMarkKey(horse.umaban, horse.horse_name)] || "";
          return mark === "◎" || mark === "〇" || mark === "△";
        })
        .sort((a, b) => {
          const markA = marks[stableHorseMarkKey(a.umaban, a.horse_name)] || "";
          const markB = marks[stableHorseMarkKey(b.umaban, b.horse_name)] || "";
          const markDiff = MARK_ORDER[markA] - MARK_ORDER[markB];
          if (markDiff !== 0) return markDiff;
          return (Number.parseInt(a.umaban || "999", 10) || 999) - (Number.parseInt(b.umaban || "999", 10) || 999);
        })
        .map((horse) => stableHorseMarkKey(horse.umaban, horse.horse_name)),
    [horses, marks],
  );
  const [manualSelectedKeys, setManualSelectedKeys] = useState<string[] | null>(null);
  const [betType, setBetType] = useState<BetType>("単勝");
  const [stakeUnit, setStakeUnit] = useState(100);
  const [estimatedOdds, setEstimatedOdds] = useState("10.0");
  const selectedKeys = manualSelectedKeys ?? initialKeys;

  const selectableHorses = useMemo(
    () =>
      horses
        .filter((horse) => marks[stableHorseMarkKey(horse.umaban, horse.horse_name)] !== "消")
        .sort((a, b) => (Number.parseInt(a.umaban || "999", 10) || 999) - (Number.parseInt(b.umaban || "999", 10) || 999)),
    [horses, marks],
  );

  const selectedHorses: BetHorse[] = useMemo(
    () =>
      selectableHorses
        .filter((horse) => selectedKeys.includes(stableHorseMarkKey(horse.umaban, horse.horse_name)))
        .map((horse) => ({
          key: stableHorseMarkKey(horse.umaban, horse.horse_name),
          horseName: horse.horse_name,
          umaban: horse.umaban,
          odds: horse.odds,
        })),
    [selectableHorses, selectedKeys],
  );

  const simulation = useMemo(
    () =>
      simulateBet({
        betType,
        horses: selectedHorses,
        stakeUnit,
        estimatedOdds: Number.parseFloat(estimatedOdds) || 0,
      }),
    [betType, selectedHorses, stakeUnit, estimatedOdds],
  );

  function toggleHorse(key: string) {
    setManualSelectedKeys((current) => {
      const base = current ?? initialKeys;
      return base.includes(key) ? base.filter((item) => item !== key) : [...base, key];
    });
  }

  if (!entry) {
    return <div className="mt-3 rounded-2xl bg-white p-4 text-sm text-slate-500">出馬表を取得中です。</div>;
  }

  return (
    <section className="mt-3 space-y-3">
      <div className="rounded-3xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p className="text-sm font-black text-slate-950">払戻シミュレータ（段階1）</p>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          単勝のみ実オッズで計算します。複勝以降は「想定オッズ」の概算です。印メモの◎〇△を初期選択し、消した馬は候補から外します。
        </p>
      </div>

      <div className="rounded-3xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs font-bold text-slate-600">
            券種
            <select
              value={betType}
              onChange={(event) => setBetType(event.target.value as BetType)}
              className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-3 text-base font-bold text-slate-900"
            >
              {BET_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-bold text-slate-600">
            単価
            <input
              type="number"
              min={100}
              step={100}
              value={stakeUnit}
              onChange={(event) => setStakeUnit(Math.max(100, Number.parseInt(event.target.value, 10) || 100))}
              className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-3 text-base font-bold text-slate-900"
            />
          </label>
        </div>
        {betType !== "単勝" ? (
          <label className="mt-3 block text-xs font-bold text-slate-600">
            想定オッズ（概算）
            <input
              inputMode="decimal"
              value={estimatedOdds}
              onChange={(event) => setEstimatedOdds(event.target.value)}
              className="mt-1 w-full rounded-xl border border-amber-300 bg-amber-50 px-3 py-3 text-base font-bold text-amber-950"
            />
          </label>
        ) : null}
      </div>

      <div className="rounded-3xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <p className="text-xs font-bold text-slate-500">馬選択</p>
        <div className="mt-3 grid grid-cols-1 gap-2">
          {selectableHorses.map((horse) => {
            const key = stableHorseMarkKey(horse.umaban, horse.horse_name);
            const mark = marks[key] || "";
            const selected = selectedKeys.includes(key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => toggleHorse(key)}
                className={`flex min-h-12 items-center justify-between rounded-2xl px-3 py-2 text-left text-sm ring-1 ${
                  selected ? "bg-slate-900 text-white ring-slate-900" : "bg-slate-50 text-slate-800 ring-slate-200"
                }`}
              >
                <span className="font-black">
                  {mark ? `${mark} ` : ""}
                  {selectedHorseLabel(horse)}
                </span>
                <span className="text-xs font-bold">単勝 {horse.odds != null ? horse.odds.toFixed(1) : "未公開"}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="rounded-3xl bg-slate-950 p-4 text-white shadow-sm">
        <p className="text-xs font-bold text-emerald-200">計算結果</p>
        <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
          <div className="rounded-2xl bg-white/10 px-2 py-3">
            <p className="font-bold text-slate-300">点数</p>
            <p className="mt-1 text-lg font-black">{simulation.pointCount}</p>
          </div>
          <div className="rounded-2xl bg-white/10 px-2 py-3">
            <p className="font-bold text-slate-300">購入額</p>
            <p className="mt-1 text-lg font-black">{yen(simulation.totalAmount)}</p>
          </div>
          <div className="rounded-2xl bg-white/10 px-2 py-3">
            <p className="font-bold text-slate-300">見込み払戻</p>
            <p className="mt-1 text-lg font-black">{yen(simulation.expectedPayout)}</p>
          </div>
        </div>
        <p className="mt-3 rounded-2xl bg-white/10 px-3 py-2 text-xs text-slate-200">
          {simulation.isExactOdds ? "単勝は現在取得済みの単勝オッズで計算しています。" : "複勝以降は想定オッズによる概算です。実際の払戻とは異なります。"}
        </p>
      </div>
    </section>
  );
}
