import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import AsyncStorage from "@react-native-async-storage/async-storage";
import i18n from "../i18n";

type ThemeMode = "light" | "dark" | "system";
type Language = "en" | "ar";

interface SettingsState {
  language: Language;
  theme: ThemeMode;
  setLanguage: (lang: Language) => void;
  setTheme: (theme: ThemeMode) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      language: (i18n.language as Language) || "en",
      theme: "system",
      setLanguage: (language) => {
        i18n.changeLanguage(language);
        set({ language });
      },
      setTheme: (theme) => set({ theme }),
    }),
    {
      name: "tanzeel-settings",
      storage: createJSONStorage(() => AsyncStorage),
      onRehydrateStorage: () => (state) => {
        if (state?.language && state.language !== i18n.language) {
          i18n.changeLanguage(state.language);
        }
      },
    }
  )
);
