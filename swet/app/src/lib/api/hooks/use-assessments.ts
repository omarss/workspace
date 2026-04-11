"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import type {
  Assessment,
  AssessmentQuestion,
  AssessmentProgress,
  AssessmentResult,
} from "@/lib/types";

interface PoolStatus {
  ready: boolean;
  generating: boolean;
  pools: { pending: number; generating: number; complete: number; failed: number };
  total: number;
}

export function usePoolStatus(enabled: boolean = true) {
  return useQuery({
    queryKey: ["pools", "status"],
    queryFn: () => apiClient<PoolStatus>("/api/v1/assessments/pools/status"),
    enabled,
    refetchInterval: (query) => {
      // Poll every 3s while pools are being generated
      const data = query.state.data;
      if (data && !data.ready) return 3000;
      return false;
    },
  });
}

export function useGeneratePools() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      apiClient<PoolStatus>("/api/v1/assessments/pools/generate", {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pools", "status"] });
    },
  });
}

export function useAssessments() {
  return useQuery({
    queryKey: ["assessments"],
    queryFn: () =>
      apiClient<{ assessments: Assessment[]; total: number }>(
        "/api/v1/assessments"
      ),
  });
}

export function useAssessment(id: string) {
  return useQuery({
    queryKey: ["assessments", id],
    queryFn: () => apiClient<Assessment>(`/api/v1/assessments/${id}`),
    enabled: !!id,
  });
}

export function useCreateAssessment() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: {
      is_timed: boolean;
      time_limit_minutes?: number;
    }) =>
      apiClient<Assessment>("/api/v1/assessments", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assessments"] });
    },
  });
}

export function useSubmitAnswer(assessmentId: string) {
  return useMutation({
    mutationFn: (data: {
      question_id: string;
      response_text?: string;
      selected_option?: string;
      time_spent_seconds: number;
      is_auto_saved: boolean;
    }) =>
      apiClient(`/api/v1/assessments/${assessmentId}/answers`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}

export function useCompleteAssessment(assessmentId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      apiClient<Assessment>(
        `/api/v1/assessments/${assessmentId}/complete`,
        { method: "POST" }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assessments"] });
    },
  });
}

export function useAssessmentProgress(assessmentId: string) {
  return useQuery({
    queryKey: ["assessments", assessmentId, "progress"],
    queryFn: () =>
      apiClient<AssessmentProgress>(
        `/api/v1/assessments/${assessmentId}/progress`
      ),
    enabled: !!assessmentId,
    refetchInterval: 30000, // Refresh every 30s
  });
}

export function useAssessmentQuestions(assessmentId: string) {
  return useQuery({
    queryKey: ["assessments", assessmentId, "questions"],
    queryFn: () =>
      apiClient<AssessmentQuestion[]>(
        `/api/v1/assessments/${assessmentId}/questions`
      ),
    enabled: !!assessmentId,
  });
}

export function useResults(assessmentId: string) {
  return useQuery({
    queryKey: ["results", assessmentId],
    queryFn: () =>
      apiClient<AssessmentResult>(`/api/v1/results/${assessmentId}`),
    enabled: !!assessmentId,
  });
}
