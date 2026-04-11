<script lang="ts">
	import { onMount } from 'svelte';
	import { app } from '$lib/stores/app.svelte';
	import * as reviewApi from '$lib/api/review';
	import * as questionsApi from '$lib/api/questions';
	import * as attemptsApi from '$lib/api/attempts';
	import type { ReviewItemResponse, QuestionResponse, GradeResponse } from '$lib/api/types';
	import { formatSlug } from '$lib/utils/format';
	import { DIFFICULTY_LABELS, DIFFICULTY_BG_COLORS, FORMAT_DISPLAY_NAMES } from '$lib/data';
	import QuestionCard from '$lib/components/QuestionCard.svelte';
	import GradeReveal from '$lib/components/GradeReveal.svelte';

	type Filter = 'all' | 'incorrect' | 'bookmarked' | 'manual';
	type ReviewPhase = 'list' | 'answering' | 'rating';

	let items = $state<ReviewItemResponse[]>([]);
	let loading = $state(true);
	let filter = $state<Filter>('all');

	// Inline review state
	let reviewPhase = $state<ReviewPhase>('list');
	let activeItem = $state<ReviewItemResponse | null>(null);
	let activeQuestion = $state<QuestionResponse | null>(null);
	let reviewGrade = $state<GradeResponse | null>(null);
	let submitting = $state(false);

	const filteredItems = $derived(
		filter === 'all' ? items : items.filter((i) => i.source === filter)
	);

	const qualityOptions = [
		{ quality: 1, label: 'Again', style: 'border-error text-error hover:bg-error/10' },
		{ quality: 3, label: 'Hard', style: 'border-warning text-warning hover:bg-warning/10' },
		{ quality: 4, label: 'Good', style: 'border-accent text-accent hover:bg-accent/10' },
		{ quality: 5, label: 'Easy', style: 'border-success text-success hover:bg-success/10' },
	];

	onMount(async () => {
		try {
			items = await reviewApi.getReviewQueue(50);
		} catch {
			app.toast('Failed to load review queue', 'error');
		} finally {
			loading = false;
		}
	});

	async function startReview(item: ReviewItemResponse) {
		activeItem = item;
		reviewPhase = 'answering';
		try {
			activeQuestion = await questionsApi.getQuestion(item.question_id);
		} catch {
			app.toast('Failed to load question', 'error');
			reviewPhase = 'list';
			activeItem = null;
		}
	}

	async function handleReviewAnswer(answerText: string, confidence?: number | null) {
		if (!activeQuestion) return;
		submitting = true;
		try {
			reviewGrade = await attemptsApi.submitAnswer({
				question_id: activeQuestion.id,
				answer_text: answerText,
				time_seconds: 0,
				confidence: confidence ?? null,
			});
			reviewPhase = 'rating';
		} catch {
			app.toast('Failed to grade answer', 'error');
		} finally {
			submitting = false;
		}
	}

	async function rateReview(quality: number) {
		if (!activeItem) return;
		try {
			await reviewApi.completeReview(activeItem.id, quality);
			items = items.filter((i) => i.id !== activeItem!.id);
			app.toast('Review completed', 'success');
		} catch {
			app.toast('Failed to save review', 'error');
		}
		// Reset and return to list
		activeItem = null;
		activeQuestion = null;
		reviewGrade = null;
		reviewPhase = 'list';
	}

	function backToList() {
		activeItem = null;
		activeQuestion = null;
		reviewGrade = null;
		reviewPhase = 'list';
	}

	async function snooze(id: string) {
		try {
			await reviewApi.snoozeReview(id, 3);
			items = items.filter((i) => i.id !== id);
			app.toast('Snoozed for 3 days', 'info');
		} catch {
			app.toast('Failed to snooze', 'error');
		}
	}

	async function dismiss(id: string) {
		try {
			await reviewApi.dismissReview(id);
			items = items.filter((i) => i.id !== id);
			app.toast('Dismissed', 'info');
		} catch {
			app.toast('Failed to dismiss', 'error');
		}
	}

	function sourceLabel(source: string): string {
		if (source === 'incorrect') return 'Missed';
		if (source === 'bookmarked') return 'Saved';
		return 'Manual';
	}

	function sourceColor(source: string): string {
		if (source === 'incorrect') return 'text-error bg-error/10';
		if (source === 'bookmarked') return 'text-warning bg-warning/10';
		return 'text-text-muted bg-bg-muted';
	}
</script>

<div class="fade-in mx-auto max-w-2xl">
	{#if loading}
		<div class="flex h-64 items-center justify-center">
			<span class="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
		</div>

	{:else if reviewPhase === 'answering' && activeQuestion}
		<!-- Inline review: answer phase -->
		<div class="mb-4">
			<button onclick={backToList} class="text-xs text-text-dim hover:text-text">
				Back to Review Queue
			</button>
		</div>

		<QuestionCard
			question={activeQuestion}
			grading={submitting}
			onAnswer={handleReviewAnswer}
		/>

	{:else if reviewPhase === 'rating' && activeQuestion && reviewGrade}
		<!-- Inline review: grade + quality rating phase -->
		<div class="mb-4">
			<button onclick={backToList} class="text-xs text-text-dim hover:text-text">
				Back to Review Queue
			</button>
		</div>

		<GradeReveal
			question={activeQuestion}
			grade={reviewGrade}
			timeSeconds={0}
			onNext={() => {}}
			showNextButton={false}
			showFollowUpLinks={false}
		/>

		<!-- Quality rating (SM-2) -->
		<div class="mt-4 rounded-xl border border-border bg-bg-subtle p-5">
			<h3 class="mb-1 text-sm font-semibold">How well did you recall this?</h3>
			<p class="mb-4 text-xs text-text-dim">This determines when you'll see it again</p>
			<div class="grid grid-cols-4 gap-2">
				{#each qualityOptions as { quality, label, style }}
					<button
						onclick={() => rateReview(quality)}
						class="rounded-lg border px-3 py-2.5 text-sm font-medium transition-colors {style}"
					>
						{label}
					</button>
				{/each}
			</div>
		</div>

	{:else}
		<!-- List mode -->
		<div class="mb-6 flex items-center justify-between">
			<h1 class="text-xl font-semibold">Review</h1>
			{#if items.length > 0}
				<span class="rounded-full bg-warning/10 px-2.5 py-0.5 text-xs font-medium text-warning">
					{items.length} due
				</span>
			{/if}
		</div>

		<!-- Filter tabs -->
		<div class="mb-4 flex gap-1 rounded-lg border border-border bg-bg-muted p-1">
			{#each [['all', 'All'], ['incorrect', 'Missed'], ['bookmarked', 'Saved']] as [value, label]}
				<button
					onclick={() => filter = value as Filter}
					class="flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors
						{filter === value ? 'bg-bg-elevated text-text' : 'text-text-muted hover:text-text'}"
				>
					{label}
				</button>
			{/each}
		</div>

		{#if filteredItems.length === 0}
			<div class="py-20 text-center">
				<div class="mb-4 font-mono text-4xl text-success">&#10003;</div>
				<h2 class="mb-2 text-lg font-semibold">
					{items.length === 0 ? "You're all caught up!" : 'No items match this filter'}
				</h2>
				<p class="text-sm text-text-muted">
					{items.length === 0
						? 'Keep practicing and items will appear here for review.'
						: 'Try a different filter to see your review items.'}
				</p>
			</div>
		{:else}
			<div class="space-y-2">
				{#each filteredItems as item (item.id)}
					<div class="rounded-xl border border-border bg-bg-subtle p-4">
						<div class="flex items-start justify-between gap-3">
							<div class="flex-1">
								<h3 class="text-sm font-medium">{item.title}</h3>
								<div class="mt-1 flex flex-wrap items-center gap-2 text-xs">
									<span class="text-text-dim">{formatSlug(item.competency_slug)}</span>
									<span class="rounded px-1.5 py-0.5 {DIFFICULTY_BG_COLORS[item.difficulty] ?? 'bg-bg-muted'}">
										{DIFFICULTY_LABELS[item.difficulty] ?? ''}
									</span>
									<span class="text-text-dim">
										{FORMAT_DISPLAY_NAMES[item.format] ?? item.format}
									</span>
									<span class="rounded px-1.5 py-0.5 {sourceColor(item.source)}">
										{sourceLabel(item.source)}
									</span>
								</div>
							</div>
						</div>

						<!-- Actions -->
						<div class="mt-3 flex gap-2">
							<button
								onclick={() => startReview(item)}
								class="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-bg transition-colors hover:bg-accent/90"
							>
								Start Review
							</button>
							<button
								onclick={() => snooze(item.id)}
								class="rounded-md border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-accent hover:text-text"
							>
								Snooze 3d
							</button>
							<button
								onclick={() => dismiss(item.id)}
								class="rounded-md border border-border px-3 py-1.5 text-xs text-text-dim transition-colors hover:text-error"
							>
								Dismiss
							</button>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</div>
