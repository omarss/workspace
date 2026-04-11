"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import type { OnboardingOptions, UserProfile } from "@/lib/types";

export function useOnboardingOptions() {
  return useQuery({
    queryKey: ["onboarding", "options"],
    queryFn: () =>
      apiClient<OnboardingOptions>("/api/v1/onboarding/options"),
  });
}

export function useProfile() {
  return useQuery({
    queryKey: ["onboarding", "profile"],
    queryFn: () => apiClient<UserProfile>("/api/v1/onboarding/profile"),
    retry: false,
  });
}

export function useCreateProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: {
      primary_role: string;
      interests: string[];
      technologies: { languages: string[]; frameworks: string[] };
      experience_years?: number;
    }) =>
      apiClient<UserProfile>("/api/v1/onboarding/profile", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["onboarding", "profile"] });
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    },
  });
}
