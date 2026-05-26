export type BetType = "単勝" | "複勝" | "馬連" | "馬単" | "3連複" | "3連単" | "ワイド";

export type BetHorse = {
  key: string;
  horseName: string;
  umaban: string;
  odds: number | null;
};

export type BetSimulationInput = {
  betType: BetType;
  horses: BetHorse[];
  stakeUnit: number;
  estimatedOdds: number;
};

export type BetSimulationResult = {
  betType: BetType;
  pointCount: number;
  totalAmount: number;
  expectedPayout: number;
  isExactOdds: boolean;
};

export function combinations<T>(items: T[], size: number): T[][] {
  if (size <= 0) return [[]];
  if (items.length < size) return [];
  const result: T[][] = [];
  const walk = (start: number, current: T[]) => {
    if (current.length === size) {
      result.push([...current]);
      return;
    }
    for (let i = start; i < items.length; i += 1) {
      current.push(items[i]);
      walk(i + 1, current);
      current.pop();
    }
  };
  walk(0, []);
  return result;
}

export function permutations<T>(items: T[], size: number): T[][] {
  if (size <= 0) return [[]];
  if (items.length < size) return [];
  const result: T[][] = [];
  const used = new Set<number>();
  const walk = (current: T[]) => {
    if (current.length === size) {
      result.push([...current]);
      return;
    }
    for (let i = 0; i < items.length; i += 1) {
      if (used.has(i)) continue;
      used.add(i);
      current.push(items[i]);
      walk(current);
      current.pop();
      used.delete(i);
    }
  };
  walk([]);
  return result;
}

export function combinationCount(total: number, size: number): number {
  return combinations(Array.from({ length: total }, (_, index) => index), size).length;
}

export function permutationCount(total: number, size: number): number {
  return permutations(Array.from({ length: total }, (_, index) => index), size).length;
}

export function betPointCount(betType: BetType, selectedCount: number): number {
  switch (betType) {
    case "単勝":
    case "複勝":
      return selectedCount;
    case "馬連":
    case "ワイド":
      return combinationCount(selectedCount, 2);
    case "馬単":
      return permutationCount(selectedCount, 2);
    case "3連複":
      return combinationCount(selectedCount, 3);
    case "3連単":
      return permutationCount(selectedCount, 3);
    default:
      return 0;
  }
}

export function simulateBet(input: BetSimulationInput): BetSimulationResult {
  const pointCount = betPointCount(input.betType, input.horses.length);
  const totalAmount = pointCount * input.stakeUnit;
  const isExactOdds = input.betType === "単勝";
  const expectedPayout = isExactOdds
    ? input.horses.reduce((sum, horse) => sum + (horse.odds ?? 0) * input.stakeUnit, 0)
    : pointCount * input.stakeUnit * Math.max(0, input.estimatedOdds || 0);
  return {
    betType: input.betType,
    pointCount,
    totalAmount,
    expectedPayout: Math.round(expectedPayout),
    isExactOdds,
  };
}

