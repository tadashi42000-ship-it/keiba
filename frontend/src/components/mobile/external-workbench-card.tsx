"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getExternalProviders,
  getXAccounts,
  postXHorseAnalysis,
  postXSummary,
  postYouTubeHorseAnalysis,
  postYouTubeSummary,
} from "@/lib/api/client";
import type {
  ExternalSnapshot,
  ExternalProvidersResponse,
  XAccountsResponse,
  XHorseAnalysisResponse,
  XSummaryResponse,
  YouTubeHorseAnalysisResponse,
  YouTubeSummaryResponse,
} from "@/lib/api/types";

import { StatusCard } from "./status-card";

function statusFrom(loading: boolean, error: string | null): "ok" | "loading" | "error" {
  if (loading) return "loading";
  if (error) return "error";
  return "ok";
}

function parseHorseNames(input: string): string[] {
  return Array.from(
    new Set(
      input
        .split(/[,\n]/)
        .map((x) => x.trim())
        .filter(Boolean),
    ),
  );
}

type ExternalWorkbenchCardProps = {
  initialRaceName?: string;
  initialHorseNames?: string[];
  initialSnapshot?: ExternalSnapshot | null;
  onSnapshotChange?: (snapshot: ExternalSnapshot) => void;
};

export function ExternalWorkbenchCard({
  initialRaceName,
  initialHorseNames = [],
  initialSnapshot,
  onSnapshotChange,
}: ExternalWorkbenchCardProps) {
  const [providers, setProviders] = useState<ExternalProvidersResponse | null>(null);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [providersError, setProvidersError] = useState<string | null>(null);

  const [xAccounts, setXAccounts] = useState<XAccountsResponse | null>(null);
  const [xAccountsError, setXAccountsError] = useState<string | null>(null);

  const [raceName, setRaceName] = useState(initialRaceName || "Satsuki Sho");
  const [youtubeQuery, setYouTubeQuery] = useState(initialRaceName ? `${initialRaceName} 予想` : "Satsuki Sho prediction");
  const [horseNamesText, setHorseNamesText] = useState(
    initialHorseNames.length ? initialHorseNames.join(", ") : "Croix du Nord, Satono Shining, Masquerade Ball",
  );

  const [maxVideos, setMaxVideos] = useState(5);
  const [youtubeResult, setYouTubeResult] = useState<YouTubeSummaryResponse | null>(initialSnapshot?.youtubeSummary ?? null);
  const [youtubeHorseResult, setYouTubeHorseResult] = useState<YouTubeHorseAnalysisResponse | null>(
    initialSnapshot?.youtubeHorseAnalysis ?? null,
  );
  const [youtubeLoading, setYouTubeLoading] = useState(false);
  const [youtubeError, setYouTubeError] = useState<string | null>(null);

  const [maxTweets, setMaxTweets] = useState(30);
  const [xResult, setXResult] = useState<XSummaryResponse | null>(initialSnapshot?.xSummary ?? null);
  const [xHorseResult, setXHorseResult] = useState<XHorseAnalysisResponse | null>(initialSnapshot?.xHorseAnalysis ?? null);
  const [xLoading, setXLoading] = useState(false);
  const [xError, setXError] = useState<string | null>(null);

  const horseNames = useMemo(() => parseHorseNames(horseNamesText), [horseNamesText]);

  const cardStatus = useMemo(
    () => statusFrom(providersLoading || youtubeLoading || xLoading, providersError || youtubeError || xError),
    [providersLoading, youtubeLoading, xLoading, providersError, youtubeError, xError],
  );

  const initialHorseNamesText = initialHorseNames.join(", ");

  useEffect(() => {
    if (initialRaceName) {
      setRaceName(initialRaceName);
      setYouTubeQuery(`${initialRaceName} 予想`);
    }
    if (initialHorseNamesText) {
      setHorseNamesText(initialHorseNamesText);
    }
  }, [initialRaceName, initialHorseNamesText]);

  useEffect(() => {
    onSnapshotChange?.({
      youtubeSummary: youtubeResult,
      youtubeHorseAnalysis: youtubeHorseResult,
      xSummary: xResult,
      xHorseAnalysis: xHorseResult,
      webSummary: initialSnapshot?.webSummary ?? null,
      updatedAt: new Date().toISOString(),
    });
  }, [youtubeResult, youtubeHorseResult, xResult, xHorseResult, initialSnapshot?.webSummary, onSnapshotChange]);

  async function refreshProviders() {
    setProvidersLoading(true);
    setProvidersError(null);
    setXAccountsError(null);
    try {
      const [providerData, accountData] = await Promise.all([getExternalProviders(), getXAccounts()]);
      setProviders(providerData);
      setXAccounts(accountData);
      setMaxTweets(accountData.default_max_tweets || 30);
    } catch (error) {
      const message = error instanceof Error ? error.message : "external provider fetch failed";
      setProvidersError(message);
      setXAccountsError(message);
    } finally {
      setProvidersLoading(false);
    }
  }

  async function handleYouTubeSummary() {
    setYouTubeLoading(true);
    setYouTubeError(null);
    try {
      const result = await postYouTubeSummary(youtubeQuery, raceName, maxVideos);
      setYouTubeResult(result);
    } catch (error) {
      setYouTubeError(error instanceof Error ? error.message : "youtube summary failed");
    } finally {
      setYouTubeLoading(false);
    }
  }

  async function handleYouTubeHorseAnalysis() {
    setYouTubeLoading(true);
    setYouTubeError(null);
    try {
      const result = await postYouTubeHorseAnalysis(youtubeQuery, raceName, horseNames, maxVideos);
      setYouTubeHorseResult(result);
    } catch (error) {
      setYouTubeError(error instanceof Error ? error.message : "youtube horse analysis failed");
    } finally {
      setYouTubeLoading(false);
    }
  }

  async function handleXSummary() {
    setXLoading(true);
    setXError(null);
    try {
      const result = await postXSummary(raceName, maxTweets);
      setXResult(result);
    } catch (error) {
      setXError(error instanceof Error ? error.message : "x summary failed");
    } finally {
      setXLoading(false);
    }
  }

  async function handleXHorseAnalysis() {
    setXLoading(true);
    setXError(null);
    try {
      const result = await postXHorseAnalysis(raceName, horseNames, maxTweets);
      setXHorseResult(result);
    } catch (error) {
      setXError(error instanceof Error ? error.message : "x horse analysis failed");
    } finally {
      setXLoading(false);
    }
  }

  useEffect(() => {
    void refreshProviders();
  }, []);

  return (
    <StatusCard title="External API Workbench" description="/api/v1/external/*" status={cardStatus}>
      <div className="space-y-4">
        <div className="rounded-xl bg-slate-50 p-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-700">Provider Status</p>
            <button
              type="button"
              onClick={() => {
                void refreshProviders();
              }}
              className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700"
            >
              Refresh
            </button>
          </div>
          {providersError ? <p className="mt-2 text-xs text-rose-700">{providersError}</p> : null}
          {providers ? (
            <ul className="mt-2 space-y-1 text-xs text-slate-700">
              <li>Tavily: {providers.tavily.configured ? "configured" : "not configured"}</li>
              <li>Gemini: {providers.gemini.configured ? "configured" : "not configured"}</li>
              <li>YouTube: {providers.youtube.configured ? "configured" : "not configured"}</li>
              <li>
                X: {providers.x.configured ? "configured" : "not configured"} / accounts {providers.x.accounts_count ?? 0}
              </li>
            </ul>
          ) : null}
          {xAccountsError ? <p className="mt-2 text-xs text-rose-700">{xAccountsError}</p> : null}
          {xAccounts ? <p className="mt-1 text-xs text-slate-500">x default_max_tweets: {xAccounts.default_max_tweets}</p> : null}
        </div>

        <div className="rounded-xl border border-slate-200 p-3">
          <p className="text-xs font-semibold text-slate-700">Input</p>
          <div className="mt-2 space-y-2">
            <input
              value={raceName}
              onChange={(event) => setRaceName(event.target.value)}
              placeholder="Race name"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            />
            <input
              value={youtubeQuery}
              onChange={(event) => setYouTubeQuery(event.target.value)}
              placeholder="YouTube query"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            />
            <textarea
              value={horseNamesText}
              onChange={(event) => setHorseNamesText(event.target.value)}
              placeholder="Horse names (comma or newline separated)"
              rows={3}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 p-3">
          <p className="text-xs font-semibold text-slate-700">YouTube</p>
          <div className="mt-2 space-y-2">
            <label className="block text-xs text-slate-600">
              Max videos
              <input
                type="number"
                min={1}
                max={10}
                value={maxVideos}
                onChange={(event) => setMaxVideos(Number.parseInt(event.target.value || "5", 10))}
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
              />
            </label>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => {
                  void handleYouTubeSummary();
                }}
                disabled={youtubeLoading}
                className="rounded-lg bg-red-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {youtubeLoading ? "Loading..." : "Get Summary"}
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleYouTubeHorseAnalysis();
                }}
                disabled={youtubeLoading}
                className="rounded-lg bg-red-800 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {youtubeLoading ? "Loading..." : "Get Horse Analysis"}
              </button>
            </div>
            {youtubeError ? <p className="text-xs text-rose-700">{youtubeError}</p> : null}
            {youtubeResult ? (
              <div className="rounded-lg bg-slate-50 p-2 text-xs text-slate-700">
                <p>Videos: {youtubeResult.videos.length} (fetched {youtubeResult.total_fetched})</p>
                <p className="mt-1 whitespace-pre-wrap">{youtubeResult.summary}</p>
              </div>
            ) : null}
            {youtubeHorseResult ? (
              <div className="rounded-lg bg-slate-50 p-2 text-xs text-slate-700">
                <p>Horse items: {youtubeHorseResult.analysis_items.length}</p>
                <p>Conclusions: {youtubeHorseResult.video_conclusions.length}</p>
                {youtubeHorseResult.warnings.length > 0 ? (
                  <p className="mt-1 text-amber-700">Warnings: {youtubeHorseResult.warnings.join(" | ")}</p>
                ) : null}
                <div className="mt-2 space-y-1">
                  {youtubeHorseResult.analysis_items.slice(0, 3).map((item, idx) => (
                    <div key={`${item.horse}-${idx}`} className="rounded-md bg-white p-2">
                      <p className="font-semibold">{item.horse}</p>
                      <p>+ {item.plus || "-"}</p>
                      <p>- {item.minus || "-"}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 p-3">
          <p className="text-xs font-semibold text-slate-700">X</p>
          <div className="mt-2 space-y-2">
            <label className="block text-xs text-slate-600">
              Max tweets
              <input
                type="number"
                min={5}
                max={100}
                value={maxTweets}
                onChange={(event) => setMaxTweets(Number.parseInt(event.target.value || "30", 10))}
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
              />
            </label>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => {
                  void handleXSummary();
                }}
                disabled={xLoading}
                className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {xLoading ? "Loading..." : "Get Summary"}
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleXHorseAnalysis();
                }}
                disabled={xLoading}
                className="rounded-lg bg-slate-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {xLoading ? "Loading..." : "Get Horse Analysis"}
              </button>
            </div>
            {xError ? <p className="text-xs text-rose-700">{xError}</p> : null}
            {xResult ? (
              <div className="rounded-lg bg-slate-50 p-2 text-xs text-slate-700">
                <p>
                  Tweets: {xResult.tweets.length} / dropped: {xResult.dropped_count} / newest_id: {xResult.newest_id ?? "-"}
                </p>
                <p className="mt-1 whitespace-pre-wrap">{xResult.summary}</p>
              </div>
            ) : null}
            {xHorseResult ? (
              <div className="rounded-lg bg-slate-50 p-2 text-xs text-slate-700">
                <p>Horse items: {xHorseResult.analysis_items.length}</p>
                {xHorseResult.warnings.length > 0 ? (
                  <p className="mt-1 text-amber-700">Warnings: {xHorseResult.warnings.join(" | ")}</p>
                ) : null}
                <div className="mt-2 space-y-1">
                  {xHorseResult.analysis_items.slice(0, 3).map((item, idx) => (
                    <div key={`${item.horse}-${idx}`} className="rounded-md bg-white p-2">
                      <p className="font-semibold">{item.horse}</p>
                      <p>+ {item.plus || "-"}</p>
                      <p>- {item.minus || "-"}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </StatusCard>
  );
}
