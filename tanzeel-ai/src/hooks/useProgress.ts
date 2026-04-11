import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuthStore } from "../stores/authStore";
import { useRecitationStore, RecognitionResult } from "../stores/recitationStore";
import {
  getProgressSummary,
  getRecitationHistory,
  ProgressSummary,
} from "../services/recognition";

interface ProgressData {
  summary: ProgressSummary;
  history: RecognitionResult[];
  loading: boolean;
  refresh: () => Promise<void>;
}

/**
 * Returns progress data from server (if authenticated) or from local store (if guest).
 */
export function useProgress(): ProgressData {
  const { isAuthenticated } = useAuthStore();
  const localHistory = useRecitationStore((s) => s.history);

  const [serverSummary, setServerSummary] = useState<ProgressSummary | null>(null);
  const [serverHistory, setServerHistory] = useState<RecognitionResult[] | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchFromServer = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const [summary, history] = await Promise.all([
        getProgressSummary(),
        getRecitationHistory(1, 50),
      ]);
      setServerSummary(summary);
      setServerHistory(history);
    } catch {
      // Fall back to local data on error
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    fetchFromServer();
  }, [fetchFromServer]);

  // For guests, compute summary from local history
  const localSummary = useMemo<ProgressSummary>(() => {
    const today = new Date().toDateString();
    return {
      total_recitations: localHistory.length,
      unique_ayat: new Set(
        localHistory
          .filter((r) => r.top_match)
          .map((r) => `${r.top_match!.surah}:${r.top_match!.ayah}`)
      ).size,
      current_streak: 0,
      today_count: localHistory.filter(
        (r) => new Date(r.created_at).toDateString() === today
      ).length,
    };
  }, [localHistory]);

  return {
    summary: isAuthenticated && serverSummary ? serverSummary : localSummary,
    history: isAuthenticated && serverHistory ? serverHistory : localHistory,
    loading,
    refresh: fetchFromServer,
  };
}
