<script lang="ts">
	import type { QuestionResponse } from '$lib/api/types';

	interface Props {
		question: QuestionResponse;
		grading: boolean;
		onAnswer: (answer: string) => void;
	}

	let { question, grading, onAnswer }: Props = $props();
	let bugLocation = $state('');
	let fix = $state('');
	let explanation = $state('');

	function handleSubmit() {
		if (grading) return;
		// Combine fields into structured answer
		const parts: string[] = [];
		if (bugLocation.trim()) parts.push(`Bug location: ${bugLocation.trim()}`);
		if (fix.trim()) parts.push(`Fix:\n${fix.trim()}`);
		if (explanation.trim()) parts.push(`Explanation: ${explanation.trim()}`);
		const answer = parts.join('\n\n');
		if (answer) onAnswer(answer);
	}

	const hasContent = $derived(bugLocation.trim() || fix.trim() || explanation.trim());
</script>

<div class="space-y-4">
	<!-- Bug location -->
	<div>
		<label for="bug-location" class="mb-1 block text-xs font-medium text-text-muted">Bug Location</label>
		<input
			id="bug-location"
			type="text"
			bind:value={bugLocation}
			placeholder="e.g., Line 12: off-by-one in loop condition"
			disabled={grading}
			class="w-full rounded-lg border border-border bg-bg-muted px-3 py-2.5 text-sm text-text
				placeholder:text-text-dim focus:border-accent focus:outline-none"
		/>
	</div>

	<!-- Fix -->
	<div>
		<label for="bug-fix" class="mb-1 block text-xs font-medium text-text-muted">Proposed Fix</label>
		<textarea
			id="bug-fix"
			bind:value={fix}
			placeholder="Write the corrected code..."
			disabled={grading}
			rows="6"
			class="w-full resize-y rounded-lg border border-border bg-bg-muted px-4 py-3
				font-mono text-sm text-text placeholder:text-text-dim
				focus:border-accent focus:outline-none"
		></textarea>
	</div>

	<!-- Explanation -->
	<div>
		<label for="bug-explanation" class="mb-1 block text-xs font-medium text-text-muted">Explanation (optional)</label>
		<textarea
			id="bug-explanation"
			bind:value={explanation}
			placeholder="Why this is a bug and how the fix addresses it..."
			disabled={grading}
			rows="3"
			class="w-full resize-y rounded-lg border border-border bg-bg-muted px-4 py-3
				text-sm text-text placeholder:text-text-dim
				focus:border-accent focus:outline-none"
		></textarea>
	</div>
</div>

<button
	onclick={handleSubmit}
	disabled={grading || !hasContent}
	class="mt-3 w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-bg
		transition-colors hover:bg-accent/90 disabled:opacity-50"
>
	{#if grading}
		<span class="inline-flex items-center gap-2">
			<span class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-bg border-t-transparent"></span>
			Grading...
		</span>
	{:else}
		Submit Fix
	{/if}
</button>
