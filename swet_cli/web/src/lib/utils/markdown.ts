import { marked } from 'marked';
import DOMPurify from 'dompurify';

// Configure marked for safe rendering
marked.setOptions({
	breaks: true,
	gfm: true
});

/** Render markdown to sanitized HTML */
export function renderMarkdown(text: string): string {
	const raw = marked.parse(text, { async: false }) as string;
	return DOMPurify.sanitize(raw);
}
