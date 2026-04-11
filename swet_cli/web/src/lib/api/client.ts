import ky, { type KyInstance } from 'ky';
import { auth } from '$lib/stores/auth.svelte';

// Same origin — nginx proxies API routes to uvicorn
const API_BASE = typeof window !== 'undefined' ? window.location.origin : 'https://swet.omarss.net';

/**
 * API client with automatic JWT auth and token refresh.
 *
 * - Attaches Bearer token to every request when logged in
 * - On 401, attempts to refresh the token and retry once
 * - On refresh failure, clears auth state (forces re-login)
 */
function createClient(): KyInstance {
	return ky.create({
		prefixUrl: API_BASE,
		timeout: 120_000,
		hooks: {
			beforeRequest: [
				(request) => {
					const token = auth.accessToken;
					if (token) {
						request.headers.set('Authorization', `Bearer ${token}`);
					}
				}
			],
			afterResponse: [
				async (request, options, response) => {
					if (response.status !== 401) return response;

					// Don't retry auth endpoints to avoid infinite loops
					const url = request.url;
					if (url.includes('/auth/')) return response;

					const refreshToken = auth.refreshToken;
					if (!refreshToken) {
						auth.clear();
						return response;
					}

					try {
						const tokens = await ky
							.post(`${API_BASE}/auth/refresh`, {
								json: { refresh_token: refreshToken }
							})
							.json<{ access_token: string; refresh_token: string }>();

						auth.setTokens(tokens.access_token, tokens.refresh_token);

						// Retry the original request with the new token
						request.headers.set('Authorization', `Bearer ${tokens.access_token}`);
						return ky(request, options);
					} catch {
						auth.clear();
						return response;
					}
				}
			]
		}
	});
}

export const api = createClient();
