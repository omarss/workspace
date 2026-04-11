import { api } from './client';
import type { AnswerRequest, GradeResponse, AttemptHistory } from './types';

export async function submitAnswer(data: AnswerRequest): Promise<GradeResponse> {
	return api.post('attempts', { json: data }).json<GradeResponse>();
}

export async function getHistory(limit: number = 20): Promise<AttemptHistory[]> {
	return api
		.get('attempts/history', { searchParams: { limit } })
		.json<AttemptHistory[]>();
}
