import { api } from './client';
import type { ReviewCountResponse, ReviewItemResponse } from './types';

export async function getReviewQueue(limit: number = 20): Promise<ReviewItemResponse[]> {
	return api.get('reviews', { searchParams: { limit } }).json<ReviewItemResponse[]>();
}

export async function getReviewCount(): Promise<ReviewCountResponse> {
	return api.get('reviews/count').json<ReviewCountResponse>();
}

export async function completeReview(reviewId: string, quality: number): Promise<ReviewItemResponse> {
	return api.post(`reviews/${reviewId}/complete`, { json: { quality } }).json<ReviewItemResponse>();
}

export async function snoozeReview(reviewId: string, days: number): Promise<ReviewItemResponse> {
	return api.post(`reviews/${reviewId}/snooze`, { json: { days } }).json<ReviewItemResponse>();
}

export async function dismissReview(reviewId: string): Promise<void> {
	await api.delete(`reviews/${reviewId}`);
}
