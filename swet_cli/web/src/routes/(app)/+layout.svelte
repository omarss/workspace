<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { auth } from '$lib/stores/auth.svelte';
	import { onMount } from 'svelte';

	let { children } = $props();
	let menuOpen = $state(false);

	onMount(() => {
		if (!auth.isAuthenticated) {
			goto('/login');
		}
	});

	function logout() {
		auth.clear();
		goto('/login');
	}

	// Nav items
	const navItems = [
		{ href: '/today', label: 'Today', icon: 'home' },
		{ href: '/train', label: 'Train', icon: 'play' },
		{ href: '/review', label: 'Review', icon: 'refresh' },
		{ href: '/library', label: 'Library', icon: 'bookmark' },
		{ href: '/progress', label: 'Progress', icon: 'chart' },
		{ href: '/settings', label: 'Settings', icon: 'settings' }
	];

	function isActive(href: string): boolean {
		return page.url.pathname === href || page.url.pathname.startsWith(href + '/');
	}
</script>

{#if auth.isAuthenticated}
	<div class="flex min-h-dvh flex-col">
		<!-- Top nav -->
		<nav class="sticky top-0 z-40 border-b border-border bg-bg/80 backdrop-blur-xl">
			<div class="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
				<!-- Logo -->
				<a href="/today" class="font-mono text-lg font-bold text-accent">swet</a>

				<!-- Desktop nav -->
				<div class="hidden items-center gap-1 md:flex">
					{#each navItems as item}
						<a
							href={item.href}
							class="rounded-lg px-3 py-1.5 text-sm transition-colors
								{isActive(item.href) ? 'bg-bg-elevated text-text' : 'text-text-muted hover:text-text'}"
						>
							{item.label}
						</a>
					{/each}

					<div class="ml-2 h-5 w-px bg-border"></div>

					<button
						onclick={logout}
						class="ml-1 rounded-lg px-3 py-1.5 text-sm text-text-muted transition-colors hover:text-error"
					>
						Log out
					</button>
				</div>

				<!-- Mobile hamburger -->
				<button
					class="rounded-lg p-2 text-text-muted md:hidden"
					onclick={() => (menuOpen = !menuOpen)}
				>
					<svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						{#if menuOpen}
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
						{:else}
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
						{/if}
					</svg>
				</button>
			</div>

			<!-- Mobile menu -->
			{#if menuOpen}
				<div class="border-t border-border bg-bg-subtle px-4 py-2 md:hidden">
					{#each navItems as item}
						<a
							href={item.href}
							onclick={() => (menuOpen = false)}
							class="block rounded-lg px-3 py-2 text-sm
								{isActive(item.href) ? 'text-text' : 'text-text-muted'}"
						>
							{item.label}
						</a>
					{/each}
					<button
						onclick={logout}
						class="block w-full rounded-lg px-3 py-2 text-left text-sm text-text-muted hover:text-error"
					>
						Log out
					</button>
				</div>
			{/if}
		</nav>

		<!-- Main content -->
		<main class="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
			{@render children()}
		</main>
	</div>
{/if}
