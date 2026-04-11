import React from "react";
import { View, Text, ScrollView, Pressable, Alert, Platform } from "react-native";
import { useTranslation } from "react-i18next";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import FontAwesome from "@expo/vector-icons/FontAwesome";
import { LanguageToggle } from "../../src/components/LanguageToggle";
import { useAuthStore } from "../../src/stores/authStore";
import { useSettingsStore } from "../../src/stores/settingsStore";

export default function SettingsScreen() {
  const { t } = useTranslation();
  const router = useRouter();
  const { user, isAuthenticated, logout } = useAuthStore();
  const { theme, setTheme } = useSettingsStore();

  const handleLogout = () => {
    if (Platform.OS === "web") {
      if (window.confirm(t("settings.logoutConfirm"))) {
        logout();
      }
    } else {
      Alert.alert(t("settings.logout"), t("settings.logoutConfirm"), [
        { text: t("common.cancel"), style: "cancel" },
        { text: t("settings.logout"), style: "destructive", onPress: logout },
      ]);
    }
  };

  const themeOptions: Array<{ key: "light" | "dark" | "system"; label: string }> = [
    { key: "light", label: t("settings.light") },
    { key: "dark", label: t("settings.dark") },
    { key: "system", label: t("settings.system") },
  ];

  return (
    <SafeAreaView className="flex-1 bg-white dark:bg-slate-900" edges={["top"]}>
      <ScrollView className="flex-1 px-5 pt-4">
        <Text className="mb-6 text-2xl font-bold text-gray-900 dark:text-white">
          {t("settings.title")}
        </Text>

        {/* Language */}
        <View className="mb-6">
          <Text className="mb-3 text-sm font-semibold uppercase text-gray-500 dark:text-gray-400">
            {t("settings.language")}
          </Text>
          <View className="rounded-2xl bg-gray-50 p-4 dark:bg-slate-800">
            <LanguageToggle />
          </View>
        </View>

        {/* Theme */}
        <View className="mb-6">
          <Text className="mb-3 text-sm font-semibold uppercase text-gray-500 dark:text-gray-400">
            {t("settings.theme")}
          </Text>
          <View className="flex-row gap-2 rounded-2xl bg-gray-50 p-4 dark:bg-slate-800">
            {themeOptions.map((option) => (
              <Pressable
                key={option.key}
                onPress={() => setTheme(option.key)}
                className={`flex-1 items-center rounded-xl py-3 ${
                  theme === option.key
                    ? "bg-primary-600"
                    : "bg-gray-200 dark:bg-slate-700"
                }`}
              >
                <Text
                  className={`text-sm font-semibold ${
                    theme === option.key
                      ? "text-white"
                      : "text-gray-700 dark:text-gray-300"
                  }`}
                >
                  {option.label}
                </Text>
              </Pressable>
            ))}
          </View>
        </View>

        {/* Account */}
        <View className="mb-6">
          <Text className="mb-3 text-sm font-semibold uppercase text-gray-500 dark:text-gray-400">
            {t("settings.account")}
          </Text>
          <View className="rounded-2xl bg-gray-50 dark:bg-slate-800">
            {isAuthenticated && user ? (
              <>
                <View className="border-b border-gray-200 p-4 dark:border-gray-700">
                  <Text className="text-gray-900 dark:text-white">
                    {user.name}
                  </Text>
                  <Text className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                    {user.email}
                  </Text>
                </View>
                <Pressable
                  onPress={handleLogout}
                  className="flex-row items-center gap-3 p-4"
                >
                  <FontAwesome name="sign-out" size={18} color="#ef4444" />
                  <Text className="font-semibold text-red-500">
                    {t("settings.logout")}
                  </Text>
                </Pressable>
              </>
            ) : (
              <View className="p-4">
                <Text className="text-gray-600 dark:text-gray-300">
                  {t("settings.guestAccount")}
                </Text>
                <Text className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  {t("settings.createAccountHint")}
                </Text>
                <Pressable
                  onPress={() => router.push("/(auth)/register")}
                  className="mt-3 items-center rounded-xl bg-primary-600 py-3 active:bg-primary-700"
                >
                  <Text className="font-semibold text-white">
                    {t("auth.register")}
                  </Text>
                </Pressable>
                <Pressable
                  onPress={() => router.push("/(auth)/login")}
                  className="mt-2 items-center rounded-xl border border-primary-600 py-3 active:bg-primary-50 dark:active:bg-primary-950"
                >
                  <Text className="font-semibold text-primary-600 dark:text-primary-400">
                    {t("auth.login")}
                  </Text>
                </Pressable>
              </View>
            )}
          </View>
        </View>

        {/* About */}
        <View className="mb-8">
          <Text className="mb-3 text-sm font-semibold uppercase text-gray-500 dark:text-gray-400">
            {t("settings.about")}
          </Text>
          <View className="rounded-2xl bg-gray-50 p-4 dark:bg-slate-800">
            <View className="flex-row items-center justify-between">
              <Text className="text-gray-500 dark:text-gray-400">
                {t("settings.version")}
              </Text>
              <Text className="text-gray-900 dark:text-white">1.0.0</Text>
            </View>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
