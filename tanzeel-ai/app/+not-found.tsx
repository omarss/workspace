import { Link, Stack } from "expo-router";
import { View, Text } from "react-native";
import { useTranslation } from "react-i18next";

export default function NotFoundScreen() {
  const { t } = useTranslation();

  return (
    <>
      <Stack.Screen options={{ title: t("common.notFound") }} />
      <View className="flex-1 items-center justify-center bg-white p-5 dark:bg-slate-900">
        <Text className="text-xl font-bold text-gray-900 dark:text-white">
          {t("common.notFound")}
        </Text>
        <Link href="/" className="mt-4 py-4">
          <Text className="text-primary-600">{t("common.goHome")}</Text>
        </Link>
      </View>
    </>
  );
}
