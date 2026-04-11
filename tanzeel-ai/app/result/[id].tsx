import React from "react";
import { View, Text, ScrollView } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useTranslation } from "react-i18next";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRecitationStore } from "../../src/stores/recitationStore";
import { useProgress } from "../../src/hooks/useProgress";
import { ResultCard } from "../../src/components/ResultCard";

export default function ResultDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useTranslation();
  const { history: progressHistory } = useProgress();
  const { history: localHistory } = useRecitationStore();

  const result =
    progressHistory.find((r) => r.id === id) ??
    localHistory.find((r) => r.id === id);

  if (!result) {
    return (
      <SafeAreaView className="flex-1 items-center justify-center bg-white dark:bg-slate-900">
        <Text className="text-gray-500 dark:text-gray-400">
          {t("common.resultNotFound")}
        </Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView className="flex-1 bg-white dark:bg-slate-900" edges={["top"]}>
      <ScrollView className="flex-1 px-5 py-4">
        <Text className="mb-2 text-sm text-gray-500 dark:text-gray-400">
          {new Date(result.created_at).toLocaleString()}
        </Text>

        <Text
          className="mb-6 text-base text-gray-600 dark:text-gray-300"
          style={{ writingDirection: "rtl", textAlign: "right" }}
        >
          {result.recognized_text}
        </Text>

        {result.top_match && (
          <View className="gap-4">
            <ResultCard match={result.top_match} isTopMatch />
            {result.alternatives.map((alt, i) => (
              <ResultCard key={`${alt.surah}-${alt.ayah}`} match={alt} />
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
