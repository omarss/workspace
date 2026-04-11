// Mirrors the API's Pydantic schemas exactly

// --- Auth ---

export interface RegisterRequest {
	email?: string | null;
	mobile?: string | null;
}

export interface OTPSendRequest {
	email?: string | null;
	mobile?: string | null;
}

export interface OTPVerifyRequest {
	email?: string | null;
	mobile?: string | null;
	code: string;
}

export interface RefreshRequest {
	refresh_token: string;
}

export interface TokenResponse {
	access_token: string;
	refresh_token: string;
	token_type: string;
}

export interface MessageResponse {
	message: string;
}

// --- Preferences ---

export interface PreferencesRequest {
	roles: string[];
	languages: string[];
	frameworks: string[];
	preferred_formats?: string[] | null;
	question_length?: string;
}

export interface PreferencesResponse {
	roles: string[];
	languages: string[];
	frameworks: string[];
	difficulty: number;
	preferred_formats: string[] | null;
	question_length: string;
}

// --- Questions ---

export interface GenerateRequest {
	competency_slug?: string | null;
	question_format?: string | null;
	difficulty?: number | null;
	count?: number;
}

export interface QuestionResponse {
	id: string;
	competency_slug: string;
	format: string;
	difficulty: number;
	title: string;
	body: string;
	code_snippet: string | null;
	language: string | null;
	options: Record<string, string> | null;
	explanation_detail?: {
		why_correct?: string;
		why_others_fail?: Record<string, string>;
		principle?: string;
	} | null;
	metadata: Record<string, unknown> | null;
}

// --- Attempts ---

export interface AnswerRequest {
	question_id: string;
	answer_text: string;
	time_seconds?: number | null;
	confidence?: number | null;
}

export interface CriterionScore {
	criterion: string;
	score: number;
	max_score: number;
	feedback: string;
}

export interface GradeResponse {
	attempt_id: string;
	score: number;
	max_score: number;
	total_score: number;
	normalized_score: number;
	criteria_scores: CriterionScore[] | null;
	overall_feedback: string;
	explanation: string | null;
	correct_answer: string | null;
}

// --- Stats ---

export interface StatsResponse {
	competency_slug: string;
	total_attempts: number;
	avg_score: number;
	min_score: number;
	max_score: number;
}

export interface StreakResponse {
	current_streak: number;
	longest_streak: number;
}

export interface CompetencyLevelResponse {
	slug: string;
	name: string;
	estimated_level: number | null;
	total_attempts: number;
}

// --- Bookmarks ---

export interface BookmarkResponse {
	id: string;
	title: string;
	competency_slug: string;
	format: string;
	difficulty: number;
	bookmarked_at: string | null;
}

// --- History ---

export interface AttemptHistory {
	id: string;
	question_id: string;
	title: string;
	competency_slug: string;
	format: string;
	difficulty: number;
	score: number;
	max_score: number;
	normalized_score: number;
	time_seconds: number | null;
	created_at: string;
}

// --- Assessments ---

export interface CompetencyResult {
	slug: string;
	name: string;
	estimated_level: number;
	confidence: number;
	posterior: Record<number, number>;
}

export interface AssessmentStartResponse {
	assessment_id: string;
	competencies: string[];
	total_questions: number;
	first_question: QuestionResponse;
	primary_language: string | null;
	assessment_phase: string;
}

export interface AssessmentAnswerRequest {
	answer: string;
}

export interface AssessmentAnswerResponse {
	correct: boolean;
	correct_answer: string;
	explanation: string | null;
	questions_completed: number;
	total_questions: number;
	is_complete: boolean;
	next_question: QuestionResponse | null;
	results: AssessmentResultsResponse | null;
	assessment_phase: string;
}

export interface AssessmentResultsResponse {
	assessment_id: string;
	status: string;
	competencies: CompetencyResult[];
	completed_at: string | null;
}

export interface AssessmentStateResponse {
	assessment_id: string;
	status: string;
	competencies: string[];
	questions_completed: number;
	total_questions: number;
	current_question: QuestionResponse | null;
	assessment_phase: string;
	primary_language: string | null;
}

// --- Sessions ---

export interface SessionStartRequest {
	count?: number;
	competency_slug?: string | null;
	question_format?: string | null;
	difficulty?: number | null;
	question_id?: string | null;
}

export interface SessionStateResponse {
	session_id: string;
	status: string;
	target_count: number;
	completed_count: number;
	current_question: QuestionResponse | null;
	started_at: string;
	competency_slug: string | null;
	question_format: string | null;
	difficulty: number | null;
}

export interface SessionStartResponse {
	session_id: string;
	target_count: number;
	first_question: QuestionResponse;
}

export interface SessionAnswerRequest {
	question_id: string;
	answer_text: string;
	time_seconds?: number | null;
	confidence?: number | null;
}

export interface SessionQuestionResult {
	question_id: string;
	title: string;
	competency_slug: string;
	format: string;
	score: number | null;
	time_seconds: number | null;
	sequence_num: number;
}

export interface SessionSummaryResponse {
	session_id: string;
	status: string;
	target_count: number;
	completed_count: number;
	avg_score: number | null;
	results: SessionQuestionResult[];
	started_at: string;
	completed_at: string | null;
}

export interface SessionAnswerResponse {
	grade: GradeResponse;
	completed_count: number;
	target_count: number;
	is_complete: boolean;
	next_question: QuestionResponse | null;
	summary: SessionSummaryResponse | null;
}

export interface SessionListItem {
	session_id: string;
	status: string;
	target_count: number;
	completed_count: number;
	avg_score: number | null;
	started_at: string;
	completed_at: string | null;
}

// --- Reviews ---

export interface ReviewItemResponse {
	id: string;
	question_id: string;
	title: string;
	competency_slug: string;
	format: string;
	difficulty: number;
	source: string;
	due_date: string;
	interval_days: number;
	review_count: number;
}

export interface ReviewCountResponse {
	due_today: number;
	due_this_week: number;
	total_pending: number;
}

// --- Dashboard ---

export interface DashboardResponse {
	streak: StreakResponse;
	review_due_count: number;
	has_completed_assessment: boolean;
	focus_competency: string | null;
	total_attempts: number;
	competencies_assessed: number;
}

// --- Enhanced Stats ---

export interface StreakCalendarResponse {
	year: number;
	month: number;
	active_days: number[];
}

export interface FormatPerformanceResponse {
	format: string;
	total_attempts: number;
	avg_score: number;
}

export interface WeakAreaResponse {
	competency_slug: string;
	avg_score: number;
	total_attempts: number;
}
