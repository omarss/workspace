import { useCallback, useEffect } from "react";
import { AxiosError } from "axios";
import { useAuthStore } from "../stores/authStore";
import * as authService from "../services/auth";
import { analytics } from "../services/analytics";

export function useAuth() {
  const { user, isAuthenticated, isGuest, isLoading, setAuth, setGuest, logout, loadTokens } =
    useAuthStore();

  useEffect(() => {
    loadTokens().then(async () => {
      const { accessToken } = useAuthStore.getState();
      if (accessToken) {
        try {
          const userData = await authService.getMe();
          useAuthStore.setState({ user: userData, isLoading: false });
        } catch (e) {
          // Only logout on auth rejection (401/403), not on network errors
          const status = e instanceof AxiosError ? e.response?.status : undefined;
          if (status === 401 || status === 403) {
            await logout();
          } else {
            // Network error — stay authenticated, no profile, but stop loading
            useAuthStore.setState({ isLoading: false });
          }
        }
      }
    });
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const data = await authService.login(email, password);
      await setAuth(data.user, data.access_token, data.refresh_token);
      analytics.login();
    },
    [setAuth]
  );

  const register = useCallback(
    async (name: string, email: string, password: string) => {
      const data = await authService.register(name, email, password);
      await setAuth(data.user, data.access_token, data.refresh_token);
      analytics.accountCreated();
    },
    [setAuth]
  );

  return {
    user,
    isAuthenticated,
    isGuest,
    isLoading,
    login,
    register,
    logout,
    continueAsGuest: setGuest,
  };
}
