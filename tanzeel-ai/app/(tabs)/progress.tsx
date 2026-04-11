import React from "react";
import { View, Text, ScrollView, ActivityIndicator } from "react-native";
import { useTranslation } from "react-i18next";
import { SafeAreaView } from "react-native-safe-area-context";
import FontAwesome from "@expo/vector-icons/FontAwesome";
import { useProgress } from "../../src/hooks/useProgress";

export default function ProgressScreen() {
  const { t } = useTranslation();
  const { summary, history, loading } = useProgress();

  const stats = [
    {
      icon: "microphone" as const,
      value: summary.total_recitations,
      label: t("progress.totalRecitations"),
      color: "#10b981",
    },
    {
      icon: "book" as const,
      value: summary.unique_ayat,
      label: t("progress.uniqueAyat"),
      color: "#eab308",
    },
    {
      icon: "fire" as const,
      value: summary.current_streak,
      label: t("progress.streak"),
      color: "#ef4444",
    },
  ];

  return (
    <SafeAreaView className="flex-1 bg-white dark:bg-slate-900" edges={["top"]}>
      <ScrollView className="flex-1 px-5 pt-4">
        <Text className="mb-6 text-2xl font-bold text-gray-900 dark:text-white">
          {t("progress.title")}
        </Text>

        {loading ? (
          <View className="mt-10 items-center">
            <ActivityIndicator size="large" />
          </View>
        ) : (
        <>
        {/* Stats Grid */}
        <View className="flex-row flex-wrap gap-3">
          {stats.map((stat, i) => (
            <View
              key={i}
              className="min-w-[30%] flex-1 items-center rounded-2xl bg-gray-50 p-4 dark:bg-slate-800"
            >
              <FontAwesome name={stat.icon} size={24} color={stat.color} />
              <Text className="mt-2 text-2xl font-bold text-gray-900 dark:text-white">
                {stat.value}
              </Text>
              <Text className="mt-1 text-center text-xs text-gray-500 dark:text-gray-400">
                {stat.label}
              </Text>
            </View>
          ))}
        </View>

        {/* History List */}
        <Text className="mb-3 mt-8 text-lg font-bold text-gray-900 dark:text-white">
          {t("progress.history")}
        </Text>

        {history.length === 0 ? (
          <View className="items-center rounded-2xl bg-gray-50 py-10 dark:bg-slate-800">
            <FontAwesome name="history" size={32} color="#9ca3af" />
            <Text className="mt-3 text-gray-500 dark:text-gray-400">
              {t("progress.noHistory")}
            </Text>
          </View>
        ) : (
          <View className="gap-3 pb-8">
            {history.map((item) => (
              <View
                key={item.id}
                className="rounded-xl bg-gray-50 p-4 dark:bg-slate-800"
              >
                <View className="flex-row items-center justify-between">
                  <Text className="font-semibold text-gray-900 dark:text-white">
                    {item.top_match
                      ? `${item.top_match.surah_name_en} : ${item.top_match.ayah}`
                      : t("progress.unrecognized")}
                  </Text>
                  <Text className="text-xs text-gray-400">
                    {new Date(item.created_at).toLocaleDateString()}
                  </Text>
                </View>
                <Text
                  className="mt-1 text-sm text-gray-500 dark:text-gray-400"
                  numberOfLines={2}
                  style={{ writingDirection: "rtl", textAlign: "right" }}
                >
                  {item.recognized_text}
                </Text>
              </View>
            ))}
          </View>
        )}
        </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
