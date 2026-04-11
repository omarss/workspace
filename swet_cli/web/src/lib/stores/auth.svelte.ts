/**
 * Reactive auth store using Svelte 5 runes.
 * Persists tokens to localStorage for session survival.
 */

const STORAGE_KEY = 'swet_auth';

interface AuthState {
	accessToken: string | null;
	refreshToken: string | null;
}

function loadFromStorage(): AuthState {
	if (typeof localStorage === 'undefined') {
		return { accessToken: null, refreshToken: null };
	}
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (raw) {
			const parsed = JSON.parse(raw);
			return {
				accessToken: parsed.accessToken ?? null,
				refreshToken: parsed.refreshToken ?? null
			};
		}
	} catch {
		// Corrupted storage — clear it
		localStorage.removeItem(STORAGE_KEY);
	}
	return { accessToken: null, refreshToken: null };
}

function saveToStorage(state: AuthState) {
	if (typeof localStorage === 'undefined') return;
	if (state.accessToken) {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
	} else {
		localStorage.removeItem(STORAGE_KEY);
	}
}

function createAuthStore() {
	const initial = loadFromStorage();
	let accessToken = $state<string | null>(initial.accessToken);
	let refreshToken = $state<string | null>(initial.refreshToken);

	return {
		get accessToken() {
			return accessToken;
		},
		get refreshToken() {
			return refreshToken;
		},
		get isAuthenticated() {
			return !!accessToken;
		},

		setTokens(access: string, refresh: string) {
			accessToken = access;
			refreshToken = refresh;
			saveToStorage({ accessToken: access, refreshToken: refresh });
		},

		clear() {
			accessToken = null;
			refreshToken = null;
			saveToStorage({ accessToken: null, refreshToken: null });
		}
	};
}

export const auth = createAuthStore();
