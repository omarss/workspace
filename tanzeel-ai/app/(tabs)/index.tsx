import React from "react";
import { View, Text, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { useTranslation } from "react-i18next";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import FontAwesome from "@expo/vector-icons/FontAwesome";
import { useAuthStore } from "../../src/stores/authStore";
import { useProgress } from "../../src/hooks/useProgress";

export default function HomeScreen() {
  const { t } = useTranslation();
  const router = useRouter();
  const { user } = useAuthStore();
  const { summary, history, loading } = useProgress();

  const isFirstRun = history.length === 0;
  const recentHistory = history.slice(0, 5);

  return (
    <SafeAreaView className="flex-1 bg-white dark:bg-slate-900" edges={["top"]}>
      <ScrollView
        className="flex-1 px-5 pt-4"
        contentContainerClassName={isFirstRun ? "flex-grow justify-center" : undefined}
      >
        {/* Greeting */}
        <Text className="text-3xl font-bold text-gray-900 dark:text-white">
          {user?.name
            ? t("home.greetingName", { name: user.name })
            : t("home.greeting")}
        </Text>

        {loading ? (
          <View className="mt-10 items-center">
            <ActivityIndicator size="large" />
          </View>
        ) : isFirstRun ? (
          /* First-run: single large CTA */
          <View className="mt-10 items-center">
            <Pressable
              onPress={() => router.push("/(tabs)/recite")}
              className="h-36 w-36 items-center justify-center rounded-full bg-primary-600 active:bg-primary-700"
            >
              <FontAwesome name="microphone" size={48} color="white" />
            </Pressable>
            <Text className="mt-6 text-xl font-semibold text-gray-900 dark:text-white">
              {t("home.startReciting")}
            </Text>
            <Text className="mt-2 px-8 text-center text-base text-gray-500 dark:text-gray-400">
              {t("home.firstRunHint")}
            </Text>
          </View>
        ) : (
          /* Returning user: stats + history */
          <>
            {/* Stats Cards */}
            <View className="mt-6 flex-row gap-4">
              <View className="flex-1 rounded-2xl bg-primary-50 p-4 dark:bg-primary-950">
                <FontAwesome name="microphone" size={20} color="#10b981" />
                <Text className="mt-2 text-2xl font-bold text-primary-700 dark:text-primary-300">
                  {summary.today_count}
                </Text>
                <Text className="text-sm text-primary-600 dark:text-primary-400">
                  {t("home.todayRecitations")}
                </Text>
              </View>
              <View className="flex-1 rounded-2xl bg-gold-300/20 p-4 dark:bg-gold-500/10">
                <FontAwesome name="fire" size={20} color="#eab308" />
                <Text className="mt-2 text-2xl font-bold text-gold-600 dark:text-gold-400">
                  {summary.current_streak}
                </Text>
                <Text className="text-sm text-gold-600 dark:text-gold-400">
                  {t("home.currentStreak")}
                </Text>
              </View>
            </View>

            {/* Start Reciting Button */}
            <Pressable
              onPress={() => router.push("/(tabs)/recite")}
              className="mt-6 items-center rounded-2xl bg-primary-600 py-4 active:bg-primary-700"
            >
              <View className="flex-row items-center gap-3">
                <FontAwesome name="microphone" size={20} color="white" />
                <Text className="text-lg font-semibold text-white">
                  {t("home.startReciting")}
                </Text>
              </View>
            </Pressable>

            {/* Recent History */}
            <Text className="mb-3 mt-8 text-xl font-bold text-gray-900 dark:text-white">
              {t("home.recentHistory")}
            </Text>

            <View className="gap-3 pb-8">
              {recentHistory.map((item) => (
                <Pressable
                  key={item.id}
                  onPress={() => router.push(`/result/${item.id}`)}
                  className="flex-row items-center justify-between rounded-xl bg-gray-50 p-4 active:bg-gray-100 dark:bg-slate-800 dark:active:bg-slate-700"
                >
                  <View className="flex-1">
                    <Text className="font-semibold text-gray-900 dark:text-white">
                      {item.top_match
                        ? `${item.top_match.surah_name_en} : ${item.top_match.ayah}`
                        : t("recite.noMatch")}
                    </Text>
                    <Text
                      className="mt-1 text-sm text-gray-500 dark:text-gray-400"
                      numberOfLines={1}
                    >
                      {item.recognized_text}
                    </Text>
                  </View>
                  {item.top_match && (
                    <View className="ml-3 rounded-full bg-primary-100 px-2 py-1 dark:bg-primary-900">
                      <Text className="text-xs font-semibold text-primary-700 dark:text-primary-300">
                        {Math.round(item.top_match.score * 100)}%
                      </Text>
                    </View>
                  )}
                </Pressable>
              ))}
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
