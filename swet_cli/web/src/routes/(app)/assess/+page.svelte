<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { app } from '$lib/stores/app.svelte';
	import * as assessmentApi from '$lib/api/assessment';
	import * as prefsApi from '$lib/api/preferences';
	import type {
		QuestionResponse,
		AssessmentAnswerResponse,
		CompetencyResult
	} from '$lib/api/types';
	import { formatSlug } from '$lib/utils/format';
	import { DIFFICULTY_LABELS, DIFFICULTY_BG_COLORS, COMPETENCIES, selectAssessmentCompetencies } from '$lib/data';

	type Phase = 'intro' | 'self-eval' | 'loading' | 'question' | 'feedback' | 'part-transition' | 'complete' | 'error';

	let phase = $state<Phase>('intro');
	let assessmentId = $state<string | null>(null);
	let currentQuestion = $state<QuestionResponse | null>(null);
	let competencies = $state<string[]>([]);
	let questionsCompleted = $state(0);
	let totalQuestions = $state(0);
	let selectedOption = $state<string | null>(null);
	let lastAnswer = $state<AssessmentAnswerResponse | null>(null);
	let results = $state<CompetencyResult[]>([]);
	let assessmentPhase = $state<string>('concepts');
	let primaryLanguage = $state<string | null>(null);

	// Self-evaluation state
	let selfRatings = $state<Record<string, number>>({});
	const ratingLabels = [
		{ value: 0, label: 'No exposure', desc: 'Never worked with this' },
		{ value: 1, label: 'Beginner', desc: 'Know the basics' },
		{ value: 2, label: 'Some experience', desc: 'Have used it' },
		{ value: 3, label: 'Comfortable', desc: 'Work with it regularly' },
		{ value: 4, label: 'Strong', desc: 'Deep knowledge' },
	];

	const activeCount = $derived(Object.values(selfRatings).filter((r) => r > 0).length);
	// Per-part progress
	const partQuestions = 50;
	const partCompleted = $derived(assessmentPhase === 'concepts' ? questionsCompleted : questionsCompleted - partQuestions);
	const progressPercent = $derived(partQuestions > 0 ? Math.round((Math.max(0, partCompleted) / partQuestions) * 100) : 0);
	const partLabel = $derived(assessmentPhase === 'concepts' ? 'Part 1: Concepts' : `Part 2: ${primaryLanguage ?? 'Language'}`);

	onMount(async () => {
		// Check for existing in-progress assessment
		try {
			const existing = await assessmentApi.getCurrentAssessment();
			if (existing) {
				assessmentId = existing.assessment_id;
				competencies = existing.competencies;
				questionsCompleted = existing.questions_completed;
				totalQuestions = existing.total_questions;
				assessmentPhase = existing.assessment_phase;
				primaryLanguage = existing.primary_language;
				if (existing.current_question) {
					currentQuestion = existing.current_question;
					phase = 'question';
				} else {
					phase = 'intro';
				}
			}
		} catch {
			// No existing assessment
		}
	});

	async function goToSelfEval() {
		// Load competencies based on user's roles
		try {
			const prefs = await prefsApi.getPreferences();
			const slugs = selectAssessmentCompetencies(prefs.roles);
			competencies = slugs;
			// Default all to "Some experience" (2)
			selfRatings = Object.fromEntries(slugs.map((s) => [s, 2]));
			phase = 'self-eval';
		} catch {
			app.toast('Failed to load preferences', 'error');
		}
	}

	async function startWithRatings() {
		phase = 'loading';
		try {
			const resp = await assessmentApi.startAssessment(selfRatings);
			assessmentId = resp.assessment_id;
			competencies = resp.competencies;
			totalQuestions = resp.total_questions;
			questionsCompleted = 0;
			currentQuestion = resp.first_question;
			assessmentPhase = resp.assessment_phase;
			primaryLanguage = resp.primary_language;
			phase = 'question';
		} catch (e: unknown) {
			try {
				const body = await (e as { response?: Response }).response?.json();
				if (body?.detail?.includes('already in progress')) {
					const existing = await assessmentApi.getCurrentAssessment();
					if (existing) {
						assessmentId = existing.assessment_id;
						competencies = existing.competencies;
						questionsCompleted = existing.questions_completed;
						totalQuestions = existing.total_questions;
						if (existing.current_question) {
							currentQuestion = existing.current_question;
							phase = 'question';
						}
					}
					return;
				}
			} catch {}
			app.toast('Failed to start assessment', 'error');
			phase = 'error';
		}
	}

	async function startWithDefaults() {
		phase = 'loading';
		try {
			const resp = await assessmentApi.startAssessment();
			assessmentId = resp.assessment_id;
			competencies = resp.competencies;
			totalQuestions = resp.total_questions;
			questionsCompleted = 0;
			currentQuestion = resp.first_question;
			assessmentPhase = resp.assessment_phase;
			primaryLanguage = resp.primary_language;
			phase = 'question';
		} catch (e: unknown) {
			try {
				const body = await (e as { response?: Response }).response?.json();
				if (body?.detail?.includes('already in progress')) {
					const existing = await assessmentApi.getCurrentAssessment();
					if (existing) {
						assessmentId = existing.assessment_id;
						competencies = existing.competencies;
						questionsCompleted = existing.questions_completed;
						totalQuestions = existing.total_questions;
						if (existing.current_question) {
							currentQuestion = existing.current_question;
							phase = 'question';
						}
					}
					return;
				}
			} catch {}
			app.toast('Failed to start assessment', 'error');
			phase = 'error';
		}
	}

	async function submitAnswer() {
		if (!assessmentId || !selectedOption) return;
		phase = 'loading';
		try {
			const resp = await assessmentApi.submitAssessmentAnswer(assessmentId, { answer: selectedOption });
			lastAnswer = resp;
			questionsCompleted = resp.questions_completed;

			if (resp.is_complete && resp.results) {
				results = resp.results.competencies;
				phase = 'complete';
			} else if (resp.assessment_phase !== assessmentPhase) {
				// Transitioning from Part 1 to Part 2
				assessmentPhase = resp.assessment_phase;
				phase = 'part-transition';
			} else {
				phase = 'feedback';
			}
		} catch {
			app.toast('Failed to submit answer', 'error');
			phase = 'question';
		}
	}

	function nextQuestion() {
		if (lastAnswer?.next_question) {
			currentQuestion = lastAnswer.next_question;
			selectedOption = null;
			lastAnswer = null;
			phase = 'question';
		}
	}

	function levelColor(level: number): string {
		return DIFFICULTY_BG_COLORS[level] ?? 'bg-bg-muted text-text-dim';
	}
</script>

<div class="fade-in mx-auto max-w-2xl">
	{#if phase === 'intro'}
		<div class="py-12 text-center">
			<div class="mb-6 font-mono text-5xl text-accent">&lt;/&gt;</div>
			<h1 class="mb-3 text-2xl font-bold">Map Your Strengths</h1>
			<p class="mb-2 text-sm text-text-muted">
				100 adaptive questions in 2 parts: concepts + language-specific.
			</p>
			<p class="mb-8 text-xs text-text-dim">
				Rate your familiarity first. Skip areas you've never worked with.
			</p>

			<div class="flex flex-col items-center gap-3">
				<button
					onclick={goToSelfEval}
					class="rounded-lg bg-accent px-8 py-3 text-sm font-medium text-bg transition-colors hover:bg-accent/90"
				>
					{assessmentId ? 'Resume Assessment' : 'Start Calibration'}
				</button>
				<button
					onclick={startWithDefaults}
					class="text-xs text-text-dim hover:text-accent"
				>
					Skip self-evaluation
				</button>
			</div>
		</div>

	{:else if phase === 'self-eval'}
		<h1 class="mb-2 text-xl font-semibold">Rate your familiarity</h1>
		<p class="mb-6 text-sm text-text-muted">
			This shapes question difficulty. Areas marked "No exposure" will be skipped.
		</p>

		<div class="space-y-4">
			{#each competencies as slug}
				{@const name = COMPETENCIES[slug]?.name ?? formatSlug(slug)}
				{@const rating = selfRatings[slug] ?? 2}
				<div class="rounded-xl border border-border bg-bg-subtle p-4">
					<h3 class="mb-3 text-sm font-medium">{name}</h3>
					<div class="flex flex-wrap gap-1.5">
						{#each ratingLabels as opt}
							<button
								onclick={() => (selfRatings[slug] = opt.value)}
								class="rounded-md border px-2.5 py-1.5 text-xs transition-colors
									{rating === opt.value
										? opt.value === 0
											? 'border-text-dim bg-bg-muted text-text-dim'
											: 'border-accent bg-accent/10 text-accent'
										: 'border-border text-text-muted hover:border-accent/50'}"
							>
								{opt.label}
							</button>
						{/each}
					</div>
				</div>
			{/each}
		</div>

		<div class="mt-6 flex items-center justify-between">
			<button
				onclick={() => (phase = 'intro')}
				class="rounded-lg border border-border px-4 py-2 text-sm text-text-muted transition-colors hover:text-text"
			>
				Back
			</button>
			<div class="flex items-center gap-4">
				<span class="text-xs text-text-dim">{activeCount} of {competencies.length} active</span>
				<button
					onclick={startWithRatings}
					disabled={activeCount === 0}
					class="rounded-lg bg-accent px-6 py-2.5 text-sm font-medium text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
				>
					Start ({activeCount * 3} questions)
				</button>
			</div>
		</div>

	{:else if phase === 'loading'}
		<div class="flex h-64 items-center justify-center">
			<span class="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
		</div>

	{:else if phase === 'question' && currentQuestion}
		<!-- Progress bar -->
		<div class="mb-6">
			<div class="mb-1 text-xs font-medium text-accent">{partLabel}</div>
			<div class="mb-2 flex items-center justify-between text-xs text-text-dim">
				<span>Question {Math.max(1, partCompleted + 1)} of {partQuestions}</span>
				<span>{progressPercent}%</span>
			</div>
			<div class="h-1.5 overflow-hidden rounded-full bg-bg-muted">
				<div
					class="h-full rounded-full bg-accent transition-all duration-500"
					style="width: {progressPercent}%"
				></div>
			</div>
			{#if currentQuestion.competency_slug}
				<p class="mt-2 text-xs text-text-muted">{formatSlug(currentQuestion.competency_slug)}</p>
			{/if}
		</div>

		<!-- Question -->
		<div class="rounded-xl border border-border bg-bg-subtle p-6">
			<h2 class="mb-4 text-sm font-semibold">{currentQuestion.title}</h2>

			{#if currentQuestion.body}
				<p class="mb-6 text-sm text-text-muted">{currentQuestion.body}</p>
			{/if}

			{#if currentQuestion.code_snippet}
				<div class="mb-6 overflow-x-auto rounded-lg border border-border bg-bg p-4">
					<pre class="text-sm leading-relaxed"><code>{currentQuestion.code_snippet}</code></pre>
				</div>
			{/if}

			{#if currentQuestion.options}
				<div class="space-y-2">
					{#each Object.entries(currentQuestion.options) as [key, value], i}
						<button
							onclick={() => (selectedOption = key)}
							class="flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left text-sm transition-colors
								{selectedOption === key
									? 'border-accent bg-accent/10 text-text'
									: 'border-border bg-bg hover:border-accent/50'}"
						>
							<span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-medium
								{selectedOption === key ? 'border-accent bg-accent text-bg' : 'border-border text-text-muted'}">
								{String.fromCharCode(65 + i)}
							</span>
							<span>{value}</span>
						</button>
					{/each}
				</div>

				<button
					onclick={submitAnswer}
					disabled={!selectedOption}
					class="mt-6 w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
				>
					Submit
				</button>
			{/if}
		</div>

	{:else if phase === 'feedback' && lastAnswer}
		<div class="rounded-xl border border-border bg-bg-subtle p-6 text-center">
			<div class="mb-4 text-4xl">{lastAnswer.correct ? '&#10003;' : '&#10007;'}</div>
			<p class="mb-2 text-sm font-semibold {lastAnswer.correct ? 'text-success' : 'text-error'}">
				{lastAnswer.correct ? 'Correct!' : 'Not quite'}
			</p>
			{#if !lastAnswer.correct && lastAnswer.correct_answer}
				<p class="mb-4 text-xs text-text-muted">Best answer: {lastAnswer.correct_answer}</p>
			{/if}
			<p class="mb-6 text-xs text-text-dim">
				{questionsCompleted} of {totalQuestions} completed
			</p>
			<button
				onclick={nextQuestion}
				class="rounded-lg bg-accent px-6 py-2.5 text-sm font-medium text-bg transition-colors hover:bg-accent/90"
			>
				Next Question
			</button>
		</div>

	{:else if phase === 'part-transition'}
		<div class="py-12 text-center">
			<div class="mb-4 font-mono text-4xl text-success">&#10003;</div>
			<h1 class="mb-3 text-xl font-bold">Part 1 Complete</h1>
			<p class="mb-2 text-sm text-text-muted">
				Concepts assessed. Now testing your <span class="font-semibold text-accent">{primaryLanguage}</span> knowledge.
			</p>
			<p class="mb-8 text-xs text-text-dim">
				50 language-specific questions with code snippets and idioms.
			</p>
			<button
				onclick={nextQuestion}
				class="rounded-lg bg-accent px-8 py-3 text-sm font-medium text-bg transition-colors hover:bg-accent/90"
			>
				Start Part 2
			</button>
		</div>

	{:else if phase === 'complete'}
		<div class="py-8 text-center">
			<div class="mb-4 font-mono text-4xl text-success">&#10003;</div>
			<h1 class="mb-2 text-2xl font-bold">Assessment Complete</h1>
			<p class="mb-8 text-sm text-text-muted">Here's your mastery map across {results.length} competencies.</p>
		</div>

		<!-- Mastery grid -->
		<div class="mb-8 grid gap-3 sm:grid-cols-2">
			{#each results as cr}
				<div class="rounded-xl border border-border bg-bg-subtle p-4">
					<div class="mb-2 flex items-center justify-between">
						<h3 class="text-sm font-medium">{cr.name}</h3>
						<span class="rounded-md px-2 py-0.5 text-xs font-medium {levelColor(cr.estimated_level)}">
							{DIFFICULTY_LABELS[cr.estimated_level] ?? `L${cr.estimated_level}`}
						</span>
					</div>
					<div class="mb-1 text-xs text-text-dim">Confidence: {Math.round(cr.confidence * 100)}%</div>
					<div class="h-1.5 overflow-hidden rounded-full bg-bg-muted">
						<div
							class="h-full rounded-full bg-accent transition-all duration-700"
							style="width: {cr.confidence * 100}%"
						></div>
					</div>
					<!-- Posterior distribution -->
					<div class="mt-2 flex gap-1">
						{#each [1, 2, 3, 4, 5] as level}
							{@const prob = cr.posterior[level] ?? 0}
							<div class="flex-1">
								<div
									class="rounded-sm {level === cr.estimated_level ? 'bg-accent' : 'bg-bg-muted'}"
									style="height: {Math.max(2, prob * 40)}px"
								></div>
								<div class="mt-0.5 text-center text-[9px] text-text-dim">L{level}</div>
							</div>
						{/each}
					</div>
				</div>
			{/each}
		</div>

		<div class="text-center">
			<button
				onclick={() => goto('/today')}
				class="rounded-lg bg-accent px-8 py-3 text-sm font-medium text-bg transition-colors hover:bg-accent/90"
			>
				Start Training
			</button>
		</div>

	{:else if phase === 'error'}
		<div class="py-20 text-center">
			<p class="text-sm text-error">Something went wrong. Please try again.</p>
			<button
				onclick={goToSelfEval}
				class="mt-4 rounded-lg bg-accent px-6 py-2.5 text-sm font-medium text-bg"
			>
				Retry
			</button>
		</div>
	{/if}
</div>
