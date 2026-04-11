"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export type SaveStatus = "idle" | "saving" | "saved" | "error";

interface AnswerData {
  text?: string;
  option?: string;
  timeSpent: number;
}

interface AssessmentState {
  assessmentId: string | null;
  currentIndex: number;
  answers: Record<string, AnswerData>;
  flaggedQuestions: Set<number>;
  saveStatus: SaveStatus;
  /** Whether the assessment is paused (e.g. tab hidden) */
  isPaused: boolean;
  /** Retry count for save failures */
  saveRetryCount: number;

  // Actions
  setAssessment: (id: string) => void;
  setCurrentIndex: (index: number) => void;
  saveAnswer: (questionId: string, answer: AnswerData) => void;
  toggleFlag: (position: number) => void;
  setSaveStatus: (status: SaveStatus) => void;
  setPaused: (paused: boolean) => void;
  incrementRetryCount: () => void;
  resetRetryCount: () => void;
  reset: () => void;
}

export const useAssessmentStore = create<AssessmentState>()(
  persist(
    (set) => ({
      assessmentId: null,
      currentIndex: 0,
      answers: {},
      flaggedQuestions: new Set(),
      saveStatus: "idle" as SaveStatus,
      isPaused: false,
      saveRetryCount: 0,

      setAssessment: (id) =>
        set({
          assessmentId: id,
          currentIndex: 0,
          answers: {},
          flaggedQuestions: new Set(),
          saveStatus: "idle" as SaveStatus,
          isPaused: false,
          saveRetryCount: 0,
        }),
      setCurrentIndex: (index) => set({ currentIndex: index }),
      saveAnswer: (questionId, answer) =>
        set((state) => ({
          answers: { ...state.answers, [questionId]: answer },
        })),
      toggleFlag: (position) =>
        set((state) => {
          const newFlags = new Set(state.flaggedQuestions);
          if (newFlags.has(position)) {
            newFlags.delete(position);
          } else {
            newFlags.add(position);
          }
          return { flaggedQuestions: newFlags };
        }),
      setSaveStatus: (status) => set({ saveStatus: status }),
      setPaused: (paused) => set({ isPaused: paused }),
      incrementRetryCount: () =>
        set((state) => ({ saveRetryCount: state.saveRetryCount + 1 })),
      resetRetryCount: () => set({ saveRetryCount: 0 }),
      reset: () =>
        set({
          assessmentId: null,
          currentIndex: 0,
          answers: {},
          flaggedQuestions: new Set(),
          saveStatus: "idle" as SaveStatus,
          isPaused: false,
          saveRetryCount: 0,
        }),
    }),
    {
      name: "swet-assessment",
      storage: createJSONStorage(() => sessionStorage),
      // Custom serialization to handle Set
      partialize: (state) => ({
        assessmentId: state.assessmentId,
        currentIndex: state.currentIndex,
        answers: state.answers,
        flaggedQuestions: [...state.flaggedQuestions],
        isPaused: state.isPaused,
      }),
      merge: (persistedState, currentState) => {
        const persisted = persistedState as Record<string, unknown>;
        return {
          ...currentState,
          ...persisted,
          flaggedQuestions: new Set(
            (persisted?.flaggedQuestions as number[]) ?? []
          ),
        };
      },
    }
  )
);
