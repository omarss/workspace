<script lang="ts">
	import type { QuestionResponse } from '$lib/api/types';

	interface Props {
		question: QuestionResponse;
		grading: boolean;
		onAnswer: (answer: string) => void;
	}

	let { question, grading, onAnswer }: Props = $props();
	let selectedOption = $state<string | null>(null);

	function handleSelect(key: string) {
		if (grading) return;
		selectedOption = key;
	}

	function handleSubmit() {
		if (!grading && selectedOption) {
			onAnswer(selectedOption);
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		if (grading || !question.options) return;
		const keys = Object.keys(question.options);
		const keyMap: Record<string, number> = { '1': 0, '2': 1, '3': 2, '4': 3, a: 0, b: 1, c: 2, d: 3 };
		const idx = keyMap[event.key.toLowerCase()];
		if (idx !== undefined && idx < keys.length) {
			event.preventDefault();
			selectedOption = keys[idx];
		}
		if (event.key === 'Enter' && selectedOption) {
			event.preventDefault();
			handleSubmit();
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

{#if question.options}
	<div class="space-y-2">
		{#each Object.entries(question.options) as [key, value], i}
			<button
				onclick={() => handleSelect(key)}
				disabled={grading}
				class="flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left text-sm transition-all
					{selectedOption === key
						? 'border-accent bg-accent/10 text-text'
						: 'border-border bg-bg-muted text-text-muted hover:bg-bg-elevated'}"
			>
				<span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border
					{selectedOption === key ? 'border-accent bg-accent text-bg' : 'border-border'}
					font-mono text-xs font-medium">
					{String.fromCharCode(65 + i)}
				</span>
				<span class="pt-0.5">{value}</span>
			</button>
		{/each}
	</div>

	<button
		onclick={handleSubmit}
		disabled={grading || !selectedOption}
		class="mt-4 w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-bg
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
{/if}
