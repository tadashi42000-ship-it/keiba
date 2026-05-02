"use client";

import { useEffect, useState } from "react";

import { getSample } from "@/lib/api/client";
import type { SampleResponse } from "@/lib/api/types";

export function useSample() {
  const [data, setData] = useState<SampleResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function run() {
      try {
        const result = await getSample();
        if (mounted) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : "unknown error");
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    run();
    return () => {
      mounted = false;
    };
  }, []);

  return { data, error, loading };
}
