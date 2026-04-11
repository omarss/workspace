import { create } from "zustand";
import * as tokenStorage from "../utils/tokenStorage";
import { AUTH_CONFIG } from "../constants/config";
import { useRecitationStore } from "./recitationStore";

interface User {
  id: string;
  email: string;
  name: string;
}

interface AuthState {
  user: User | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isGuest: boolean;
  isLoading: boolean;
  setAuth: (user: User, accessToken: string, refreshToken: string) => Promise<void>;
  setGuest: () => void;
  logout: () => Promise<void>;
  loadTokens: () => Promise<void>;
  updateAccessToken: (token: string) => Promise<void>;
}

export const useAuthStore = create<AuthState>()((set) => ({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isGuest: false,
  isLoading: true,

  setAuth: async (user, accessToken, refreshToken) => {
    await tokenStorage.setItem(AUTH_CONFIG.accessTokenKey, accessToken);
    await tokenStorage.setItem(AUTH_CONFIG.refreshTokenKey, refreshToken);
    set({ user, accessToken, isAuthenticated: true, isGuest: false, isLoading: false });
  },

  setGuest: () => {
    set({ user: null, accessToken: null, isAuthenticated: false, isGuest: true, isLoading: false });
  },

  logout: async () => {
    await tokenStorage.deleteItem(AUTH_CONFIG.accessTokenKey);
    await tokenStorage.deleteItem(AUTH_CONFIG.refreshTokenKey);
    useRecitationStore.getState().setHistory([]);
    set({ user: null, accessToken: null, isAuthenticated: false, isGuest: true, isLoading: false });
  },

  loadTokens: async () => {
    try {
      const accessToken = await tokenStorage.getItem(AUTH_CONFIG.accessTokenKey);
      if (accessToken) {
        set({ accessToken, isAuthenticated: true, isLoading: true });
      } else {
        // Auto-enter guest mode when no token exists (first launch or logged out)
        set({ isGuest: true, isLoading: false });
      }
    } catch {
      set({ isGuest: true, isLoading: false });
    }
  },

  updateAccessToken: async (token) => {
    await tokenStorage.setItem(AUTH_CONFIG.accessTokenKey, token);
    set({ accessToken: token });
  },
}));
