import { api } from './client';
import type { GenerateRequest, QuestionResponse } from './types';

export async function generateQuestions(
	data: GenerateRequest = {}
): Promise<QuestionResponse[]> {
	return api.post('questions/generate', { json: data }).json<QuestionResponse[]>();
}

export async function getNextQuestion(params?: {
	competency?: string;
	format?: string;
	difficulty?: number;
}): Promise<QuestionResponse | null> {
	const searchParams = new URLSearchParams();
	if (params?.competency) searchParams.set('competency', params.competency);
	if (params?.format) searchParams.set('format', params.format);
	if (params?.difficulty) searchParams.set('difficulty', String(params.difficulty));

	return api
		.get('questions/next', { searchParams })
		.json<QuestionResponse | null>();
}

export async function getQuestion(id: string): Promise<QuestionResponse> {
	return api.get(`questions/${id}`).json<QuestionResponse>();
}
