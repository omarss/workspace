<script lang="ts">
	import type { QuestionResponse } from '$lib/api/types';

	interface Props {
		question: QuestionResponse;
		grading: boolean;
		onAnswer: (answer: string) => void;
	}

	let { question, grading, onAnswer }: Props = $props();
	let architecture = $state('');
	let dataModel = $state('');
	let tradeoffs = $state('');
	let scalability = $state('');

	const sections = [
		{ key: 'architecture', label: 'Architecture', placeholder: 'Describe the high-level architecture, key components, and their interactions...', rows: 5 },
		{ key: 'dataModel', label: 'Data Model', placeholder: 'Define key entities, relationships, storage choices...', rows: 4 },
		{ key: 'tradeoffs', label: 'Key Trade-offs', placeholder: 'What trade-offs did you consider? Why did you choose this approach?', rows: 3 },
		{ key: 'scalability', label: 'Scalability', placeholder: 'How does this scale? What are the bottlenecks and mitigations?', rows: 3 }
	] as const;

	function getValue(key: string): string {
		if (key === 'architecture') return architecture;
		if (key === 'dataModel') return dataModel;
		if (key === 'tradeoffs') return tradeoffs;
		if (key === 'scalability') return scalability;
		return '';
	}

	function setValue(key: string, val: string) {
		if (key === 'architecture') architecture = val;
		else if (key === 'dataModel') dataModel = val;
		else if (key === 'tradeoffs') tradeoffs = val;
		else if (key === 'scalability') scalability = val;
	}

	function handleSubmit() {
		if (grading) return;
		const parts: string[] = [];
		if (architecture.trim()) parts.push(`## Architecture\n${architecture.trim()}`);
		if (dataModel.trim()) parts.push(`## Data Model\n${dataModel.trim()}`);
		if (tradeoffs.trim()) parts.push(`## Trade-offs\n${tradeoffs.trim()}`);
		if (scalability.trim()) parts.push(`## Scalability\n${scalability.trim()}`);
		const answer = parts.join('\n\n');
		if (answer) onAnswer(answer);
	}

	const hasContent = $derived(
		architecture.trim() || dataModel.trim() || tradeoffs.trim() || scalability.trim()
	);
</script>

<div class="space-y-4">
	{#each sections as section}
		<div>
			<label for="design-{section.key}" class="mb-1 block text-xs font-medium text-text-muted">{section.label}</label>
			<textarea
				id="design-{section.key}"
				value={getValue(section.key)}
				oninput={(e) => setValue(section.key, (e.target as HTMLTextAreaElement).value)}
				placeholder={section.placeholder}
				disabled={grading}
				rows={section.rows}
				class="w-full resize-y rounded-lg border border-border bg-bg-muted px-4 py-3
					text-sm text-text placeholder:text-text-dim
					focus:border-accent focus:outline-none"
			></textarea>
		</div>
	{/each}
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
		Submit Design
	{/if}
</button>
