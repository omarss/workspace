"use client";

import { create } from "zustand";

export type TimerWarningLevel = "normal" | "amber" | "red";

interface TimerState {
  /** Elapsed seconds for the current question */
  questionElapsed: number;
  /** Total elapsed seconds for the assessment */
  totalElapsed: number;
  /** Whether the timer is running */
  isRunning: boolean;
  /** Time limit in seconds (null = untimed) */
  timeLimit: number | null;
  /** Whether auto-submit has been triggered */
  autoSubmitTriggered: boolean;

  // Computed-like getters
  /** Remaining seconds (null if untimed) */
  getTimeRemaining: () => number | null;
  /** Current warning level based on remaining time */
  getWarningLevel: () => TimerWarningLevel;

  // Actions
  tick: () => void;
  start: () => void;
  pause: () => void;
  resetQuestion: () => void;
  setTimeLimit: (seconds: number | null) => void;
  setAutoSubmitTriggered: () => void;
  reset: () => void;
}

export const useTimerStore = create<TimerState>()((set, get) => ({
  questionElapsed: 0,
  totalElapsed: 0,
  isRunning: false,
  timeLimit: null,
  autoSubmitTriggered: false,

  getTimeRemaining: () => {
    const { timeLimit, totalElapsed } = get();
    if (timeLimit === null) return null;
    return Math.max(0, timeLimit - totalElapsed);
  },

  getWarningLevel: () => {
    const remaining = get().getTimeRemaining();
    if (remaining === null) return "normal";
    if (remaining <= 60) return "red"; // 1 minute
    if (remaining <= 300) return "amber"; // 5 minutes
    return "normal";
  },

  tick: () =>
    set((state) =>
      state.isRunning
        ? {
            questionElapsed: state.questionElapsed + 1,
            totalElapsed: state.totalElapsed + 1,
          }
        : state
    ),
  start: () => set({ isRunning: true }),
  pause: () => set({ isRunning: false }),
  resetQuestion: () => set({ questionElapsed: 0 }),
  setTimeLimit: (seconds) => set({ timeLimit: seconds }),
  setAutoSubmitTriggered: () => set({ autoSubmitTriggered: true }),
  reset: () =>
    set({
      questionElapsed: 0,
      totalElapsed: 0,
      isRunning: false,
      timeLimit: null,
      autoSubmitTriggered: false,
    }),
}));
