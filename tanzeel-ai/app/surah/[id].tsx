import React from "react";
import { View, Text, ScrollView } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { getSurahInfo } from "../../src/utils/quranData";
import { useTranslation } from "react-i18next";

export default function SurahViewerScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, i18n } = useTranslation();
  const surahNumber = parseInt(id, 10);
  const surah = getSurahInfo(surahNumber);

  if (!surah) {
    return (
      <SafeAreaView className="flex-1 items-center justify-center bg-white dark:bg-slate-900">
        <Text className="text-gray-500 dark:text-gray-400">
          {t("common.surahNotFound")}
        </Text>
      </SafeAreaView>
    );
  }

  const isArabic = i18n.language === "ar";

  return (
    <SafeAreaView className="flex-1 bg-white dark:bg-slate-900" edges={["top"]}>
      <ScrollView className="flex-1 px-5 py-4">
        <View className="mb-6 items-center">
          <Text className="text-3xl font-bold text-primary-700 dark:text-primary-300">
            {isArabic ? surah.name_ar : surah.name_en}
          </Text>
          <Text
            className="mt-1 font-arabic text-xl text-gray-600 dark:text-gray-400"
            style={{ writingDirection: "rtl" }}
          >
            {isArabic ? surah.name_en : surah.name_ar}
          </Text>
          <Text className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            {t("common.ayatCount", { count: surah.ayah_count })} | {surah.revelation_type}
          </Text>
        </View>

        <View className="rounded-2xl bg-gray-50 p-6 dark:bg-slate-800">
          <Text className="text-center text-gray-500 dark:text-gray-400">
            {t("common.surahPlaceholder")}
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
