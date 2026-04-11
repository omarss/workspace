<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { app } from '$lib/stores/app.svelte';
	import * as questionsApi from '$lib/api/questions';
	import * as prefsApi from '$lib/api/preferences';
	import * as todayApi from '$lib/api/today';
	import * as attemptsApi from '$lib/api/attempts';
	import type { QuestionResponse, GradeResponse, DashboardResponse } from '$lib/api/types';
	import QuestionCard from '$lib/components/QuestionCard.svelte';
	import GradeReveal from '$lib/components/GradeReveal.svelte';
	import { formatSlug } from '$lib/utils/format';
	import { DIFFICULTY_LABELS, DIFFICULTY_BG_COLORS } from '$lib/data';

	let dashboard = $state<DashboardResponse | null>(null);
	let question = $state<QuestionResponse | null>(null);
	let grade = $state<GradeResponse | null>(null);
	let pageState = $state<'loading' | 'no-prefs' | 'hub' | 'question' | 'graded'>('loading');
	let generating = $state(false);
	let grading = $state(false);
	let timer = $state(0);
	let timerInterval: ReturnType<typeof setInterval> | null = null;

	onMount(async () => {
		try {
			await prefsApi.getPreferences();
		} catch {
			pageState = 'no-prefs';
			return;
		}

		// Load dashboard data
		try {
			dashboard = await todayApi.getDashboard();
		} catch {
			// Fallback: still show hub even if dashboard fails
			dashboard = null;
		}

		pageState = 'hub';
	});

	onDestroy(() => stopTimer());

	async function startPractice() {
		pageState = 'loading';
		try {
			question = await questionsApi.getNextQuestion();
			if (!question) {
				generating = true;
				await questionsApi.generateQuestions({ count: 10 });
				question = await questionsApi.getNextQuestion();
				generating = false;
			}
			if (question) {
				pageState = 'question';
				startTimer();
			} else {
				app.toast('Failed to load question', 'error');
				pageState = 'hub';
			}
		} catch {
			generating = false;
			app.toast('Failed to generate questions', 'error');
			pageState = 'hub';
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
		if (!question) return;
		grading = true;
		stopTimer();

		try {
			grade = await attemptsApi.submitAnswer({
				question_id: question.id,
				answer_text: answerText,
				time_seconds: timer,
				confidence: confidence ?? null
			});
			pageState = 'graded';
			// Refresh dashboard in background
			todayApi.getDashboard().then((d) => (dashboard = d)).catch(() => {});
		} catch {
			app.toast('Failed to submit answer', 'error');
			startTimer();
		} finally {
			grading = false;
		}
	}

	async function handleNext() {
		pageState = 'loading';
		try {
			question = await questionsApi.getNextQuestion();
			if (!question) {
				questionsApi.generateQuestions({ count: 10 }).catch(() => {});
				question = await questionsApi.getNextQuestion();
			}
			if (question) {
				grade = null;
				timer = 0;
				pageState = 'question';
				startTimer();
			} else {
				pageState = 'hub';
			}
		} catch {
			pageState = 'hub';
		}
	}

	function formatTimer(s: number): string {
		const m = Math.floor(s / 60);
		const sec = s % 60;
		return `${m}:${sec.toString().padStart(2, '0')}`;
	}
</script>

<div class="fade-in">
	{#if pageState === 'loading'}
		<div class="flex h-64 items-center justify-center">
			<span class="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
		</div>

	{:else if pageState === 'no-prefs'}
		<div class="mx-auto max-w-md py-20 text-center">
			<div class="mb-4 font-mono text-4xl text-accent">{'{ }'}</div>
			<h2 class="mb-2 text-xl font-semibold">Welcome to SWET</h2>
			<p class="mb-6 text-sm text-text-muted">
				Set up your profile to get personalized questions tailored to your role and tech stack.
			</p>
			<a
				href="/settings"
				class="inline-block rounded-lg bg-accent px-6 py-2.5 text-sm font-medium text-bg transition-colors hover:bg-accent/90"
			>
				Set Up Profile
			</a>
		</div>

	{:else if pageState === 'hub'}
		<h1 class="mb-6 text-xl font-semibold">Today</h1>

		<!-- Top stats row -->
		<div class="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
			<!-- Streak -->
			<div class="rounded-xl border border-border bg-bg-subtle p-4">
				<div class="text-xs text-text-dim">Streak</div>
				<div class="mt-1 flex items-center gap-1.5">
					<span class="text-2xl font-bold text-warning">{dashboard?.streak.current_streak ?? 0}</span>
					<svg class="h-5 w-5 text-warning" viewBox="0 0 24 24" fill="currentColor">
						<path d="M12 23c-3.3 0-6-2.7-6-6 0-2.6 1.7-5 2.8-6.5l1.3-1.8C11 7.2 12 4 12 1c2.3 3.3 5 6.2 5 10 0 1-.2 2-.5 2.8L18 11c.3.8.5 1.6.5 2.5-.1 5.2-3.2 9.5-6.5 9.5z"/>
					</svg>
				</div>
			</div>

			<!-- Total -->
			<div class="rounded-xl border border-border bg-bg-subtle p-4">
				<div class="text-xs text-text-dim">Questions</div>
				<div class="mt-1 text-2xl font-bold">{dashboard?.total_attempts ?? 0}</div>
			</div>

			<!-- Competencies -->
			<div class="rounded-xl border border-border bg-bg-subtle p-4">
				<div class="text-xs text-text-dim">Assessed</div>
				<div class="mt-1 text-2xl font-bold">{dashboard?.competencies_assessed ?? 0}</div>
			</div>

			<!-- Review -->
			<div class="rounded-xl border border-border bg-bg-subtle p-4">
				<div class="text-xs text-text-dim">Due review</div>
				<div class="mt-1 flex items-center gap-2">
					<span class="text-2xl font-bold {(dashboard?.review_due_count ?? 0) > 0 ? 'text-warning' : ''}">
						{dashboard?.review_due_count ?? 0}
					</span>
				</div>
			</div>
		</div>

		<!-- Primary CTA -->
		{#if (dashboard?.review_due_count ?? 0) > 0}
			<a
				href="/review"
				class="mb-4 block rounded-xl border border-warning/30 bg-warning/10 p-6 transition-colors hover:bg-warning/15"
			>
				<div class="flex items-center justify-between">
					<div>
						<h3 class="text-base font-bold text-warning">Review {dashboard?.review_due_count} Item{dashboard?.review_due_count === 1 ? '' : 's'}</h3>
						<p class="mt-1 text-sm text-text-muted">
							Strengthen recall on missed and saved drills
						</p>
						<p class="mt-2 text-xs text-text-dim">~{(dashboard?.review_due_count ?? 1) * 2} min</p>
					</div>
					<svg class="h-6 w-6 text-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
					</svg>
				</div>
			</a>
		{:else if !dashboard?.has_completed_assessment}
			<a
				href="/assess"
				class="mb-4 block rounded-xl border border-accent/30 bg-accent/10 p-6 transition-colors hover:bg-accent/15"
			>
				<div class="flex items-center justify-between">
					<div>
						<h3 class="text-base font-bold text-accent">Calibrate Your Level</h3>
						<p class="mt-1 text-sm text-text-muted">Take a quick assessment to map your strengths</p>
						<p class="mt-2 text-xs text-text-dim">~8 min</p>
					</div>
					<svg class="h-6 w-6 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
					</svg>
				</div>
			</a>
		{:else}
			<a
				href="/train?mode=workout"
				class="mb-4 block rounded-xl border border-accent/30 bg-accent/10 p-6 transition-colors hover:bg-accent/15"
			>
				<div class="flex items-center justify-between">
					<div>
						<h3 class="text-base font-bold text-accent">Start Today's Workout</h3>
						<p class="mt-1 text-sm text-text-muted">
							5 adaptive questions{dashboard?.focus_competency ? ` — focusing on ${formatSlug(dashboard.focus_competency)}` : ''}
						</p>
						<p class="mt-2 text-xs text-text-dim">~10 min</p>
					</div>
					<svg class="h-6 w-6 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
					</svg>
				</div>
			</a>
		{/if}

		<!-- Secondary actions -->
		<div class="grid grid-cols-2 gap-3">
			<button
				onclick={startPractice}
				disabled={generating}
				class="rounded-xl border border-border bg-bg-subtle p-4 text-left transition-colors hover:border-accent"
			>
				<h3 class="text-sm font-semibold">1-Question Drill</h3>
				<p class="mt-1 text-xs text-text-muted">~2 min</p>
			</button>

			{#if (dashboard?.review_due_count ?? 0) > 0}
				<!-- Workout as secondary when review is primary -->
				<a
					href="/train?mode=workout"
					class="rounded-xl border border-border bg-bg-subtle p-4 transition-colors hover:border-accent"
				>
					<h3 class="text-sm font-semibold">Workout</h3>
					<p class="mt-1 text-xs text-text-muted">5 questions, ~10 min</p>
				</a>
			{:else if dashboard?.focus_competency}
				<a
					href="/train?competency={dashboard.focus_competency}"
					class="rounded-xl border border-border bg-bg-subtle p-4 transition-colors hover:border-accent"
				>
					<h3 class="text-sm font-semibold">Focus: {formatSlug(dashboard.focus_competency)}</h3>
					<p class="mt-1 text-xs text-text-muted">Weakest area</p>
				</a>
			{:else}
				<a
					href="/train?mode=practice"
					class="rounded-xl border border-border bg-bg-subtle p-4 transition-colors hover:border-accent"
				>
					<h3 class="text-sm font-semibold">Extended Practice</h3>
					<p class="mt-1 text-xs text-text-muted">10 questions, ~20 min</p>
				</a>
			{/if}
		</div>

	{:else if pageState === 'question' && question}
		<!-- Back to hub -->
		<div class="mb-4 flex items-center justify-between">
			<button onclick={() => { stopTimer(); pageState = 'hub'; }} class="text-xs text-text-dim hover:text-text">
				Back to Today
			</button>
			<span class="font-mono text-sm text-text-dim">{formatTimer(timer)}</span>
		</div>

		<QuestionCard
			{question}
			{grading}
			onAnswer={handleAnswer}
		/>

	{:else if pageState === 'graded' && question && grade}
		<GradeReveal
			{question}
			{grade}
			timeSeconds={timer}
			onNext={handleNext}
		/>
	{/if}
</div>
