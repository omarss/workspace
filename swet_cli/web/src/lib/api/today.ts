import { api } from './client';
import type { DashboardResponse } from './types';

export async function getDashboard(): Promise<DashboardResponse> {
	return api.get('dashboard').json<DashboardResponse>();
}
