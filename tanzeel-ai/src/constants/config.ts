import Constants from "expo-constants";

function getApiUrl(): string {
  if (process.env.EXPO_PUBLIC_API_URL) {
    return process.env.EXPO_PUBLIC_API_URL;
  }
  // In dev, use the Expo dev server host so physical devices can reach the backend
  const debuggerHost =
    Constants.expoConfig?.hostUri ?? Constants.manifest2?.extra?.expoGo?.debuggerHost;
  if (debuggerHost) {
    const host = debuggerHost.split(":")[0];
    return `http://${host}:8000`;
  }
  return "http://localhost:8000";
}

export const API_URL = getApiUrl();

if (__DEV__ && API_URL.includes("localhost")) {
  console.warn(`[Tanzeel] API_URL is ${API_URL} — physical devices won't reach localhost`);
} else if (!__DEV__ && API_URL.includes("localhost")) {
  throw new Error("API_URL points to localhost in a production build. Set EXPO_PUBLIC_API_URL.");
}

export const AUDIO_CONFIG = {
  maxDurationMs: 30_000,
  sampleRate: 16_000,
  channels: 1,
} as const;

export const RECOGNITION_CONFIG = {
  maxAlternatives: 3,
  minConfidence: 0.3,
} as const;

export const AUTH_CONFIG = {
  accessTokenKey: "tanzeel_access_token",
  refreshTokenKey: "tanzeel_refresh_token",
} as const;

export const GUEST_LIMITS = {
  dailyRecognitions: 10,
} as const;
