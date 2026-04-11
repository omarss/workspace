import { DarkTheme, DefaultTheme, ThemeProvider } from "@react-navigation/native";
import { useFonts } from "expo-font";
import { Stack, useRouter, useSegments } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect } from "react";
import { useColorScheme } from "react-native";
import "react-native-reanimated";
import "../global.css";
import "../src/i18n";
import { useAuthStore } from "../src/stores/authStore";
import { useSettingsStore } from "../src/stores/settingsStore";

export { ErrorBoundary } from "expo-router";

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [loaded, error] = useFonts({
    Amiri: require("../assets/fonts/Amiri-Regular.ttf"),
    SpaceMono: require("../assets/fonts/SpaceMono-Regular.ttf"),
  });
  const { isLoading: authLoading, loadTokens } = useAuthStore();

  useEffect(() => {
    loadTokens();
  }, []);

  useEffect(() => {
    if (error) throw error;
  }, [error]);

  useEffect(() => {
    if (loaded && !authLoading) {
      SplashScreen.hideAsync();
    }
  }, [loaded, authLoading]);

  if (!loaded || authLoading) {
    return null;
  }

  return <RootLayoutNav />;
}

function RootLayoutNav() {
  const systemColorScheme = useColorScheme();
  const themeSetting = useSettingsStore((s) => s.theme);
  const { isAuthenticated, isGuest, isLoading } = useAuthStore();
  const segments = useSegments();
  const router = useRouter();

  const isDark =
    themeSetting === "system"
      ? systemColorScheme === "dark"
      : themeSetting === "dark";

  useEffect(() => {
    if (isLoading) return;

    const inAuthGroup = segments[0] === "(auth)";
    const hasAccess = isAuthenticated || isGuest;

    if (!hasAccess && !inAuthGroup) {
      router.replace("/(auth)/login");
    } else if (isAuthenticated && inAuthGroup) {
      router.replace("/(tabs)");
    }
  }, [isAuthenticated, isGuest, isLoading, segments]);

  return (
    <ThemeProvider value={isDark ? DarkTheme : DefaultTheme}>
      <Stack>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="(auth)" options={{ headerShown: false }} />
        <Stack.Screen
          name="result/[id]"
          options={{ title: "Result", headerBackTitle: "Back" }}
        />
        {/* Surah viewer hidden until full ayah text loading is implemented */}
      </Stack>
    </ThemeProvider>
  );
}
