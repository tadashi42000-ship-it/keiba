type FetchStatusPanelProps = {
  resolveStatus: "ok" | "loading" | "error";
  csvStatus: "ok" | "loading" | "error";
  oddsStatus: "ok" | "loading" | "error";
  csvPath: string | null;
  oddsFetchedAt: string | null;
  resolveError: string | null;
  csvError: string | null;
  oddsError: string | null;
  className: string;
};

export function FetchStatusPanel({
  resolveStatus,
  csvStatus,
  oddsStatus,
  csvPath,
  oddsFetchedAt,
  resolveError,
  csvError,
  oddsError,
  className,
}: FetchStatusPanelProps) {
  return (
    <section className={className}>
      <p className="text-sm font-semibold text-slate-900">取得状態</p>
      <div className="mt-2 space-y-1 text-xs text-slate-700">
        <p>resolve: {resolveStatus}</p>
        <p>csv: {csvStatus}</p>
        <p>odds: {oddsStatus}</p>
        <p>CSV Path: {csvPath ?? "-"}</p>
        <p>オッズ取得時刻: {oddsFetchedAt ?? "-"}</p>
      </div>
      {resolveError ? <p className="mt-1 text-xs text-rose-700">resolve: {resolveError}</p> : null}
      {csvError ? <p className="mt-1 text-xs text-rose-700">csv: {csvError}</p> : null}
      {oddsError ? <p className="mt-1 text-xs text-rose-700">odds: {oddsError}</p> : null}
    </section>
  );
}
