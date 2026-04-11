<script lang="ts">
	import type { QuestionResponse } from '$lib/api/types';

	interface Props {
		question: QuestionResponse;
		grading: boolean;
		onAnswer: (answer: string) => void;
	}

	let { question, grading, onAnswer }: Props = $props();
	let annotations = $state<Record<number, string>>({});
	let activeLine = $state<number | null>(null);
	let generalComment = $state('');

	const codeLines = $derived(question.code_snippet?.split('\n') ?? []);

	function toggleLine(lineNum: number) {
		if (grading) return;
		if (activeLine === lineNum) {
			activeLine = null;
		} else {
			activeLine = lineNum;
			if (!annotations[lineNum]) annotations[lineNum] = '';
		}
	}

	function handleSubmit() {
		if (grading) return;
		// Serialize annotations + general comment as the answer
		const parts: string[] = [];
		for (const [line, comment] of Object.entries(annotations)) {
			if (comment.trim()) {
				parts.push(`Line ${line}: ${comment.trim()}`);
			}
		}
		if (generalComment.trim()) {
			parts.push(`\nOverall: ${generalComment.trim()}`);
		}
		const answer = parts.length > 0 ? parts.join('\n') : generalComment.trim();
		if (answer) onAnswer(answer);
	}

	const hasContent = $derived(
		Object.values(annotations).some((v) => v.trim()) || generalComment.trim()
	);
</script>

<!-- Code with line annotations -->
{#if codeLines.length > 0}
	<div class="mb-4 overflow-x-auto rounded-lg border border-border bg-bg">
		{#each codeLines as line, i}
			{@const lineNum = i + 1}
			<div class="group flex border-b border-border/50 last:border-0">
				<button
					onclick={() => toggleLine(lineNum)}
					class="w-10 shrink-0 border-r border-border/50 py-1 text-right text-xs
						{annotations[lineNum]?.trim() ? 'bg-warning/10 text-warning' : 'text-text-dim hover:bg-accent/10 hover:text-accent'}"
				>
					{lineNum}
				</button>
				<pre class="flex-1 py-1 pl-3 pr-4 text-sm leading-relaxed"><code>{line}</code></pre>
			</div>
			{#if activeLine === lineNum}
				<div class="border-b border-accent/30 bg-accent/5 px-3 py-2">
					<input
						type="text"
						bind:value={annotations[lineNum]}
						placeholder="Add annotation for line {lineNum}..."
						class="w-full rounded border border-border bg-bg-muted px-2 py-1.5 text-xs text-text placeholder:text-text-dim focus:border-accent focus:outline-none"
						disabled={grading}
					/>
				</div>
			{/if}
		{/each}
	</div>
{/if}

<!-- General review comment -->
<p class="mb-1 text-xs text-text-dim">Click line numbers to annotate specific lines, or add a general review below.</p>
<textarea
	bind:value={generalComment}
	placeholder="Overall review comments..."
	disabled={grading}
	rows="4"
	class="w-full resize-y rounded-lg border border-border bg-bg-muted px-4 py-3
		font-mono text-sm text-text placeholder:text-text-dim
		focus:border-accent focus:outline-none"
></textarea>

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
		Submit Review
	{/if}
</button>
