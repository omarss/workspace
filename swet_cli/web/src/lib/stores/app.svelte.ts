/**
 * Global app state: loading indicators, current view context, etc.
 */

function createAppStore() {
	let loading = $state(false);
	let loadingMessage = $state('');
	let toasts = $state<Array<{ id: number; message: string; type: 'success' | 'error' | 'info' }>>([]);
	let nextToastId = 0;

	return {
		get loading() { return loading; },
		get loadingMessage() { return loadingMessage; },
		get toasts() { return toasts; },

		setLoading(msg: string = '') {
			loading = true;
			loadingMessage = msg;
		},

		clearLoading() {
			loading = false;
			loadingMessage = '';
		},

		toast(message: string, type: 'success' | 'error' | 'info' = 'info') {
			const id = nextToastId++;
			toasts = [...toasts, { id, message, type }];
			// Auto-dismiss after 4s
			setTimeout(() => {
				toasts = toasts.filter((t) => t.id !== id);
			}, 4000);
		}
	};
}

export const app = createAppStore();
