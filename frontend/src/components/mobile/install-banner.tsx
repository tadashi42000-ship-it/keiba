"use client";

import { useEffect, useState } from "react";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
};

export function InstallBanner() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const handler = (event: Event) => {
      event.preventDefault();
      setDeferredPrompt(event as BeforeInstallPromptEvent);
      setVisible(true);
    };

    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  if (!visible || !deferredPrompt) {
    return null;
  }

  return (
    <div className="rounded-2xl bg-sky-50 p-4 ring-1 ring-sky-200">
      <p className="text-sm font-semibold text-sky-900">ホーム画面に追加できます</p>
      <p className="mt-1 text-xs text-sky-700">Android ではインストールしてアプリのように使えます。</p>
      <button
        type="button"
        className="mt-3 rounded-lg bg-sky-600 px-3 py-2 text-sm font-semibold text-white"
        onClick={async () => {
          await deferredPrompt.prompt();
          await deferredPrompt.userChoice;
          setVisible(false);
        }}
      >
        インストール
      </button>
    </div>
  );
}
