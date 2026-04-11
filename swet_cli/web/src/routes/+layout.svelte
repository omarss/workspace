<script lang="ts">
	import '../app.css';
	import { app } from '$lib/stores/app.svelte';

	let { children } = $props();
</script>

<svelte:head>
	<title>SWET</title>
</svelte:head>

<div class="min-h-dvh">
	{@render children()}
</div>

<!-- Toast notifications -->
{#if app.toasts.length > 0}
	<div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
		{#each app.toasts as toast (toast.id)}
			<div
				class="fade-in rounded-lg border px-4 py-3 text-sm shadow-lg
					{toast.type === 'error' ? 'border-error/30 bg-error/10 text-error' :
					toast.type === 'success' ? 'border-success/30 bg-success/10 text-success' :
					'border-accent/30 bg-accent/10 text-accent'}"
			>
				{toast.message}
			</div>
		{/each}
	</div>
{/if}
