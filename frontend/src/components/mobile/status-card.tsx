import type { ReactNode } from "react";

type StatusCardProps = {
  title: string;
  description: string;
  status: "ok" | "loading" | "error";
  children?: ReactNode;
};

function statusColor(status: StatusCardProps["status"]) {
  if (status === "ok") return "bg-emerald-100 text-emerald-700";
  if (status === "error") return "bg-rose-100 text-rose-700";
  return "bg-amber-100 text-amber-700";
}

function statusLabel(status: StatusCardProps["status"]) {
  if (status === "ok") return "Connected";
  if (status === "error") return "Error";
  return "Loading";
}

export function StatusCard({ title, description, status, children }: StatusCardProps) {
  return (
    <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          <p className="mt-1 text-sm text-slate-600">{description}</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusColor(status)}`}>
          {statusLabel(status)}
        </span>
      </div>
      {children ? <div className="mt-4 text-sm text-slate-700">{children}</div> : null}
    </section>
  );
}
