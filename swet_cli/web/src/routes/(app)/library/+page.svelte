<script lang="ts">
	import { onMount } from 'svelte';
	import { app } from '$lib/stores/app.svelte';
	import * as bookmarksApi from '$lib/api/bookmarks';
	import type { BookmarkResponse } from '$lib/api/types';
	import { formatSlug } from '$lib/utils/format';
	import { DIFFICULTY_LABELS, DIFFICULTY_BG_COLORS } from '$lib/data';

	let bookmarks = $state<BookmarkResponse[]>([]);
	let loading = $state(true);

	onMount(async () => {
		try {
			bookmarks = await bookmarksApi.listBookmarks();
		} catch {
			app.toast('Failed to load bookmarks', 'error');
		} finally {
			loading = false;
		}
	});

	async function unbookmark(questionId: string) {
		try {
			await bookmarksApi.removeBookmark(questionId);
			bookmarks = bookmarks.filter((b) => b.id !== questionId);
			app.toast('Bookmark removed', 'info');
		} catch {
			app.toast('Failed to remove bookmark', 'error');
		}
	}
</script>

<div class="fade-in mx-auto max-w-2xl">
	<div class="mb-6 flex items-center justify-between">
		<h1 class="text-xl font-semibold">Library</h1>
		{#if bookmarks.length > 0}
			<span class="rounded-full bg-bg-elevated px-2.5 py-0.5 text-xs font-medium text-text-muted">
				{bookmarks.length} saved
			</span>
		{/if}
	</div>

	{#if loading}
		<div class="flex h-64 items-center justify-center">
			<span
				class="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent"
			></span>
		</div>
	{:else if bookmarks.length === 0}
		<div class="py-20 text-center">
			<div class="mb-3 font-mono text-3xl text-text-dim">[]</div>
			<p class="text-sm text-text-muted">No bookmarks yet</p>
			<p class="mt-1 text-xs text-text-dim">
				Bookmark questions from the grade screen to save them here
			</p>
		</div>
	{:else}
		<div class="divide-y divide-border rounded-xl border border-border bg-bg-subtle">
			{#each bookmarks as bookmark (bookmark.id)}
				<div class="px-5 py-4">
					<div class="mb-2 flex items-start justify-between gap-3">
						<h3 class="text-sm font-medium">{bookmark.title}</h3>
						<span
							class="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold {DIFFICULTY_BG_COLORS[bookmark.difficulty - 1] ?? ''}"
						>
							{DIFFICULTY_LABELS[bookmark.difficulty - 1] ?? `L${bookmark.difficulty}`}
						</span>
					</div>
					<div class="mb-3 flex items-center gap-2 text-xs text-text-dim">
						<span>{formatSlug(bookmark.competency_slug)}</span>
						<span class="text-border">|</span>
						<span>{formatSlug(bookmark.format)}</span>
					</div>
					<div class="flex items-center gap-2">
						<a
							href="/train?question_id={bookmark.id}"
							class="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-bg transition-colors hover:bg-accent/90"
						>
							Practice
						</a>
						<button
							onclick={() => unbookmark(bookmark.id)}
							class="rounded-md border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-error hover:text-error"
						>
							Remove
						</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
