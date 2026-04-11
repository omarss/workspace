"use client";

import { create } from "zustand";

const TOKEN_KEY = "swet-anon-token";
const USER_ID_KEY = "swet-anon-user-id";

interface AnonymousState {
  token: string | null;
  userId: string | null;

  // Actions
  setSession: (token: string, userId: string) => void;
  clearSession: () => void;
  /** Hydrate state from sessionStorage (call once on mount) */
  hydrate: () => void;
}

export const useAnonymousStore = create<AnonymousState>()((set) => ({
  token: null,
  userId: null,

  setSession: (token, userId) => {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(USER_ID_KEY, userId);
    set({ token, userId });
  },

  clearSession: () => {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_ID_KEY);
    set({ token: null, userId: null });
  },

  hydrate: () => {
    const token = sessionStorage.getItem(TOKEN_KEY);
    const userId = sessionStorage.getItem(USER_ID_KEY);
    if (token && userId) {
      set({ token, userId });
    }
  },
}));

/**
 * Read the anonymous token directly from sessionStorage.
 * Used by the API client which runs outside of React component lifecycle.
 */
export function getAnonymousToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(TOKEN_KEY);
}
