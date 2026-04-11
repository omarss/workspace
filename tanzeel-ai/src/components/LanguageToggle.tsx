import React from "react";
import { Pressable, Text, View } from "react-native";
import { useSettingsStore } from "../stores/settingsStore";

export function LanguageToggle() {
  const { language, setLanguage } = useSettingsStore();

  return (
    <View className="flex-row overflow-hidden rounded-full border border-primary-300 dark:border-primary-700">
      <Pressable
        onPress={() => setLanguage("en")}
        className={`px-4 py-2 ${
          language === "en" ? "bg-primary-600" : "bg-transparent"
        }`}
      >
        <Text
          className={`text-sm font-semibold ${
            language === "en" ? "text-white" : "text-primary-600 dark:text-primary-400"
          }`}
        >
          EN
        </Text>
      </Pressable>
      <Pressable
        onPress={() => setLanguage("ar")}
        className={`px-4 py-2 ${
          language === "ar" ? "bg-primary-600" : "bg-transparent"
        }`}
      >
        <Text
          className={`font-arabic text-sm font-semibold ${
            language === "ar" ? "text-white" : "text-primary-600 dark:text-primary-400"
          }`}
        >
          عربي
        </Text>
      </Pressable>
    </View>
  );
}
