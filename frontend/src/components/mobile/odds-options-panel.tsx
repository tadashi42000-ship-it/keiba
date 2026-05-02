import type { OddsLimit, OddsSortKey } from "@/lib/odds-utils";

type OddsOptionsPanelProps = {
  oddsSort: OddsSortKey;
  oddsLimit: OddsLimit;
  horseFilter: string;
  onlyWithOdds: boolean;
  onOddsSortChange: (value: OddsSortKey) => void;
  onOddsLimitChange: (value: OddsLimit) => void;
  onHorseFilterChange: (value: string) => void;
  onOnlyWithOddsChange: (value: boolean) => void;
  className: string;
};

export function OddsOptionsPanel({
  oddsSort,
  oddsLimit,
  horseFilter,
  onlyWithOdds,
  onOddsSortChange,
  onOddsLimitChange,
  onHorseFilterChange,
  onOnlyWithOddsChange,
  className,
}: OddsOptionsPanelProps) {
  return (
    <section className={className}>
      <p className="text-sm font-semibold text-slate-900">オッズ表示オプション</p>

      <div className="mt-2 grid grid-cols-2 gap-2">
        <label className="text-xs text-slate-600">
          並び順
          <select
            value={oddsSort}
            onChange={(event) => onOddsSortChange(event.target.value as OddsSortKey)}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
          >
            <option value="oddsAsc">オッズ低い順</option>
            <option value="oddsDesc">オッズ高い順</option>
            <option value="umabanAsc">馬番順</option>
            <option value="nameAsc">馬名順</option>
          </select>
        </label>
        <label className="text-xs text-slate-600">
          表示件数
          <select
            value={oddsLimit}
            onChange={(event) => onOddsLimitChange(event.target.value as OddsLimit)}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
          >
            <option value="5">5件</option>
            <option value="10">10件</option>
            <option value="18">18件</option>
            <option value="all">すべて</option>
          </select>
        </label>
      </div>

      <label className="mt-2 block text-xs text-slate-600">
        馬名フィルタ
        <input
          type="text"
          value={horseFilter}
          onChange={(event) => onHorseFilterChange(event.target.value)}
          placeholder="例: クロワ"
          className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
        />
      </label>

      <label className="mt-2 flex items-center gap-2 text-xs text-slate-700">
        <input
          type="checkbox"
          checked={onlyWithOdds}
          onChange={(event) => onOnlyWithOddsChange(event.target.checked)}
        />
        オッズ欠損の馬を除外
      </label>
    </section>
  );
}
