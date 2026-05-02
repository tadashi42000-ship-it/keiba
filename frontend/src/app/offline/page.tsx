export default function OfflinePage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md items-center px-6 py-8">
      <section className="w-full rounded-3xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <h1 className="text-xl font-bold text-slate-900">オフラインです</h1>
        <p className="mt-3 text-sm text-slate-600">
          ネットワーク接続を確認してから再読み込みしてください。
          この画面はPWAの最低限フォールバックです。
        </p>
      </section>
    </main>
  );
}
