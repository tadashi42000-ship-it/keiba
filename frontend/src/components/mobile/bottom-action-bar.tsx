"use client";

type BottomActionBarProps = {
  onRefresh: () => void;
};

export function BottomActionBar({ onRefresh }: BottomActionBarProps) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur">
      <div className="mx-auto flex w-full max-w-md gap-2">
        <button
          type="button"
          onClick={onRefresh}
          className="flex-1 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white"
        >
          最新状態に更新
        </button>
        <a
          href="/offline"
          className="rounded-xl border border-slate-300 px-4 py-3 text-sm font-semibold text-slate-700"
        >
          オフライン表示
        </a>
      </div>
    </div>
  );
}
