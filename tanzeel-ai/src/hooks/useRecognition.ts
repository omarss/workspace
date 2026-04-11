import { useCallback } from "react";
import { Platform } from "react-native";
import { useTranslation } from "react-i18next";
import * as Haptics from "expo-haptics";
import { useAuthStore } from "../stores/authStore";
import { useRecitationStore } from "../stores/recitationStore";
import { recognizeAudio } from "../services/recognition";
import { GUEST_LIMITS } from "../constants/config";
import { analytics } from "../services/analytics";

export function useRecognition() {
  const { t } = useTranslation();
  const { setStatus, setResult, setError, reset, history } = useRecitationStore();
  const { isAuthenticated } = useAuthStore();

  const recognize = useCallback(
    async (audioUri: string) => {
      // Enforce guest daily limit
      if (!isAuthenticated) {
        const today = new Date().toDateString();
        const todayCount = history.filter(
          (r) => new Date(r.created_at).toDateString() === today
        ).length;
        if (todayCount >= GUEST_LIMITS.dailyRecognitions) {
          analytics.guestLimitReached();
          setError(t("recite.guestLimitReached"));
          return;
        }
      }

      setStatus("processing");
      try {
        const result = await recognizeAudio(audioUri);
        setResult(result);
        if (result.top_match) {
          analytics.recognitionSuccess(result.top_match.surah, result.top_match.ayah, result.top_match.score);
          if (history.length === 0) {
            analytics.firstRecitation();
          }
        } else {
          analytics.recognitionFail();
        }
        if (Platform.OS !== "web") {
          Haptics.notificationAsync(
            result.top_match
              ? Haptics.NotificationFeedbackType.Success
              : Haptics.NotificationFeedbackType.Warning
          );
        }
      } catch (e) {
        const message =
          e instanceof Error ? e.message : t("common.error");
        setError(message);
      }
    },
    [setStatus, setResult, setError, isAuthenticated, history, t]
  );

  return { recognize, reset };
}
