import { api } from './client';
import type {
	AssessmentAnswerRequest,
	AssessmentAnswerResponse,
	AssessmentResultsResponse,
	AssessmentStartResponse,
	AssessmentStateResponse
} from './types';

export async function startAssessment(
	selfRatings?: Record<string, number>
): Promise<AssessmentStartResponse> {
	const body = selfRatings ? { self_ratings: selfRatings } : {};
	return api.post('assessments', { json: body }).json<AssessmentStartResponse>();
}

export async function getCurrentAssessment(): Promise<AssessmentStateResponse | null> {
	return api.get('assessments/current').json<AssessmentStateResponse | null>();
}

export async function submitAssessmentAnswer(
	assessmentId: string,
	req: AssessmentAnswerRequest
): Promise<AssessmentAnswerResponse> {
	return api.post(`assessments/${assessmentId}/answer`, { json: req }).json<AssessmentAnswerResponse>();
}

export async function finalizeAssessment(assessmentId: string): Promise<AssessmentResultsResponse> {
	return api.post(`assessments/${assessmentId}/finalize`).json<AssessmentResultsResponse>();
}

export async function getAssessmentResults(assessmentId: string): Promise<AssessmentResultsResponse> {
	return api.get(`assessments/${assessmentId}`).json<AssessmentResultsResponse>();
}

export async function cancelAssessment(assessmentId: string): Promise<void> {
	await api.delete(`assessments/${assessmentId}`);
}
