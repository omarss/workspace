import { api } from './client';
import type {
	SessionAnswerRequest,
	SessionAnswerResponse,
	SessionListItem,
	SessionStartRequest,
	SessionStartResponse,
	SessionStateResponse,
	SessionSummaryResponse
} from './types';

export async function startSession(req: SessionStartRequest = {}): Promise<SessionStartResponse> {
	return api.post('sessions', { json: req }).json<SessionStartResponse>();
}

export async function getCurrentSession(): Promise<SessionStateResponse | null> {
	return api.get('sessions/current').json<SessionStateResponse | null>();
}

export async function submitSessionAnswer(
	sessionId: string,
	req: SessionAnswerRequest
): Promise<SessionAnswerResponse> {
	return api.post(`sessions/${sessionId}/answer`, { json: req }).json<SessionAnswerResponse>();
}

export async function endSession(sessionId: string): Promise<SessionSummaryResponse> {
	return api.post(`sessions/${sessionId}/end`).json<SessionSummaryResponse>();
}

export async function getSession(sessionId: string): Promise<SessionSummaryResponse> {
	return api.get(`sessions/${sessionId}`).json<SessionSummaryResponse>();
}

export async function getSessionHistory(limit: number = 20): Promise<SessionListItem[]> {
	return api.get('sessions/history', { searchParams: { limit } }).json<SessionListItem[]>();
}
