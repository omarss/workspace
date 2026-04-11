"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import type {
  AssessmentResult,
  CompareResponse,
  HistoryResponse,
  HistoryStats,
  RadarDataPoint,
  TrendDataPoint,
} from "@/lib/types";

export interface HistoryFilters {
  page?: number;
  per_page?: number;
  status?: string;
  from_date?: string;
  to_date?: string;
}

export function useResult(assessmentId: string) {
  return useQuery({
    queryKey: ["results", assessmentId],
    queryFn: () =>
      apiClient<AssessmentResult>(`/api/v1/results/${assessmentId}`),
    enabled: !!assessmentId,
  });
}

export function useRadarData(assessmentId: string) {
  return useQuery({
    queryKey: ["results", assessmentId, "radar"],
    queryFn: () =>
      apiClient<{ data: RadarDataPoint[] }>(
        `/api/v1/results/${assessmentId}/radar`
      ),
    enabled: !!assessmentId,
  });
}

export function useGradingStatus(assessmentId: string) {
  return useQuery({
    queryKey: ["results", assessmentId, "grading-status"],
    queryFn: () =>
      apiClient<{
        assessment_id: string;
        grading_status: string;
        progress_percent: number;
      }>(`/api/v1/results/${assessmentId}/grading-status`),
    enabled: !!assessmentId,
    refetchInterval: (query) => {
      const data = query.state.data;
      // Stop polling once grading is complete
      if (data?.grading_status === "complete") return false;
      return 3000; // Poll every 3 seconds
    },
  });
}

export function useHistory(filters: HistoryFilters = {}) {
  const params = new URLSearchParams();
  if (filters.page) params.set("page", String(filters.page));
  if (filters.per_page) params.set("per_page", String(filters.per_page));
  if (filters.status) params.set("status", filters.status);
  if (filters.from_date) params.set("from_date", filters.from_date);
  if (filters.to_date) params.set("to_date", filters.to_date);
  const qs = params.toString();

  return useQuery({
    queryKey: ["history", filters],
    queryFn: () =>
      apiClient<HistoryResponse>(
        `/api/v1/results/history${qs ? `?${qs}` : ""}`
      ),
  });
}

export function useHistoryStats() {
  return useQuery({
    queryKey: ["history-stats"],
    queryFn: () =>
      apiClient<HistoryStats>("/api/v1/results/history/stats"),
  });
}

export function useTrend() {
  return useQuery({
    queryKey: ["history-trend"],
    queryFn: () =>
      apiClient<{ data: TrendDataPoint[] }>("/api/v1/results/history/trend"),
  });
}

export function useComparison(id1: string, id2: string) {
  return useQuery({
    queryKey: ["compare", id1, id2],
    queryFn: () =>
      apiClient<CompareResponse>(
        `/api/v1/results/compare?ids=${id1},${id2}`
      ),
    enabled: !!id1 && !!id2,
  });
}
