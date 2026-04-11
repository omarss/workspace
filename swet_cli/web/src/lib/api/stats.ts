import { api } from './client';
import type {
	StatsResponse,
	StreakResponse,
	CompetencyLevelResponse,
	StreakCalendarResponse,
	FormatPerformanceResponse,
	WeakAreaResponse
} from './types';

export async function getStats(): Promise<StatsResponse[]> {
	return api.get('stats').json<StatsResponse[]>();
}

export async function getStreak(): Promise<StreakResponse> {
	return api.get('stats/streak').json<StreakResponse>();
}

export async function getCompetencyLevels(): Promise<CompetencyLevelResponse[]> {
	return api.get('stats/competencies').json<CompetencyLevelResponse[]>();
}

export async function getStreakCalendar(year?: number, month?: number): Promise<StreakCalendarResponse> {
	const params: Record<string, number> = {};
	if (year) params.year = year;
	if (month) params.month = month;
	return api.get('stats/calendar', { searchParams: params }).json<StreakCalendarResponse>();
}

export async function getFormatPerformance(): Promise<FormatPerformanceResponse[]> {
	return api.get('stats/format-performance').json<FormatPerformanceResponse[]>();
}

export async function getWeakAreas(limit: number = 5): Promise<WeakAreaResponse[]> {
	return api.get('stats/weak-areas', { searchParams: { limit } }).json<WeakAreaResponse[]>();
}
