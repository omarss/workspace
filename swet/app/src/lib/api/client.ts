/**
 * API client with auth header injection.
 * Wraps fetch to automatically include the NextAuth session token
 * or anonymous Bearer token when available.
 */

import { getAnonymousToken } from "@/lib/stores/anonymous-store";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string | null,
    message: string,
    public detail?: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface FetchOptions extends RequestInit {
  /** Skip auth header injection */
  noAuth?: boolean;
}

/**
 * Fetch wrapper that adds auth headers and handles error responses.
 */
export async function apiClient<T>(
  path: string,
  options: FetchOptions = {}
): Promise<T> {
  const { noAuth, ...fetchOptions } = options;

  const headers = new Headers(fetchOptions.headers);

  if (!headers.has("Content-Type") && fetchOptions.body) {
    headers.set("Content-Type", "application/json");
  }

  // Inject anonymous Bearer token if present and auth not skipped
  if (!noAuth && !headers.has("Authorization")) {
    const anonToken = getAnonymousToken();
    if (anonToken) {
      headers.set("Authorization", `Bearer ${anonToken}`);
    }
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...fetchOptions,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      errorBody.code ?? null,
      errorBody.error ?? `Request failed with status ${response.status}`,
      errorBody.detail
    );
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}
