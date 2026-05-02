import type { OddsHorse } from "@/lib/api/types";
import { formatOdds, oddsSortLabel, type OddsSortKey } from "@/lib/odds-utils";

type OddsTablePanelProps = {
  rows: OddsHorse[];
  oddsSort: OddsSortKey;
  oddsError: string | null;
  className: string;
  tableMinWidthClass?: string;
  emptyMessage?: string;
};

export function OddsTablePanel({
  rows,
  oddsSort,
  oddsError,
  className,
  tableMinWidthClass = "min-w-[480px]",
  emptyMessage = "データ未取得、またはフィルタ条件に一致しません。",
}: OddsTablePanelProps) {
  const topThree = rows.slice(0, 3);

  return (
    <section className={className}>
      <p className="text-sm font-semibold text-slate-900">
        オッズ一覧 ({oddsSortLabel(oddsSort)} / {rows.length}件表示)
      </p>

      {!oddsError && rows.length === 0 ? <p className="mt-2 text-sm text-slate-500">{emptyMessage}</p> : null}

      {topThree.length > 0 ? (
        <div className="mt-2 rounded-lg bg-emerald-50 p-2 text-xs text-emerald-800">
          上位参考: {topThree.map((horse) => `${horse.horse_name}(${formatOdds(horse.odds)})`).join(" / ")}
        </div>
      ) : null}

      {rows.length > 0 ? (
        <div className="mt-2 overflow-x-auto">
          <table className={`w-full ${tableMinWidthClass} text-left text-xs`}>
            <thead>
              <tr className="text-slate-500">
                <th className="pb-2">#</th>
                <th className="pb-2">枠番</th>
                <th className="pb-2">馬番</th>
                <th className="pb-2">馬名</th>
                <th className="pb-2 text-right">単勝オッズ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((horse, index) => (
                <tr key={`${horse.umaban ?? "-"}-${horse.horse_name}`} className="border-t border-slate-100">
                  <td className="py-2">{index + 1}</td>
                  <td className="py-2">{horse.waku ?? "-"}</td>
                  <td className="py-2">{horse.umaban ?? "-"}</td>
                  <td className="py-2">{horse.horse_name}</td>
                  <td className="py-2 text-right">{formatOdds(horse.odds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
