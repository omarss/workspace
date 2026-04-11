import axios from "axios";
import * as tokenStorage from "../utils/tokenStorage";
import { API_URL, AUTH_CONFIG } from "../constants/config";
import { useAuthStore } from "../stores/authStore";

const api = axios.create({
  baseURL: API_URL,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use(async (config) => {
  const token = await tokenStorage.getItem(AUTH_CONFIG.accessTokenKey);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Mutex: only one token refresh at a time
let refreshPromise: Promise<string> | null = null;

async function doRefresh(): Promise<string> {
  const refreshToken = await tokenStorage.getItem(AUTH_CONFIG.refreshTokenKey);
  if (!refreshToken) throw new Error("No refresh token");

  const { data } = await axios.post<{ access_token: string }>(`${API_URL}/auth/refresh`, {
    refresh_token: refreshToken,
  });

  await useAuthStore.getState().updateAccessToken(data.access_token);
  return data.access_token;
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      try {
        if (!refreshPromise) {
          refreshPromise = doRefresh().finally(() => {
            refreshPromise = null;
          });
        }
        const newToken = await refreshPromise;
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return api(originalRequest);
      } catch {
        await useAuthStore.getState().logout();
        return Promise.reject(error);
      }
    }
    return Promise.reject(error);
  }
);

export default api;
