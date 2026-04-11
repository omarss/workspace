<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import { onMount } from 'svelte';

	onMount(() => {
		if (auth.isAuthenticated) {
			goto('/today');
		} else {
			goto('/login');
		}
	});
</script>

<div class="flex h-dvh items-center justify-center">
	<div class="shimmer h-8 w-32 rounded-lg"></div>
</div>
