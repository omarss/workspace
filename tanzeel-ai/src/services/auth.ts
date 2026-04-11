import api from "./api";

interface AuthResponse {
  access_token: string;
  refresh_token: string;
  user: {
    id: string;
    email: string;
    name: string;
  };
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const { data } = await api.post<AuthResponse>("/auth/login", { email, password });
  return data;
}

export async function register(
  name: string,
  email: string,
  password: string
): Promise<AuthResponse> {
  const { data } = await api.post<AuthResponse>("/auth/register", {
    name,
    email,
    password,
  });
  return data;
}

export async function refreshToken(refresh_token: string): Promise<{ access_token: string }> {
  const { data } = await api.post("/auth/refresh", { refresh_token });
  return data;
}

export async function getMe(): Promise<AuthResponse["user"]> {
  const { data } = await api.get("/auth/me");
  return data;
}
