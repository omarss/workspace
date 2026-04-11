<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { app } from '$lib/stores/app.svelte';
	import * as sessionsApi from '$lib/api/sessions';
	import type {
		QuestionResponse,
		GradeResponse,
		SessionQuestionResult,
		SessionStartRequest,
		SessionSummaryResponse
	} from '$lib/api/types';
	import QuestionCard from '$lib/components/QuestionCard.svelte';
	import GradeReveal from '$lib/components/GradeReveal.svelte';
	import { formatSlug, formatScore } from '$lib/utils/format';
	import { DIFFICULTY_BG_COLORS, DIFFICULTY_LABELS } from '$lib/data';

	type Phase = 'select' | 'loading' | 'question' | 'graded' | 'summary';

	let phase = $state<Phase>('select');
	let sessionId = $state<string | null>(null);
	let currentQuestion = $state<QuestionResponse | null>(null);
	let gradedQuestion = $state<QuestionResponse | null>(null);
	let currentGrade = $state<GradeResponse | null>(null);
	let completedCount = $state(0);
	let targetCount = $state(5);
	let summary = $state<SessionSummaryResponse | null>(null);
	let grading = $state(false);
	let timer = $state(0);
	let timerInterval: ReturnType<typeof setInterval> | null = null;
	let customCount = $state(5);

	const progressPercent = $derived(targetCount > 0 ? Math.round((completedCount / targetCount) * 100) : 0);

	onMount(async () => {
		// Check for an active session to resume
		try {
			const existing = await sessionsApi.getCurrentSession();
			if (existing && existing.current_question) {
				sessionId = existing.session_id;
				targetCount = existing.target_count;
				completedCount = existing.completed_count;
				currentQuestion = existing.current_question;
				phase = 'question';
				startTimer();
				return;
			}
		} catch {
			// No active session — continue to URL param handling
		}

		const mode = page.url.searchParams.get('mode');
		const competency = page.url.searchParams.get('competency');
		const difficulty = page.url.searchParams.get('difficulty');
		const questionId = page.url.searchParams.get('question_id');

		if (mode === 'workout') {
			await startSession({ count: 5 });
		} else if (mode === 'practice') {
			await startSession({ count: 10 });
		} else if (competency || difficulty || questionId) {
			await startSession({
				count: 1,
				competency_slug: competency,
				difficulty: difficulty ? Number(difficulty) : null,
				question_id: questionId,
			});
		}
	});

	onDestroy(() => stopTimer());

	async function startSession(req: SessionStartRequest) {
		phase = 'loading';
		targetCount = req.count ?? 5;
		try {
			const resp = await sessionsApi.startSession(req);
			sessionId = resp.session_id;
			targetCount = resp.target_count;
			currentQuestion = resp.first_question;
			completedCount = 0;
			phase = 'question';
			startTimer();
		} catch {
			app.toast('Failed to start session', 'error');
			phase = 'select';
		}
	}

	function startTimer() {
		stopTimer();
		timer = 0;
		timerInterval = setInterval(() => timer++, 1000);
	}

	function stopTimer() {
		if (timerInterval) {
			clearInterval(timerInterval);
			timerInterval = null;
		}
	}

	async function handleAnswer(answerText: string, confidence?: number | null) {
		if (!sessionId || !currentQuestion) return;
		grading = true;
		stopTimer();
		gradedQuestion = currentQuestion;

		try {
			const resp = await sessionsApi.submitSessionAnswer(sessionId, {
				question_id: currentQuestion.id,
				answer_text: answerText,
				time_seconds: timer,
				confidence: confidence ?? null
			});
			currentGrade = resp.grade;
			completedCount = resp.completed_count;

			if (resp.is_complete && resp.summary) {
				summary = resp.summary;
				phase = 'graded';
			} else if (resp.next_question) {
				currentQuestion = resp.next_question;
				phase = 'graded';
			} else {
				phase = 'graded';
			}
		} catch {
			app.toast('Failed to submit answer', 'error');
			startTimer();
		} finally {
			grading = false;
		}
	}

	function handleNext() {
		if (summary) {
			// Session complete — show summary
			phase = 'summary';
			return;
		}
		// Move to next question
		currentGrade = null;
		phase = 'question';
		startTimer();
	}

	async function endEarly() {
		if (!sessionId) return;
		stopTimer();
		try {
			summary = await sessionsApi.endSession(sessionId);
			phase = 'summary';
		} catch {
			app.toast('Failed to end session', 'error');
		}
	}

	function formatTimer(s: number): string {
		const m = Math.floor(s / 60);
		const sec = s % 60;
		return `${m}:${sec.toString().padStart(2, '0')}`;
	}
</script>

<div class="fade-in mx-auto max-w-2xl">
	{#if phase === 'select'}
		<h1 class="mb-6 text-xl font-semibold">Train</h1>

		<div class="space-y-3">
			<button
				onclick={() => startSession({ count: 5 })}
				class="w-full rounded-xl border border-accent/30 bg-accent/5 p-5 text-left transition-colors hover:bg-accent/10"
			>
				<h3 class="text-sm font-semibold text-accent">Workout</h3>
				<p class="mt-1 text-xs text-text-muted">5 adaptive questions across your weak areas</p>
			</button>

			<button
				onclick={() => startSession({ count: 10 })}
				class="w-full rounded-xl border border-border bg-bg-subtle p-5 text-left transition-colors hover:border-accent"
			>
				<h3 class="text-sm font-semibold">Quick Practice</h3>
				<p class="mt-1 text-xs text-text-muted">10 questions for broad practice</p>
			</button>

			<div class="rounded-xl border border-border bg-bg-subtle p-5">
				<h3 class="mb-3 text-sm font-semibold">Custom</h3>
				<div class="flex items-center gap-3">
					<input
						type="number"
						bind:value={customCount}
						min="1"
						max="20"
						class="w-20 rounded-lg border border-border bg-bg-muted px-3 py-2 text-center text-sm text-text"
					/>
					<span class="text-xs text-text-muted">questions</span>
					<button
						onclick={() => startSession({ count: customCount })}
						class="ml-auto rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg transition-colors hover:bg-accent/90"
					>
						Start
					</button>
				</div>
			</div>
		</div>

	{:else if phase === 'loading'}
		<div class="flex h-64 items-center justify-center">
			<span class="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
		</div>

	{:else if phase === 'question' && currentQuestion}
		<!-- Session header: progress + timer + end button -->
		<div class="mb-4">
			<div class="mb-2 flex items-center justify-between">
				<span class="text-xs text-text-dim">{completedCount}/{targetCount}</span>
				<div class="flex items-center gap-3">
					<span class="font-mono text-sm text-text-dim">{formatTimer(timer)}</span>
					<button onclick={endEarly} class="text-xs text-text-dim hover:text-error">End</button>
				</div>
			</div>
			<div class="h-1.5 overflow-hidden rounded-full bg-bg-muted">
				<div
					class="h-full rounded-full bg-accent transition-all duration-300"
					style="width: {progressPercent}%"
				></div>
			</div>
		</div>

		<QuestionCard
			question={currentQuestion}
			{grading}
			onAnswer={handleAnswer}
		/>

	{:else if phase === 'graded' && gradedQuestion && currentGrade}
		<!-- Session progress indicator -->
		<div class="mb-4 flex items-center justify-between text-xs text-text-dim">
			<span>{completedCount}/{targetCount} completed</span>
			{#if summary}
				<span class="text-success">Session complete!</span>
			{/if}
		</div>

		<GradeReveal
			question={gradedQuestion}
			grade={currentGrade}
			timeSeconds={timer}
			onNext={handleNext}
		/>

	{:else if phase === 'summary' && summary}
		<div class="py-6 text-center">
			<div class="mb-2 font-mono text-4xl text-success">&#10003;</div>
			<h1 class="mb-1 text-xl font-bold">Session Complete</h1>
			<p class="text-sm text-text-muted">
				{summary.completed_count} of {summary.target_count} questions answered
			</p>
		</div>

		<!-- Stats card -->
		<div class="mb-6 grid grid-cols-2 gap-3">
			<div class="rounded-xl border border-border bg-bg-subtle p-4 text-center">
				<div class="text-xs text-text-dim">Avg Score</div>
				<div class="mt-1 text-2xl font-bold {(summary.avg_score ?? 0) >= 0.8 ? 'text-success' : (summary.avg_score ?? 0) >= 0.5 ? 'text-warning' : 'text-error'}">
					{summary.avg_score != null ? formatScore(summary.avg_score) : '--'}
				</div>
			</div>
			<div class="rounded-xl border border-border bg-bg-subtle p-4 text-center">
				<div class="text-xs text-text-dim">Questions</div>
				<div class="mt-1 text-2xl font-bold">{summary.completed_count}</div>
			</div>
		</div>

		<!-- Per-question results -->
		{#if summary.results.length > 0}
			<div class="mb-6 rounded-xl border border-border bg-bg-subtle">
				<div class="border-b border-border px-5 py-3">
					<h2 class="text-sm font-semibold">Results</h2>
				</div>
				<div class="divide-y divide-border">
					{#each summary.results as result}
						{@const pct = result.score != null ? Math.round(result.score * 100) : null}
						<div class="flex items-center justify-between px-5 py-3">
							<div class="flex-1">
								<div class="text-sm">{result.title}</div>
								<div class="flex items-center gap-2 text-xs text-text-dim">
									<span>{formatSlug(result.competency_slug)}</span>
									<span class="rounded px-1 py-0.5 {DIFFICULTY_BG_COLORS[0] ?? ''}">
										{result.format}
									</span>
								</div>
							</div>
							{#if pct != null}
								<span class="font-mono text-sm font-bold {pct >= 80 ? 'text-success' : pct >= 50 ? 'text-warning' : 'text-error'}">
									{pct}%
								</span>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Actions -->
		<div class="flex gap-3">
			<button
				onclick={() => goto('/today')}
				class="flex-1 rounded-lg border border-border px-4 py-2.5 text-sm text-text-muted transition-colors hover:border-accent hover:text-text"
			>
				Back to Today
			</button>
			<button
				onclick={() => { phase = 'select'; summary = null; sessionId = null; }}
				class="flex-1 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-bg transition-colors hover:bg-accent/90"
			>
				Train Again
			</button>
		</div>
	{/if}
</div>
