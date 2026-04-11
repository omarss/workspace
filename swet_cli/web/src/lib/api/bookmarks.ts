import { api } from './client';
import type { BookmarkResponse } from './types';

export async function listBookmarks(limit: number = 50): Promise<BookmarkResponse[]> {
	return api.get('bookmarks', { searchParams: { limit } }).json<BookmarkResponse[]>();
}

export async function addBookmark(questionId: string): Promise<void> {
	await api.post(`bookmarks/${questionId}`);
}

export async function removeBookmark(questionId: string): Promise<void> {
	await api.delete(`bookmarks/${questionId}`);
}
