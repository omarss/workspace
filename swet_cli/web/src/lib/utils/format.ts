/** Format a competency slug to a readable name */
export function formatSlug(slug: string): string {
	return slug
		.replace(/_/g, ' ')
		.replace(/\b\w/g, (c) => c.toUpperCase())
		.replace(/And /g, '& ')
		.replace(/Ci Cd/g, 'CI/CD')
		.replace(/Llm/g, 'LLM')
		.replace(/Ai /g, 'AI ')
		.replace(/Mlops/g, 'MLOps')
		.replace(/Api /g, 'API ')
		.replace(/Qa /g, 'QA ');
}

/** Format seconds to mm:ss */
export function formatTime(seconds: number): string {
	const m = Math.floor(seconds / 60);
	const s = Math.floor(seconds % 60);
	return `${m}:${s.toString().padStart(2, '0')}`;
}

/** Format a score as percentage */
export function formatScore(normalized: number): string {
	return `${Math.round(normalized * 100)}%`;
}

/** Relative time (e.g., "2h ago", "3d ago") */
export function timeAgo(dateStr: string): string {
	const now = Date.now();
	const then = new Date(dateStr).getTime();
	const diff = now - then;
	const mins = Math.floor(diff / 60000);
	if (mins < 1) return 'just now';
	if (mins < 60) return `${mins}m ago`;
	const hours = Math.floor(mins / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	if (days < 30) return `${days}d ago`;
	return new Date(dateStr).toLocaleDateString();
}
