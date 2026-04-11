<script lang="ts">
	import { onMount } from 'svelte';
	import type { QuestionResponse, GradeResponse } from '$lib/api/types';
	import { formatSlug, formatTime, formatScore } from '$lib/utils/format';
	import { renderMarkdown } from '$lib/utils/markdown';
	import { addBookmark, removeBookmark, listBookmarks } from '$lib/api/bookmarks';
	import { app } from '$lib/stores/app.svelte';

	interface Props {
		question: QuestionResponse;
		grade: GradeResponse;
		timeSeconds: number;
		onNext: () => void;
		showNextButton?: boolean;
		showFollowUpLinks?: boolean;
	}

	let { question, grade, timeSeconds, onNext, showNextButton = true, showFollowUpLinks = true }: Props = $props();

	let bookmarked = $state(false);

	// Check if already bookmarked
	onMount(async () => {
		try {
			const bookmarks = await listBookmarks();
			bookmarked = bookmarks.some((b) => b.id === question.id);
		} catch {
			// Non-critical — default to false
		}
	});
	let showExplanation = $state(false);

	const scorePercent = $derived(Math.round(grade.normalized_score * 100));
	const scoreColor = $derived(
		scorePercent >= 80 ? 'text-success' : scorePercent >= 50 ? 'text-warning' : 'text-error'
	);

	async function toggleBookmark() {
		try {
			if (bookmarked) {
				await removeBookmark(question.id);
				bookmarked = false;
			} else {
				await addBookmark(question.id);
				bookmarked = true;
			}
		} catch {
			app.toast('Failed to update bookmark', 'error');
		}
	}
</script>

<div class="fade-in space-y-4">
	<!-- Score card -->
	<div class="rounded-xl border border-border bg-bg-subtle p-6 text-center">
		<!-- Circular score indicator -->
		<div class="mx-auto mb-4 flex h-28 w-28 items-center justify-center">
			<svg viewBox="0 0 100 100" class="h-full w-full -rotate-90">
				<circle cx="50" cy="50" r="42" fill="none" stroke="var(--color-border)" stroke-width="6" />
				<circle
					cx="50"
					cy="50"
					r="42"
					fill="none"
					stroke={scorePercent >= 80 ? 'var(--color-success)' : scorePercent >= 50 ? 'var(--color-warning)' : 'var(--color-error)'}
					stroke-width="6"
					stroke-linecap="round"
					stroke-dasharray="{scorePercent * 2.64} {264 - scorePercent * 2.64}"
					class="transition-all duration-1000 ease-out"
				/>
			</svg>
			<span class="absolute font-mono text-2xl font-bold {scoreColor}">
				{scorePercent}%
			</span>
		</div>

		<p class="text-sm text-text-muted">
			{grade.score}/{grade.max_score} points in {formatTime(timeSeconds)}
		</p>

		<!-- Competency + Difficulty -->
		<p class="mt-2 text-xs text-text-dim">
			{formatSlug(question.competency_slug)}
		</p>
	</div>

	<!-- Feedback -->
	<div class="rounded-xl border border-border bg-bg-subtle p-5">
		<h3 class="mb-3 text-sm font-semibold">
			{scorePercent >= 80 ? 'Strong answer' : scorePercent >= 50 ? 'Partial credit' : 'Not quite'}
		</h3>
		<div class="markdown-body text-sm text-text-muted">
			{@html renderMarkdown(grade.overall_feedback)}
		</div>
	</div>

	<!-- Criteria breakdown -->
	{#if grade.criteria_scores && grade.criteria_scores.length > 0}
		<div class="rounded-xl border border-border bg-bg-subtle p-5">
			<h3 class="mb-3 text-sm font-semibold">Criteria Breakdown</h3>
			<div class="space-y-3">
				{#each grade.criteria_scores as criterion}
					<div>
						<div class="flex items-center justify-between text-xs">
							<span class="text-text-muted">{criterion.criterion}</span>
							<span class="font-mono">{criterion.score}/{criterion.max_score}</span>
						</div>
						<div class="mt-1 h-1.5 overflow-hidden rounded-full bg-bg-muted">
							<div
								class="h-full rounded-full transition-all duration-700 ease-out
									{criterion.score / criterion.max_score >= 0.8 ? 'bg-success' :
									criterion.score / criterion.max_score >= 0.5 ? 'bg-warning' : 'bg-error'}"
								style="width: {(criterion.score / criterion.max_score) * 100}%"
							></div>
						</div>
						{#if criterion.feedback}
							<p class="mt-1 text-xs text-text-dim">{criterion.feedback}</p>
						{/if}
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Structured explanation (if available) -->
	{#if question.explanation_detail}
		{@const detail = question.explanation_detail}
		{#if grade.correct_answer && detail.why_correct}
			<div class="rounded-xl border border-success/20 bg-success/5 p-5">
				<h3 class="mb-2 text-sm font-semibold text-success">Why {grade.correct_answer} is strongest</h3>
				<p class="text-sm text-text-muted">{detail.why_correct}</p>
			</div>
		{/if}

		{#if detail.why_others_fail && Object.keys(detail.why_others_fail).length > 0}
			<div class="rounded-xl border border-error/20 bg-error/5 p-5">
				<h3 class="mb-2 text-sm font-semibold text-error">Why other options fall short</h3>
				<div class="space-y-2">
					{#each Object.entries(detail.why_others_fail) as [letter, reason]}
						<p class="text-sm text-text-muted"><span class="font-mono font-semibold text-text-dim">{letter}.</span> {reason}</p>
					{/each}
				</div>
			</div>
		{/if}

		{#if detail.principle}
			<div class="rounded-xl border border-accent/20 bg-accent/5 p-5">
				<h3 class="mb-2 text-sm font-semibold text-accent">Rule to remember</h3>
				<p class="text-sm text-text">{detail.principle}</p>
			</div>
		{/if}

	<!-- Fallback: plain correct answer + explanation -->
	{:else}
		{#if grade.correct_answer}
			<div class="rounded-xl border border-success/20 bg-success/5 p-5">
				<h3 class="mb-2 text-sm font-semibold text-success">Best answer: {grade.correct_answer}</h3>
			</div>
		{/if}

		{#if grade.explanation}
			<button
				onclick={() => (showExplanation = !showExplanation)}
				class="w-full rounded-xl border border-border bg-bg-subtle p-4 text-left text-sm text-text-muted transition-colors hover:bg-bg-elevated"
			>
				<span class="font-medium text-text">{showExplanation ? 'Hide' : 'Show'} Explanation</span>
			</button>
			{#if showExplanation}
				<div class="rounded-xl border border-border bg-bg-subtle p-5">
					<div class="markdown-body text-sm text-text-muted">
						{@html renderMarkdown(grade.explanation)}
					</div>
				</div>
			{/if}
		{/if}
	{/if}

	<!-- Primary actions -->
	<div class="flex gap-3">
		{#if showNextButton}
			<button
				onclick={onNext}
				class="flex-1 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-bg transition-colors hover:bg-accent/90"
			>
				Next Question
			</button>
		{/if}
		<button
			onclick={toggleBookmark}
			class="rounded-lg border px-4 py-2.5 text-sm transition-colors
				{bookmarked ? 'border-warning bg-warning/10 text-warning' : 'border-border text-text-muted hover:border-accent hover:text-accent'}"
		>
			{bookmarked ? 'Bookmarked' : 'Bookmark'}
		</button>
	</div>

	<!-- Follow-up actions -->
	{#if showFollowUpLinks}
		<div class="flex flex-wrap gap-2">
			{#if question.difficulty > 1}
				<a
					href="/train?competency={question.competency_slug}&difficulty={question.difficulty - 1}"
					class="rounded-md border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-accent hover:text-text"
				>
					Easier Version
				</a>
			{/if}
			{#if question.difficulty < 5}
				<a
					href="/train?competency={question.competency_slug}&difficulty={question.difficulty + 1}"
					class="rounded-md border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-accent hover:text-text"
				>
					Harder Version
				</a>
			{/if}
			<a
				href="/train?competency={question.competency_slug}"
				class="rounded-md border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-accent hover:text-text"
			>
				Same Topic
			</a>
		</div>
	{/if}
</div>
