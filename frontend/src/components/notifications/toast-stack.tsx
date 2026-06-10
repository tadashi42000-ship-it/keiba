"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

type ToastInput = {
  kind: string;
  title: string;
  body?: string;
  durationMs?: number;
};

type ToastItem = ToastInput & {
  id: string;
};

type ToastContextValue = {
  toast: (input: ToastInput) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

function toastClass(kind: string): string {
  if (kind === "odds") return "bg-rose-50 text-rose-950 ring-rose-200";
  if (kind === "deadline") return "bg-emerald-50 text-emerald-950 ring-emerald-200";
  if (kind === "drift") return "bg-amber-50 text-amber-950 ring-amber-200";
  return "bg-slate-50 text-slate-950 ring-slate-200";
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const remove = useCallback((id: string) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback(
    (input: ToastInput) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const item: ToastItem = { ...input, id };
      setItems((current) => [item, ...current].slice(0, 3));
      window.setTimeout(() => remove(id), input.durationMs ?? 4500);
    },
    [remove],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed left-0 top-0 z-50 flex w-[100dvw] max-w-[100dvw] flex-col gap-2 px-3 pt-3 sm:left-1/2 sm:w-full sm:max-w-md sm:-translate-x-1/2">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => remove(item.id)}
            className={`pointer-events-auto w-full translate-y-0 rounded-2xl px-4 py-3 text-left text-xs shadow-lg ring-1 transition duration-200 sm:mx-auto sm:max-w-md ${toastClass(item.kind)}`}
          >
            <span className="block font-black">{item.title}</span>
            {item.body ? <span className="mt-1 block leading-5">{item.body}</span> : null}
          </button>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const value = useContext(ToastContext);
  if (!value) {
    return { toast: () => undefined };
  }
  return value;
}
