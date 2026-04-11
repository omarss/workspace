<script lang="ts">
	import { onMount } from 'svelte';
	import * as statsApi from '$lib/api/stats';
	import * as attemptsApi from '$lib/api/attempts';
	import type {
		StatsResponse,
		StreakResponse,
		CompetencyLevelResponse,
		FormatPerformanceResponse,
		WeakAreaResponse,
		StreakCalendarResponse,
		AttemptHistory
	} from '$lib/api/types';
	import { DIFFICULTY_LABELS, DIFFICULTY_BG_COLORS, FORMAT_DISPLAY_NAMES } from '$lib/data';
	import { formatSlug, formatScore, timeAgo } from '$lib/utils/format';

	let stats = $state<StatsResponse[]>([]);
	let streak = $state<StreakResponse | null>(null);
	let competencies = $state<CompetencyLevelResponse[]>([]);
	let formatPerf = $state<FormatPerformanceResponse[]>([]);
	let weakAreas = $state<WeakAreaResponse[]>([]);
	let calendar = $state<StreakCalendarResponse | null>(null);
	let history = $state<AttemptHistory[]>([]);
	let loading = $state(true);
	let showHistory = $state(false);

	onMount(async () => {
		try {
			const [s, st, c, fp, wa, cal, h] = await Promise.all([
				statsApi.getStats(),
				statsApi.getStreak(),
				statsApi.getCompetencyLevels(),
				statsApi.getFormatPerformance(),
				statsApi.getWeakAreas(3),
				statsApi.getStreakCalendar(),
				attemptsApi.getHistory(20)
			]);
			stats = s;
			streak = st;
			competencies = c;
			formatPerf = fp;
			weakAreas = wa;
			calendar = cal;
			history = h;
		} catch {
			// partial failure is ok
		} finally {
			loading = false;
		}
	});

	const rankedCompetencies = $derived(
		[...competencies]
			.filter((c) => c.estimated_level !== null)
			.sort((a, b) => (b.estimated_level ?? 0) - (a.estimated_level ?? 0) || b.total_attempts - a.total_attempts)
	);

	const unassessedCompetencies = $derived(
		competencies.filter((c) => c.estimated_level === null)
	);

	const totalAttempts = $derived(stats.reduce((acc, s) => acc + s.total_attempts, 0));
	const avgScore = $derived(
		stats.length > 0 ? stats.reduce((acc, s) => acc + s.avg_score, 0) / stats.length : 0
	);

	// Calendar: generate days array for current month
	const daysInMonth = $derived(
		calendar ? new Date(calendar.year, calendar.month, 0).getDate() : 0
	);
	const firstDayOffset = $derived(
		calendar ? new Date(calendar.year, calendar.month - 1, 1).getDay() : 0
	);
</script>

<div class="fade-in">
	{#if loading}
		<div class="flex h-64 items-center justify-center">
			<span class="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
		</div>
	{:else}
		<h1 class="mb-6 text-xl font-semibold">Progress</h1>

		<!-- Top stats -->
		<div class="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
			<div class="rounded-xl border border-border bg-bg-subtle p-4">
				<div class="text-xs text-text-dim">Streak</div>
				<div class="mt-1 flex items-center gap-1.5">
					<span class="text-2xl font-bold text-warning">{streak?.current_streak ?? 0}</span>
					<svg class="h-5 w-5 text-warning" viewBox="0 0 24 24" fill="currentColor">
						<path d="M12 23c-3.3 0-6-2.7-6-6 0-2.6 1.7-5 2.8-6.5l1.3-1.8C11 7.2 12 4 12 1c2.3 3.3 5 6.2 5 10 0 1-.2 2-.5 2.8L18 11c.3.8.5 1.6.5 2.5-.1 5.2-3.2 9.5-6.5 9.5z"/>
					</svg>
				</div>
			</div>
			<div class="rounded-xl border border-border bg-bg-subtle p-4">
				<div class="text-xs text-text-dim">Best streak</div>
				<div class="mt-1 text-2xl font-bold">{streak?.longest_streak ?? 0}</div>
			</div>
			<div class="rounded-xl border border-border bg-bg-subtle p-4">
				<div class="text-xs text-text-dim">Questions</div>
				<div class="mt-1 text-2xl font-bold">{totalAttempts}</div>
			</div>
			<div class="rounded-xl border border-border bg-bg-subtle p-4">
				<div class="text-xs text-text-dim">Avg score</div>
				<div class="mt-1 text-2xl font-bold">{totalAttempts > 0 ? formatScore(avgScore) : '--'}</div>
			</div>
		</div>

		<!-- Streak calendar -->
		{#if calendar && daysInMonth > 0}
			<div class="mb-6 rounded-xl border border-border bg-bg-subtle p-5">
				<h2 class="mb-3 text-sm font-semibold">
					Activity — {new Date(calendar.year, calendar.month - 1).toLocaleDateString('en', { month: 'long', year: 'numeric' })}
				</h2>
				<div class="grid grid-cols-7 gap-1">
					{#each ['S', 'M', 'T', 'W', 'T', 'F', 'S'] as day}
						<div class="text-center text-[10px] text-text-dim">{day}</div>
					{/each}
					{#each Array(firstDayOffset) as _}
						<div></div>
					{/each}
					{#each Array(daysInMonth) as _, i}
						{@const day = i + 1}
						{@const active = calendar.active_days.includes(day)}
						<div
							class="mx-auto h-4 w-4 rounded-sm {active ? 'bg-accent' : 'bg-bg-muted'}"
							title="{calendar.year}-{String(calendar.month).padStart(2, '0')}-{String(day).padStart(2, '0')}"
						></div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Weak areas -->
		{#if weakAreas.length > 0}
			<div class="mb-6 rounded-xl border border-warning/20 bg-warning/5 p-5">
				<h2 class="mb-3 text-sm font-semibold text-warning">Focus Areas</h2>
				<div class="space-y-2">
					{#each weakAreas as area}
						<div class="flex items-center justify-between">
							<span class="text-sm text-text-muted">{formatSlug(area.competency_slug)}</span>
							<div class="flex items-center gap-2">
								<span class="font-mono text-xs text-error">{formatScore(area.avg_score)}</span>
								<a
									href="/train?competency={area.competency_slug}"
									class="rounded-md bg-warning/10 px-2 py-0.5 text-xs text-warning hover:bg-warning/20"
								>
									Practice
								</a>
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Competency levels -->
		{#if rankedCompetencies.length > 0}
			<div class="mb-6 rounded-xl border border-border bg-bg-subtle">
				<div class="border-b border-border px-5 py-3">
					<h2 class="text-sm font-semibold">Competency Levels</h2>
				</div>
				<div class="divide-y divide-border">
					{#each rankedCompetencies as comp}
						{@const stat = stats.find((s) => s.competency_slug === comp.slug)}
						<div class="flex items-center justify-between px-5 py-3">
							<div>
								<div class="text-sm">{formatSlug(comp.slug)}</div>
								<div class="text-xs text-text-dim">
									{comp.total_attempts} attempts
									{#if stat}
										· avg {formatScore(stat.avg_score)}
									{/if}
								</div>
							</div>
							<span class="rounded-md px-2 py-0.5 text-xs font-medium {DIFFICULTY_BG_COLORS[comp.estimated_level ?? 0] ?? 'bg-bg-muted text-text-dim'}">
								{DIFFICULTY_LABELS[comp.estimated_level ?? 0] ?? '--'}
							</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Format performance -->
		{#if formatPerf.length > 0}
			<div class="mb-6 rounded-xl border border-border bg-bg-subtle p-5">
				<h2 class="mb-3 text-sm font-semibold">Format Performance</h2>
				<div class="space-y-3">
					{#each formatPerf as fp}
						{@const pct = Math.round(fp.avg_score * 100)}
						<div>
							<div class="flex items-center justify-between text-xs">
								<span class="text-text-muted">{FORMAT_DISPLAY_NAMES[fp.format] ?? fp.format}</span>
								<span class="font-mono">{pct}% · {fp.total_attempts} attempts</span>
							</div>
							<div class="mt-1 h-1.5 overflow-hidden rounded-full bg-bg-muted">
								<div
									class="h-full rounded-full transition-all duration-700
										{pct >= 80 ? 'bg-success' : pct >= 50 ? 'bg-warning' : 'bg-error'}"
									style="width: {pct}%"
								></div>
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Unassessed competencies -->
		{#if unassessedCompetencies.length > 0}
			<div class="mb-6 rounded-xl border border-border bg-bg-subtle">
				<div class="border-b border-border px-5 py-3">
					<h2 class="text-sm font-semibold text-text-muted">Not yet assessed</h2>
				</div>
				<div class="px-5 py-3">
					<div class="flex flex-wrap gap-2">
						{#each unassessedCompetencies as comp}
							<span class="rounded-md bg-bg-muted px-2 py-1 text-xs text-text-dim">
								{formatSlug(comp.slug)}
							</span>
						{/each}
					</div>
				</div>
			</div>
		{/if}

		<!-- Recent history (collapsible) -->
		{#if history.length > 0}
			<div class="rounded-xl border border-border bg-bg-subtle">
				<button
					onclick={() => (showHistory = !showHistory)}
					class="flex w-full items-center justify-between border-b border-border px-5 py-3 text-left"
				>
					<h2 class="text-sm font-semibold">Recent History</h2>
					<span class="text-xs text-text-dim">{showHistory ? 'Hide' : 'Show'}</span>
				</button>
				{#if showHistory}
					<div class="divide-y divide-border">
						{#each history as attempt}
							{@const pct = Math.round(attempt.normalized_score * 100)}
							<div class="flex items-center gap-4 px-5 py-3">
								<div class="w-12 text-right font-mono text-sm font-bold {pct >= 80 ? 'text-success' : pct >= 50 ? 'text-warning' : 'text-error'}">
									{pct}%
								</div>
								<div class="flex-1">
									<div class="text-sm">{attempt.title}</div>
									<div class="flex flex-wrap items-center gap-2 text-xs text-text-dim">
										<span>{formatSlug(attempt.competency_slug)}</span>
										<span class="rounded px-1 py-0.5 {DIFFICULTY_BG_COLORS[attempt.difficulty] ?? ''}">
											{DIFFICULTY_LABELS[attempt.difficulty] ?? ''}
										</span>
										<span>{FORMAT_DISPLAY_NAMES[attempt.format] ?? attempt.format}</span>
									</div>
								</div>
								<div class="text-xs text-text-dim">{timeAgo(attempt.created_at)}</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

		{#if stats.length === 0 && rankedCompetencies.length === 0}
			<div class="py-20 text-center">
				<p class="text-sm text-text-muted">No stats yet. Answer some questions to see your progress.</p>
			</div>
		{/if}
	{/if}
</div>
