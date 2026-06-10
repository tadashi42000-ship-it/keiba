import type { RaceEntryResponse, ResearchParsed, TrackBias } from "@/lib/api/types";

export type DriftSeverity = "ok" | "minor" | "warn" | "critical";

export type OddsDrift = {
  umaban: string;
  horse_name: string;
  mark: string;
  assumed_odds: number;
  current_odds: number;
  ratio: number;
  severity: DriftSeverity;
  assumed_ev?: number;
  recalc_ev?: number;
};

export type BiasDrift = {
  assumed: string;
  current: string;
  conflict: boolean;
};

export type ResearchDrift = {
  odds_drifts: OddsDrift[];
  bias_drift: BiasDrift | null;
  has_warning: boolean;
  has_critical: boolean;
};

export const EMPTY_RESEARCH_DRIFT: ResearchDrift = {
  odds_drifts: [],
  bias_drift: null,
  has_warning: false,
  has_critical: false,
};

function normalizeUmaban(value?: string | null): string {
  return String(value || "").trim().replace(/^0+/, "");
}

function severityFromRatio(ratio: number): DriftSeverity {
  const abs = Math.abs(ratio);
  if (abs >= 0.3) return "critical";
  if (abs >= 0.15) return "warn";
  if (abs > 0) return "minor";
  return "ok";
}

function containsAny(text: string, words: string[]): boolean {
  return words.some((word) => text.includes(word));
}

function hasBiasConflict(assumed: string, current: string): boolean {
  const a = assumed.toLowerCase();
  const c = current.toLowerCase();
  if (!a || !c) return false;
  if (containsAny(a, ["内", "inner"]) && containsAny(c, ["外", "outer"])) return true;
  if (containsAny(a, ["外", "outer"]) && containsAny(c, ["内", "inner"])) return true;
  if (containsAny(a, ["先行", "逃げ", "front"]) && containsAny(c, ["差し", "追込", "close"])) return true;
  if (containsAny(a, ["差し", "追込", "close"]) && containsAny(c, ["先行", "逃げ", "front"])) return true;
  if (containsAny(a, ["ハイ", "high"]) && containsAny(c, ["スロー", "slow"])) return true;
  if (containsAny(a, ["スロー", "slow"]) && containsAny(c, ["ハイ", "high"])) return true;
  return false;
}

export function detectResearchDrift(
  parsed: ResearchParsed | null,
  entry: RaceEntryResponse | null,
  trackBias: TrackBias | null,
): ResearchDrift {
  if (!parsed || !entry) return EMPTY_RESEARCH_DRIFT;
  const hasAssumptions =
    parsed.marks.some((mark) => typeof mark.assumed_odds === "number" && mark.assumed_odds > 0) ||
    Boolean(parsed.assumed_pace_label || parsed.assumed_frame_bias || parsed.assumed_style_bias);
  if (!hasAssumptions) return EMPTY_RESEARCH_DRIFT;

  const oddsByUmaban = new Map<string, number>();
  entry.horses.forEach((horse) => {
    const umaban = normalizeUmaban(horse.umaban);
    if (umaban && typeof horse.odds === "number" && Number.isFinite(horse.odds)) {
      oddsByUmaban.set(umaban, horse.odds);
    }
  });

  const oddsDrifts = parsed.marks.flatMap((mark): OddsDrift[] => {
    const umaban = normalizeUmaban(mark.umaban);
    const assumed = mark.assumed_odds;
    const current = oddsByUmaban.get(umaban);
    if (!umaban || typeof assumed !== "number" || assumed <= 0 || typeof current !== "number") return [];
    const ratio = (current - assumed) / assumed;
    const assumedEv = typeof mark.assumed_ev === "number" ? mark.assumed_ev : undefined;
    return [
      {
        umaban,
        horse_name: mark.horse_name,
        mark: mark.mark,
        assumed_odds: assumed,
        current_odds: current,
        ratio,
        severity: severityFromRatio(ratio),
        assumed_ev: assumedEv,
        recalc_ev: assumedEv != null ? assumedEv * (current / assumed) : undefined,
      },
    ];
  });

  const assumedBias = [parsed.assumed_pace_label, parsed.assumed_frame_bias, parsed.assumed_style_bias].filter(Boolean).join(" / ");
  const currentBias = trackBias?.summary_label || "";
  const biasDrift = assumedBias
    ? {
        assumed: assumedBias,
        current: currentBias,
        conflict: hasBiasConflict(assumedBias, currentBias),
      }
    : null;

  const hasCritical = oddsDrifts.some((item) => item.severity === "critical");
  const hasWarning = hasCritical || oddsDrifts.some((item) => item.severity === "warn") || Boolean(biasDrift?.conflict);
  return {
    odds_drifts: oddsDrifts,
    bias_drift: biasDrift,
    has_warning: hasWarning,
    has_critical: hasCritical,
  };
}
