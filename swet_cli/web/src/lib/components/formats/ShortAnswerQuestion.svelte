<script lang="ts">
	import type { QuestionResponse } from '$lib/api/types';

	interface Props {
		question: QuestionResponse;
		grading: boolean;
		onAnswer: (answer: string) => void;
	}

	let { question, grading, onAnswer }: Props = $props();
	let answer = $state('');

	const charCount = $derived(answer.length);

	function handleSubmit() {
		if (!grading && answer.trim()) {
			onAnswer(answer.trim());
		}
	}
</script>

<textarea
	bind:value={answer}
	placeholder="Type your answer here..."
	disabled={grading}
	rows="8"
	class="w-full resize-y rounded-lg border border-border bg-bg-muted px-4 py-3
		font-mono text-sm text-text placeholder:text-text-dim
		focus:border-accent focus:outline-none"
></textarea>

<div class="mt-1 flex items-center justify-between">
	<span class="text-xs text-text-dim">
		{charCount} characters
		{#if charCount < 50}
			· Aim for 100-300 characters
		{:else if charCount < 100}
			· Keep going...
		{:else if charCount <= 500}
			· Good length
		{:else}
			· Consider being more concise
		{/if}
	</span>
</div>

<button
	onclick={handleSubmit}
	disabled={grading || !answer.trim()}
	class="mt-3 w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-bg
		transition-colors hover:bg-accent/90 disabled:opacity-50"
>
	{#if grading}
		<span class="inline-flex items-center gap-2">
			<span class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-bg border-t-transparent"></span>
			Grading...
		</span>
	{:else}
		Submit Answer
	{/if}
</button>
