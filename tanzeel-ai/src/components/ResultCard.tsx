import React from "react";
import { View, Text, Pressable } from "react-native";
import { useTranslation } from "react-i18next";
import FontAwesome from "@expo/vector-icons/FontAwesome";
import { RecognitionMatch } from "../stores/recitationStore";
import { AyahText } from "./AyahText";

interface ResultCardProps {
  match: RecognitionMatch;
  isTopMatch?: boolean;
  onPress?: () => void;
}

export function ResultCard({ match, isTopMatch = false, onPress }: ResultCardProps) {
  const { t, i18n } = useTranslation();
  const isArabic = i18n.language === "ar";
  const confidencePercent = Math.round(match.score * 100);

  return (
    <Pressable
      onPress={onPress}
      className={`rounded-2xl border p-4 ${
        isTopMatch
          ? "border-primary-300 bg-primary-50 dark:border-primary-700 dark:bg-primary-950"
          : "border-gray-200 bg-white dark:border-gray-700 dark:bg-slate-800"
      }`}
    >
      {/* Header */}
      <View className="mb-3 flex-row items-center justify-between">
        <View className="flex-row items-center gap-2">
          {isTopMatch && confidencePercent >= 80 && (
            <FontAwesome name="check-circle" size={18} color="#16a34a" />
          )}
          <View className="rounded-lg bg-primary-600 px-3 py-1">
            <Text className="text-sm font-semibold text-white">
              {isArabic ? match.surah_name_ar : match.surah_name_en}
            </Text>
          </View>
          <Text className="text-sm text-gray-500 dark:text-gray-400">
            {t("recite.ayah")} {match.ayah}
          </Text>
        </View>

        {/* Confidence badge */}
        <View
          className={`rounded-full px-3 py-1 ${
            confidencePercent >= 80
              ? "bg-green-100 dark:bg-green-900"
              : confidencePercent >= 50
                ? "bg-yellow-100 dark:bg-yellow-900"
                : "bg-red-100 dark:bg-red-900"
          }`}
        >
          <Text
            className={`text-xs font-semibold ${
              confidencePercent >= 80
                ? "text-green-700 dark:text-green-300"
                : confidencePercent >= 50
                  ? "text-yellow-700 dark:text-yellow-300"
                  : "text-red-700 dark:text-red-300"
            }`}
          >
            {confidencePercent}%
          </Text>
        </View>
      </View>

      {/* Ayah text */}
      <AyahText text={match.text} fontSize={isTopMatch ? 28 : 22} highlighted={isTopMatch} />
    </Pressable>
  );
}
