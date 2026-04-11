<script lang="ts">
	import type { QuestionResponse } from '$lib/api/types';
	import { DIFFICULTY_BG_COLORS, DIFFICULTY_LABELS, FORMAT_DISPLAY_NAMES } from '$lib/data';
	import { formatSlug } from '$lib/utils/format';
	import { renderMarkdown } from '$lib/utils/markdown';
	import McqQuestion from './formats/McqQuestion.svelte';
	import CodeReviewQuestion from './formats/CodeReviewQuestion.svelte';
	import DebuggingQuestion from './formats/DebuggingQuestion.svelte';
	import DesignPromptQuestion from './formats/DesignPromptQuestion.svelte';
	import ShortAnswerQuestion from './formats/ShortAnswerQuestion.svelte';

	interface Props {
		question: QuestionResponse;
		grading: boolean;
		onAnswer: (answer: string, confidence?: number | null) => void;
	}

	let { question, grading, onAnswer }: Props = $props();

	let confidence = $state<number | null>(null);
	const confidenceLabels = ['Guessing', 'Unsure', 'Maybe', 'Confident', 'Certain'];

	function handleFormatAnswer(answer: string) {
		onAnswer(answer, confidence);
	}
</script>

<div class="fade-in rounded-xl border border-border bg-bg-subtle">
	<!-- Header -->
	<div class="flex flex-wrap items-center gap-2 border-b border-border px-5 py-3">
		<span class="rounded-md bg-bg-muted px-2 py-0.5 text-xs font-medium text-text-muted">
			{formatSlug(question.competency_slug)}
		</span>
		<span class="rounded-md px-2 py-0.5 text-xs font-medium {DIFFICULTY_BG_COLORS[question.difficulty] ?? ''}">
			{DIFFICULTY_LABELS[question.difficulty] ?? `L${question.difficulty}`}
		</span>
		<span class="rounded-md bg-bg-muted px-2 py-0.5 text-xs text-text-dim">
			{FORMAT_DISPLAY_NAMES[question.format] ?? question.format}
		</span>
	</div>

	<!-- Body -->
	<div class="p-5">
		<h2 class="mb-4 text-lg font-semibold leading-snug">{question.title}</h2>

		<div class="markdown-body text-sm text-text-muted">
			{@html renderMarkdown(question.body)}
		</div>

		<!-- Code snippet (shown for non-code-review formats; code review handles its own) -->
		{#if question.code_snippet && question.format !== 'code_review'}
			<div class="mt-4 overflow-x-auto rounded-lg border border-border bg-bg p-4">
				<pre class="text-sm leading-relaxed"><code>{question.code_snippet}</code></pre>
			</div>
		{/if}
	</div>

	<!-- Format-specific answer area -->
	<div class="border-t border-border p-5">
		<!-- Confidence selector (shown when user starts interacting) -->
		<div class="mb-4 flex items-center gap-1.5">
			<span class="text-xs text-text-dim">Confidence:</span>
			{#each [1, 2, 3, 4, 5] as level}
				<button
					onclick={() => (confidence = confidence === level ? null : level)}
					class="rounded-md px-2 py-1 text-xs transition-colors
						{confidence === level ? 'bg-accent text-bg' : 'bg-bg-muted text-text-dim hover:text-text'}"
				>
					{confidenceLabels[level - 1]}
				</button>
			{/each}
		</div>

		{#if question.format === 'mcq' && question.options}
			<McqQuestion {question} {grading} onAnswer={handleFormatAnswer} />
		{:else if question.format === 'code_review'}
			<CodeReviewQuestion {question} {grading} onAnswer={handleFormatAnswer} />
		{:else if question.format === 'debugging'}
			<DebuggingQuestion {question} {grading} onAnswer={handleFormatAnswer} />
		{:else if question.format === 'design_prompt'}
			<DesignPromptQuestion {question} {grading} onAnswer={handleFormatAnswer} />
		{:else}
			<ShortAnswerQuestion {question} {grading} onAnswer={handleFormatAnswer} />
		{/if}
	</div>
</div>
