import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import AsyncStorage from "@react-native-async-storage/async-storage";

export interface RecognitionMatch {
  surah: number;
  ayah: number;
  surah_name_ar: string;
  surah_name_en: string;
  text: string;
  score: number;
}

export interface RecognitionResult {
  id: string;
  recognized_text: string;
  top_match: RecognitionMatch | null;
  alternatives: RecognitionMatch[];
  created_at: string;
}

type RecordingStatus = "idle" | "recording" | "processing" | "done" | "error";

interface RecitationState {
  status: RecordingStatus;
  currentResult: RecognitionResult | null;
  history: RecognitionResult[];
  error: string | null;
  setStatus: (status: RecordingStatus) => void;
  setResult: (result: RecognitionResult) => void;
  setError: (error: string) => void;
  addToHistory: (result: RecognitionResult) => void;
  setHistory: (history: RecognitionResult[]) => void;
  reset: () => void;
}

export const useRecitationStore = create<RecitationState>()(
  persist(
    (set) => ({
      status: "idle",
      currentResult: null,
      history: [],
      error: null,

      setStatus: (status) => set({ status, error: null }),
      setResult: (result) =>
        set((state) => ({
          currentResult: result,
          status: "done",
          history: [result, ...state.history].slice(0, 500),
        })),
      setError: (error) => set({ error, status: "error" }),
      addToHistory: (result) =>
        set((state) => ({ history: [result, ...state.history].slice(0, 500) })),
      setHistory: (history) => set({ history }),
      reset: () => set({ status: "idle", currentResult: null, error: null }),
    }),
    {
      name: "tanzeel-recitations",
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({ history: state.history }),
    }
  )
);
