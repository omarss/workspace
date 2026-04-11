<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { app } from '$lib/stores/app.svelte';
	import { api } from '$lib/api/client';
	import * as prefsApi from '$lib/api/preferences';
	import {
		ROLES,
		QUESTION_FORMATS,
		ROLE_DISPLAY_NAMES,
		FORMAT_DISPLAY_NAMES,
		FORMAT_DESCRIPTIONS,
		getLanguagesForRoles,
		getFrameworksForRoles
	} from '$lib/data';

	type Step = 'roles' | 'languages' | 'frameworks' | 'formats' | 'length' | 'confirm';
	const STEPS: Step[] = ['roles', 'languages', 'frameworks', 'formats', 'length', 'confirm'];

	let step = $state<Step>('roles');
	let selectedRoles = $state<string[]>([]);
	let selectedLanguages = $state<string[]>([]);
	let selectedFrameworks = $state<string[]>([]);
	let selectedFormats = $state<string[]>([]);
	let questionLength = $state('standard');
	let loading = $state(true);
	let saving = $state(false);
	let isFirstSetup = $state(false);
	let resetting = $state(false);
	let clearing = $state(false);

	async function resetLevel() {
		if (!confirm('Reset all competency levels and assessment data? Your question history is kept.')) return;
		resetting = true;
		try {
			await api.post('preferences/reset-level');
			app.toast('Levels reset. You can re-assess from Today.', 'success');
		} catch {
			app.toast('Failed to reset levels', 'error');
		} finally {
			resetting = false;
		}
	}

	async function clearAllData() {
		if (!confirm('Delete ALL training data? This cannot be undone. Your account and preferences are kept.')) return;
		clearing = true;
		try {
			await api.post('preferences/clear-data');
			app.toast('All training data cleared.', 'success');
			goto('/today');
		} catch {
			app.toast('Failed to clear data', 'error');
		} finally {
			clearing = false;
		}
	}

	// Derived filtered lists
	const availableLanguages = $derived(getLanguagesForRoles(selectedRoles));
	const availableFrameworks = $derived(getFrameworksForRoles(selectedRoles, selectedLanguages));

	const stepIndex = $derived(STEPS.indexOf(step));

	onMount(async () => {
		try {
			const prefs = await prefsApi.getPreferences();
			selectedRoles = prefs.roles;
			selectedLanguages = prefs.languages;
			selectedFrameworks = prefs.frameworks;
			selectedFormats = prefs.preferred_formats ?? [];
			questionLength = prefs.question_length ?? 'standard';
		} catch {
			// No preferences yet — first setup
			isFirstSetup = true;
		}
		loading = false;
	});

	function toggleItem(list: string[], item: string): string[] {
		return list.includes(item) ? list.filter((i) => i !== item) : [...list, item];
	}

	function nextStep() {
		const idx = STEPS.indexOf(step);
		if (idx < STEPS.length - 1) {
			step = STEPS[idx + 1];
		}
	}

	function prevStep() {
		const idx = STEPS.indexOf(step);
		if (idx > 0) {
			step = STEPS[idx - 1];
		}
	}

	async function save() {
		saving = true;
		try {
			await prefsApi.updatePreferences({
				roles: selectedRoles,
				languages: selectedLanguages,
				frameworks: selectedFrameworks,
				preferred_formats: selectedFormats.length > 0 ? selectedFormats : null,
				question_length: questionLength
			});
			app.toast('Preferences saved', 'success');
			goto(isFirstSetup ? '/assess' : '/today');
		} catch {
			app.toast('Failed to save preferences', 'error');
		} finally {
			saving = false;
		}
	}

	function canProceed(): boolean {
		if (step === 'roles') return selectedRoles.length > 0;
		if (step === 'languages') return selectedLanguages.length > 0;
		return true;
	}
</script>

<div class="fade-in mx-auto max-w-2xl">
	{#if loading}
		<div class="flex h-64 items-center justify-center">
			<span class="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent"></span>
		</div>
	{:else}
		<!-- Step indicator -->
		<div class="mb-8 flex items-center justify-center gap-2">
			{#each STEPS as s, i}
				<div
					class="h-1.5 w-8 rounded-full transition-colors
						{i <= stepIndex ? 'bg-accent' : 'bg-border'}"
				></div>
			{/each}
		</div>

		<!-- Roles -->
		{#if step === 'roles'}
			<h2 class="mb-2 text-xl font-semibold">What's your primary role?</h2>
			<p class="mb-6 text-sm text-text-muted">Select one or more. This shapes which skills we train.</p>

			<div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
				{#each ROLES as role}
					<button
						onclick={() => (selectedRoles = toggleItem(selectedRoles, role))}
						class="rounded-lg border px-3 py-3 text-left text-sm transition-all
							{selectedRoles.includes(role)
								? 'border-accent bg-accent/10 text-text'
								: 'border-border bg-bg-muted text-text-muted hover:border-border hover:bg-bg-elevated'}"
					>
						{ROLE_DISPLAY_NAMES[role] ?? role}
					</button>
				{/each}
			</div>

		<!-- Languages -->
		{:else if step === 'languages'}
			<h2 class="mb-2 text-xl font-semibold">What languages do you code in?</h2>
			<p class="mb-6 text-sm text-text-muted">We'll generate questions and code snippets in these.</p>

			<div class="flex flex-wrap gap-2">
				{#each availableLanguages as lang}
					<button
						onclick={() => (selectedLanguages = toggleItem(selectedLanguages, lang))}
						class="rounded-full border px-3 py-1.5 text-sm transition-all
							{selectedLanguages.includes(lang)
								? 'border-accent bg-accent/10 text-accent'
								: 'border-border text-text-muted hover:border-accent/50'}"
					>
						{lang}
					</button>
				{/each}
			</div>

		<!-- Frameworks -->
		{:else if step === 'frameworks'}
			<h2 class="mb-2 text-xl font-semibold">Your stack</h2>
			<p class="mb-6 text-sm text-text-muted">Optional. Helps us generate scenarios that look like your real work.</p>

			<div class="flex flex-wrap gap-2">
				{#each availableFrameworks as fw}
					<button
						onclick={() => (selectedFrameworks = toggleItem(selectedFrameworks, fw))}
						class="rounded-full border px-3 py-1.5 text-sm transition-all
							{selectedFrameworks.includes(fw)
								? 'border-accent bg-accent/10 text-accent'
								: 'border-border text-text-muted hover:border-accent/50'}"
					>
						{fw}
					</button>
				{/each}
			</div>

		<!-- Formats -->
		{:else if step === 'formats'}
			<h2 class="mb-2 text-xl font-semibold">How do you learn best?</h2>
			<p class="mb-6 text-sm text-text-muted">Optional. We'll prioritize the formats you pick.</p>

			<div class="space-y-2">
				{#each QUESTION_FORMATS as fmt}
					<button
						onclick={() => (selectedFormats = toggleItem(selectedFormats, fmt))}
						class="flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-all
							{selectedFormats.includes(fmt)
								? 'border-accent bg-accent/10'
								: 'border-border bg-bg-muted hover:bg-bg-elevated'}"
					>
						<div>
							<div class="text-sm font-medium {selectedFormats.includes(fmt) ? 'text-text' : 'text-text-muted'}">
								{FORMAT_DISPLAY_NAMES[fmt] ?? fmt}
							</div>
							<div class="text-xs text-text-dim">{FORMAT_DESCRIPTIONS[fmt] ?? ''}</div>
						</div>
					</button>
				{/each}
			</div>

		<!-- Length -->
		{:else if step === 'length'}
			<h2 class="mb-2 text-xl font-semibold">Session style</h2>
			<p class="mb-6 text-sm text-text-muted">Controls question length and detail level.</p>

			<div class="space-y-2">
				{#each [
					{ value: 'concise', label: 'Quick reps', desc: 'Shorter prompts, faster pace' },
					{ value: 'standard', label: 'Balanced', desc: 'Standard detail and context' },
					{ value: 'detailed', label: 'Deep dive', desc: 'Rich context, longer code, real-world scenarios' }
				] as opt}
					<button
						onclick={() => (questionLength = opt.value)}
						class="flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-all
							{questionLength === opt.value
								? 'border-accent bg-accent/10'
								: 'border-border bg-bg-muted hover:bg-bg-elevated'}"
					>
						<div
							class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2
								{questionLength === opt.value ? 'border-accent' : 'border-border'}"
						>
							{#if questionLength === opt.value}
								<div class="h-2.5 w-2.5 rounded-full bg-accent"></div>
							{/if}
						</div>
						<div>
							<div class="text-sm font-medium {questionLength === opt.value ? 'text-text' : 'text-text-muted'}">{opt.label}</div>
							<div class="text-xs text-text-dim">{opt.desc}</div>
						</div>
					</button>
				{/each}
			</div>

		<!-- Confirm -->
		{:else if step === 'confirm'}
			<h2 class="mb-6 text-xl font-semibold">Your training profile</h2>

			<div class="space-y-4 rounded-xl border border-border bg-bg-subtle p-5 text-sm">
				<div>
					<span class="text-text-dim">Roles:</span>
					<span class="ml-2 text-text">{selectedRoles.map((r) => ROLE_DISPLAY_NAMES[r] ?? r).join(', ')}</span>
				</div>
				<div>
					<span class="text-text-dim">Languages:</span>
					<span class="ml-2 text-text">{selectedLanguages.join(', ')}</span>
				</div>
				{#if selectedFrameworks.length > 0}
					<div>
						<span class="text-text-dim">Frameworks:</span>
						<span class="ml-2 text-text">{selectedFrameworks.join(', ')}</span>
					</div>
				{/if}
				{#if selectedFormats.length > 0}
					<div>
						<span class="text-text-dim">Preferred formats:</span>
						<span class="ml-2 text-text">{selectedFormats.map((f) => FORMAT_DISPLAY_NAMES[f] ?? f).join(', ')}</span>
					</div>
				{/if}
				<div>
					<span class="text-text-dim">Session style:</span>
					<span class="ml-2 text-text capitalize">{questionLength === 'concise' ? 'Quick reps' : questionLength === 'detailed' ? 'Deep dive' : 'Balanced'}</span>
				</div>
			</div>

			{#if isFirstSetup}
				<div class="mt-4 rounded-xl border border-accent/20 bg-accent/5 p-4">
					<h3 class="mb-2 text-sm font-semibold text-accent">What happens next</h3>
					<ul class="space-y-1 text-xs text-text-muted">
						<li>10-minute calibration across your top competencies</li>
						<li>Adaptive skill map based on your answers</li>
						<li>Daily workouts generated from your weak areas</li>
					</ul>
				</div>
			{/if}
		{/if}

		<!-- Danger zone (only show after initial setup) -->
		{#if !isFirstSetup}
			<div class="mt-12 rounded-xl border border-error/20 p-5">
				<h3 class="mb-1 text-sm font-semibold text-error">Danger Zone</h3>
				<p class="mb-4 text-xs text-text-dim">These actions cannot be undone.</p>
				<div class="flex flex-wrap gap-2">
					<button
						onclick={resetLevel}
						disabled={resetting}
						class="rounded-lg border border-error/30 px-4 py-2 text-xs font-medium text-error transition-colors hover:bg-error/10 disabled:opacity-50"
					>
						{resetting ? 'Resetting...' : 'Reset Levels'}
					</button>
					<button
						onclick={clearAllData}
						disabled={clearing}
						class="rounded-lg border border-error/30 px-4 py-2 text-xs font-medium text-error transition-colors hover:bg-error/10 disabled:opacity-50"
					>
						{clearing ? 'Clearing...' : 'Clear All Data'}
					</button>
				</div>
			</div>
		{/if}

		<!-- Navigation buttons -->
		<div class="mt-8 flex justify-between">
			{#if stepIndex > 0}
				<button
					onclick={prevStep}
					class="rounded-lg border border-border px-4 py-2 text-sm text-text-muted transition-colors hover:text-text"
				>
					Back
				</button>
			{:else}
				<div></div>
			{/if}

			{#if step === 'confirm'}
				<button
					onclick={save}
					disabled={saving}
					class="rounded-lg bg-accent px-6 py-2 text-sm font-medium text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
				>
					{#if saving}
						Saving...
					{:else}
						{isFirstSetup ? 'Start Calibration' : 'Save Changes'}
					{/if}
				</button>
			{:else}
				<div class="flex items-center gap-3">
					{#if isFirstSetup && step === 'languages'}
						<button
							onclick={() => { step = 'confirm'; }}
							disabled={!canProceed()}
							class="rounded-lg bg-accent px-6 py-2 text-sm font-medium text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
						>
							Skip to Calibration
						</button>
						<button
							onclick={nextStep}
							disabled={!canProceed()}
							class="rounded-lg border border-border px-4 py-2 text-sm text-text-muted transition-colors hover:text-text"
						>
							Customize further
						</button>
					{:else}
						<button
							onclick={nextStep}
							disabled={!canProceed()}
							class="rounded-lg bg-accent px-6 py-2 text-sm font-medium text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
						>
							Next
						</button>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</div>
