/**
 * Shared TypeScript types mirroring backend schemas.
 */

// Auth
export interface User {
  id: string;
  github_id: number;
  github_username: string;
  email: string | null;
  avatar_url: string | null;
  is_active: boolean;
  is_anonymous: boolean;
  onboarding_completed: boolean;
  created_at: string;
}

// Onboarding
export interface TechnologySelection {
  languages: string[];
  frameworks: string[];
}

export interface UserProfile {
  id: string;
  user_id: string;
  primary_role: string;
  interests: string[];
  technologies: TechnologySelection;
  experience_years: number | null;
  config_hash: string | null;
}

export interface OnboardingOptions {
  roles: string[];
  interests: string[];
  languages: string[];
  frameworks: string[];
}

// Assessment
export interface Assessment {
  id: string;
  status: "in_progress" | "completed";
  total_questions: number;
  current_question_index: number;
  is_timed: boolean;
  time_limit_minutes: number | null;
  started_at: string;
  completed_at: string | null;
}

export interface AssessmentQuestion {
  id: string;
  competency_id: number;
  format: QuestionFormat;
  difficulty: number;
  title: string;
  body: string;
  code_snippet: string | null;
  language: string | null;
  options: Record<string, string> | null;
  position: number;
}

export type QuestionFormat =
  | "mcq"
  | "code_review"
  | "debugging"
  | "short_answer"
  | "design_prompt";

export interface AssessmentProgress {
  assessment_id: string;
  total_questions: number;
  answered_count: number;
  current_index: number;
  time_elapsed_seconds: number | null;
  time_remaining_seconds: number | null;
}

// Results
export interface CompetencyScore {
  competency_id: number;
  competency_name: string | null;
  score: number;
  proficiency_level: number;
  questions_total: number;
  questions_correct: number;
  ai_graded_avg: number | null;
}

export interface AssessmentResult {
  id: string;
  assessment_id: string;
  overall_score: number;
  overall_proficiency_level: number;
  proficiency_label: string;
  total_time_seconds: number;
  grading_status: string;
  competency_scores: CompetencyScore[];
  created_at: string;
}

export interface RadarDataPoint {
  competency: string;
  score: number;
  max_score: number;
}

// History
export interface ResultSummary {
  id: string;
  assessment_id: string;
  overall_score: number;
  proficiency_label: string;
  total_time_seconds: number;
  grading_status: string;
  created_at: string;
}

export interface HistoryResponse {
  items: ResultSummary[];
  total_count: number;
  page: number;
  per_page: number;
}

export interface HistoryStats {
  total_assessments: number;
  average_score: number;
  highest_score: number;
  latest_proficiency_label: string;
}

export interface TrendDataPoint {
  date: string;
  score: number;
}

export interface CompareResponse {
  results: AssessmentResult[];
}
