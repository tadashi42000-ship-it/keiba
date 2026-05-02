"use client";

import { useMemo } from "react";

import { AppHeader } from "@/components/mobile/app-header";
import { BottomActionBar } from "@/components/mobile/bottom-action-bar";
import { ExternalWorkbenchCard } from "@/components/mobile/external-workbench-card";
import { InstallBanner } from "@/components/mobile/install-banner";
import { IosInstallGuide } from "@/components/mobile/ios-install-guide";
import { RaceWorkbenchCard } from "@/components/mobile/race-workbench-card";
import { StatusCard } from "@/components/mobile/status-card";
import { useHealth } from "@/hooks/use-health";
import { useSample } from "@/hooks/use-sample";

export default function Home() {
  const health = useHealth();
  const sample = useSample();

  const healthStatus = useMemo(() => {
    if (health.loading) return "loading" as const;
    if (health.error) return "error" as const;
    return "ok" as const;
  }, [health.loading, health.error]);

  const sampleStatus = useMemo(() => {
    if (sample.loading) return "loading" as const;
    if (sample.error) return "error" as const;
    return "ok" as const;
  }, [sample.loading, sample.error]);

  return (
    <main className="mx-auto min-h-screen w-full max-w-md px-4 pb-28 pt-6">
      <div className="space-y-4">
        <AppHeader
          title="競馬モバイル"
          subtitle="当日30分前に、出馬表・脚質・オッズ・買い目候補を素早く確認"
        />

        <InstallBanner />
        <IosInstallGuide />

        <StatusCard
          title="Backend Health"
          description="GET /health"
          status={healthStatus}
        >
          {health.error ? (
            <p className="text-rose-700">{health.error}</p>
          ) : (
            <ul className="space-y-1">
              <li>Status: {health.data?.status ?? "-"}</li>
              <li>Service: {health.data?.service ?? "-"}</li>
              <li>Version: {health.data?.version ?? "-"}</li>
            </ul>
          )}
        </StatusCard>

        <StatusCard
          title="Sample API"
          description="GET /api/v1/sample"
          status={sampleStatus}
        >
          {sample.error ? (
            <p className="text-rose-700">{sample.error}</p>
          ) : (
            <div className="space-y-2">
              <p>{sample.data?.message ?? "-"}</p>
              <ul className="space-y-1">
                {(sample.data?.sample_items ?? []).map((item) => (
                  <li key={item.title} className="rounded-lg bg-slate-50 px-3 py-2">
                    <span className="font-semibold">{item.title}</span>: {item.value}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </StatusCard>

        <RaceWorkbenchCard />
        <ExternalWorkbenchCard />
      </div>

      <BottomActionBar
        onRefresh={() => {
          window.location.reload();
        }}
      />
    </main>
  );
}
