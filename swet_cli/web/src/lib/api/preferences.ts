import { api } from './client';
import type { PreferencesRequest, PreferencesResponse } from './types';

export async function getPreferences(): Promise<PreferencesResponse> {
	return api.get('preferences').json<PreferencesResponse>();
}

export async function updatePreferences(
	data: PreferencesRequest
): Promise<PreferencesResponse> {
	return api.put('preferences', { json: data }).json<PreferencesResponse>();
}
