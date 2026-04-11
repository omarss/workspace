import React from "react";
import { View, Text, Platform, useColorScheme } from "react-native";

interface AyahTextProps {
  text: string;
  fontSize?: number;
  highlighted?: boolean;
}

export function AyahText({ text, fontSize = 28, highlighted = false }: AyahTextProps) {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === "dark";

  const textColor = highlighted
    ? isDark ? "#34d399" : "#047857"
    : isDark ? "#f1f5f9" : "#1c1917";

  return (
    <View
      className={`rounded-xl px-4 py-5 ${
        highlighted ? "bg-primary-50 dark:bg-primary-950" : "bg-quran-bg dark:bg-slate-800"
      }`}
    >
      <Text
        style={{
          fontFamily: "Amiri",
          fontSize,
          lineHeight: fontSize * (Platform.OS === "android" ? 2.2 : 1.9),
          writingDirection: "rtl",
          textAlign: "right",
          color: textColor,
        }}
      >
        {text}
      </Text>
    </View>
  );
}
