"use client";

export function IosInstallGuide() {
  const isIos =
    typeof navigator !== "undefined" && /iphone|ipad|ipod/.test(navigator.userAgent.toLowerCase());

  const standalone =
    typeof window !== "undefined" &&
    (window.matchMedia("(display-mode: standalone)").matches ||
      (window.navigator as Navigator & { standalone?: boolean }).standalone === true);

  if (!isIos || standalone) {
    return null;
  }

  return (
    <div className="rounded-2xl bg-violet-50 p-4 ring-1 ring-violet-200">
      <p className="text-sm font-semibold text-violet-900">iPhoneでアプリっぽく使う方法</p>
      <p className="mt-1 text-xs text-violet-700">Safariの共有メニューから「ホーム画面に追加」を選んでください。</p>
    </div>
  );
}
