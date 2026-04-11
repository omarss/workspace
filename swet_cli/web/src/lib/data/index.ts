/**
 * Static data and filtering logic, mirroring swet_cli/data.py.
 * Loaded from the extracted competency matrix JSON at build time.
 */

import matrix from './matrix.json';

// --- Core data ---

export const ROLES: string[] = matrix.roles;
export const LEVELS: string[] = matrix.levels;
export const QUESTION_FORMATS: string[] = matrix.question_formats;
export const COMPETENCIES = matrix.competencies as Record<
	string,
	{ name: string; technology_domains: string[] }
>;
export const COMPETENCY_SLUGS = Object.keys(COMPETENCIES);
export const ROLE_EMPHASIS = matrix.role_emphasis as Record<
	string,
	Record<string, string[]>
>;
export const TECHNOLOGY_TAXONOMY = matrix.technology_taxonomy as Record<
	string,
	Record<string, string[]>
>;

// --- Display helpers ---

export const ROLE_DISPLAY_NAMES: Record<string, string> = {
	backend_engineer: 'Backend Engineer',
	frontend_engineer: 'Frontend Engineer',
	mobile_engineer: 'Mobile Engineer',
	data_engineer: 'Data Engineer',
	platform_engineer: 'Platform Engineer',
	security_engineer: 'Security Engineer',
	data_scientist: 'Data Scientist',
	machine_learning_engineer: 'ML Engineer',
	ai_engineer: 'AI Engineer',
	full_stack_engineer: 'Full Stack Engineer',
	qa_automation_engineer: 'QA Automation',
	site_reliability_engineer: 'SRE'
};

export const ROLE_ICONS: Record<string, string> = {
	backend_engineer: 'server',
	frontend_engineer: 'layout',
	mobile_engineer: 'smartphone',
	data_engineer: 'database',
	platform_engineer: 'cloud',
	security_engineer: 'shield',
	data_scientist: 'bar-chart',
	machine_learning_engineer: 'cpu',
	ai_engineer: 'brain',
	full_stack_engineer: 'layers',
	qa_automation_engineer: 'check-circle',
	site_reliability_engineer: 'activity'
};

export const FORMAT_DISPLAY_NAMES: Record<string, string> = {
	mcq: 'Multiple Choice',
	code_review: 'Code Review',
	debugging: 'Debugging',
	short_answer: 'Short Answer',
	design_prompt: 'System Design'
};

export const FORMAT_DESCRIPTIONS: Record<string, string> = {
	mcq: 'Quick knowledge checks with 4 options',
	code_review: 'Analyze code snippets for issues and improvements',
	debugging: 'Find and fix bugs in code',
	short_answer: 'Explain concepts in your own words',
	design_prompt: 'Design systems and architectures'
};

export const DIFFICULTY_LABELS: Record<number, string> = {
	1: 'Junior',
	2: 'Mid',
	3: 'Senior',
	4: 'Staff',
	5: 'Principal'
};

export const DIFFICULTY_COLORS: Record<number, string> = {
	1: 'text-l1',
	2: 'text-l2',
	3: 'text-l3',
	4: 'text-l4',
	5: 'text-l5'
};

export const DIFFICULTY_BG_COLORS: Record<number, string> = {
	1: 'bg-l1/15 text-l1',
	2: 'bg-l2/15 text-l2',
	3: 'bg-l3/15 text-l3',
	4: 'bg-l4/15 text-l4',
	5: 'bg-l5/15 text-l5'
};

// --- Filtering logic (mirrors data.py) ---

const ROLE_LANGUAGE_SUBCATEGORIES: Record<string, string[]> = {
	backend_engineer: ['general_purpose', 'data_query_and_modeling', 'scripting_and_shell'],
	frontend_engineer: ['general_purpose'],
	mobile_engineer: ['general_purpose'],
	full_stack_engineer: ['general_purpose', 'data_query_and_modeling'],
	data_engineer: ['general_purpose', 'data_query_and_modeling', 'scripting_and_shell'],
	platform_engineer: [
		'general_purpose',
		'scripting_and_shell',
		'data_serialization_and_config'
	],
	site_reliability_engineer: [
		'general_purpose',
		'scripting_and_shell',
		'data_serialization_and_config'
	],
	security_engineer: ['general_purpose', 'scripting_and_shell'],
	data_scientist: ['general_purpose', 'data_query_and_modeling'],
	machine_learning_engineer: ['general_purpose'],
	ai_engineer: ['general_purpose'],
	qa_automation_engineer: ['general_purpose', 'scripting_and_shell']
};

const ROLE_TOOL_DOMAINS: Record<string, string[]> = {
	backend_engineer: [
		'backend_frameworks',
		'databases',
		'orms_and_data_access',
		'messaging_and_streaming',
		'containers_and_orchestration'
	],
	frontend_engineer: ['frontend_frameworks'],
	mobile_engineer: ['mobile_frameworks'],
	full_stack_engineer: [
		'backend_frameworks',
		'frontend_frameworks',
		'databases',
		'orms_and_data_access'
	],
	data_engineer: ['databases', 'data_platforms_and_processing', 'messaging_and_streaming'],
	platform_engineer: [
		'cloud_and_infrastructure',
		'containers_and_orchestration',
		'iac_and_configuration',
		'ci_cd_and_build'
	],
	site_reliability_engineer: [
		'cloud_and_infrastructure',
		'containers_and_orchestration',
		'observability_and_apm',
		'iac_and_configuration'
	],
	security_engineer: [
		'security_and_identity',
		'cloud_and_infrastructure',
		'containers_and_orchestration'
	],
	data_scientist: [
		'scientific_computing_and_notebooks',
		'classical_ml_libraries',
		'analytics_and_bi'
	],
	machine_learning_engineer: [
		'deep_learning_frameworks',
		'machine_learning_frameworks',
		'model_serving_and_inference',
		'mlops_and_orchestration'
	],
	ai_engineer: [
		'llm_and_genai_frameworks',
		'vector_databases_and_retrieval',
		'agent_and_workflow_frameworks',
		'ai_evaluation_and_guardrails'
	],
	qa_automation_engineer: ['testing_and_quality_tools', 'frontend_frameworks', 'ci_cd_and_build']
};

// Language-specific tech items (items not here are language-agnostic)
const TECH_TO_LANGUAGES: Record<string, Set<string>> = {
	'Spring Boot': new Set(['Java', 'Kotlin']),
	'Spring MVC': new Set(['Java', 'Kotlin']),
	'Spring WebFlux': new Set(['Java', 'Kotlin']),
	Quarkus: new Set(['Java']),
	Micronaut: new Set(['Java', 'Kotlin']),
	Dropwizard: new Set(['Java']),
	Ktor: new Set(['Kotlin']),
	NestJS: new Set(['TypeScript', 'JavaScript']),
	Express: new Set(['TypeScript', 'JavaScript']),
	Fastify: new Set(['TypeScript', 'JavaScript']),
	Hono: new Set(['TypeScript', 'JavaScript']),
	Koa: new Set(['TypeScript', 'JavaScript']),
	AdonisJS: new Set(['TypeScript', 'JavaScript']),
	FastAPI: new Set(['Python']),
	Django: new Set(['Python']),
	Flask: new Set(['Python']),
	Starlette: new Set(['Python']),
	Gin: new Set(['Go']),
	Echo: new Set(['Go']),
	Fiber: new Set(['Go']),
	chi: new Set(['Go']),
	'ASP.NET Core': new Set(['C#', 'F#']),
	'Ruby on Rails': new Set(['Ruby']),
	Laravel: new Set(['PHP']),
	Phoenix: new Set(['Elixir']),
	JPA: new Set(['Java', 'Kotlin']),
	Hibernate: new Set(['Java', 'Kotlin']),
	'Spring Data': new Set(['Java', 'Kotlin']),
	jOOQ: new Set(['Java', 'Kotlin']),
	MyBatis: new Set(['Java']),
	Exposed: new Set(['Kotlin']),
	Prisma: new Set(['TypeScript', 'JavaScript']),
	TypeORM: new Set(['TypeScript', 'JavaScript']),
	'Drizzle ORM': new Set(['TypeScript', 'JavaScript']),
	Sequelize: new Set(['TypeScript', 'JavaScript']),
	Mongoose: new Set(['TypeScript', 'JavaScript']),
	SQLAlchemy: new Set(['Python']),
	'Django ORM': new Set(['Python']),
	Pydantic: new Set(['Python']),
	'Entity Framework Core': new Set(['C#', 'F#']),
	Dapper: new Set(['C#', 'F#']),
	GORM: new Set(['Go']),
	sqlc: new Set(['Go']),
	'Jetpack Compose': new Set(['Kotlin']),
	SwiftUI: new Set(['Swift']),
	UIKit: new Set(['Swift']),
	'React Native': new Set(['TypeScript', 'JavaScript']),
	Expo: new Set(['TypeScript', 'JavaScript']),
	Flutter: new Set(['Dart']),
	'Kotlin Multiplatform': new Set(['Kotlin']),
	NumPy: new Set(['Python']),
	SciPy: new Set(['Python']),
	Pandas: new Set(['Python']),
	Polars: new Set(['Python']),
	Matplotlib: new Set(['Python']),
	Plotly: new Set(['Python']),
	Seaborn: new Set(['Python']),
	Jupyter: new Set(['Python']),
	JupyterLab: new Set(['Python']),
	Streamlit: new Set(['Python']),
	Gradio: new Set(['Python']),
	'scikit-learn': new Set(['Python']),
	XGBoost: new Set(['Python']),
	LightGBM: new Set(['Python']),
	CatBoost: new Set(['Python']),
	PyTorch: new Set(['Python']),
	TensorFlow: new Set(['Python']),
	Keras: new Set(['Python']),
	JAX: new Set(['Python']),
	'PyTorch Lightning': new Set(['Python']),
	Transformers: new Set(['Python']),
	LangChain: new Set(['Python', 'TypeScript', 'JavaScript']),
	LlamaIndex: new Set(['Python']),
	DSPy: new Set(['Python']),
	LangGraph: new Set(['Python']),
	CrewAI: new Set(['Python']),
	AutoGen: new Set(['Python']),
	Maven: new Set(['Java', 'Kotlin', 'Scala']),
	Gradle: new Set(['Java', 'Kotlin', 'Scala', 'Groovy']),
	npm: new Set(['TypeScript', 'JavaScript']),
	pnpm: new Set(['TypeScript', 'JavaScript']),
	yarn: new Set(['TypeScript', 'JavaScript']),
	Poetry: new Set(['Python']),
	uv: new Set(['Python']),
	pip: new Set(['Python']),
	Cargo: new Set(['Rust']),
	JUnit: new Set(['Java', 'Kotlin']),
	Mockito: new Set(['Java', 'Kotlin']),
	Jest: new Set(['TypeScript', 'JavaScript']),
	Vitest: new Set(['TypeScript', 'JavaScript']),
	Pytest: new Set(['Python']),
	'Go test': new Set(['Go']),
	xUnit: new Set(['C#', 'F#']),
	ESLint: new Set(['TypeScript', 'JavaScript']),
	Ruff: new Set(['Python']),
	mypy: new Set(['Python']),
	'golangci-lint': new Set(['Go'])
};

/** Get languages relevant to the selected roles */
export function getLanguagesForRoles(roles: string[]): string[] {
	const langTaxonomy = TECHNOLOGY_TAXONOMY['languages'] ?? {};
	const subcategories = new Set<string>();

	for (const role of roles) {
		for (const sub of ROLE_LANGUAGE_SUBCATEGORIES[role] ?? ['general_purpose']) {
			subcategories.add(sub);
		}
	}

	const langs: string[] = [];
	for (const sub of subcategories) {
		const items = langTaxonomy[sub];
		if (Array.isArray(items)) {
			langs.push(...items);
		}
	}
	return [...new Set(langs)];
}

/** Get frameworks/tools relevant to the selected roles and languages */
export function getFrameworksForRoles(roles: string[], languages?: string[]): string[] {
	const domains = new Set<string>();
	for (const role of roles) {
		for (const domain of ROLE_TOOL_DOMAINS[role] ?? []) {
			domains.add(domain);
		}
	}

	// Flatten items from those domains
	const allItems: string[] = [];
	for (const domain of domains) {
		const domainData = TECHNOLOGY_TAXONOMY[domain];
		if (domainData && typeof domainData === 'object') {
			for (const subcatItems of Object.values(domainData)) {
				if (Array.isArray(subcatItems)) {
					allItems.push(...subcatItems);
				}
			}
		}
	}

	if (!languages || languages.length === 0) return [...new Set(allItems)];

	const selectedLangs = new Set(languages);
	const filtered: string[] = [];
	const seen = new Set<string>();

	for (const item of allItems) {
		if (seen.has(item)) continue;
		seen.add(item);

		const itemLangs = TECH_TO_LANGUAGES[item];
		if (!itemLangs) {
			// Language-agnostic — always include
			filtered.push(item);
		} else {
			// Check if any of the item's languages match
			for (const lang of itemLangs) {
				if (selectedLangs.has(lang)) {
					filtered.push(item);
					break;
				}
			}
		}
	}
	return filtered;
}

/** Select competencies for assessment based on role emphasis */
export function selectAssessmentCompetencies(roles: string[]): string[] {
	const veryHigh: string[] = [];
	const high: string[] = [];

	for (const role of roles) {
		const emphasis = ROLE_EMPHASIS[role] ?? {};
		veryHigh.push(...(emphasis['very_high'] ?? []));
		high.push(...(emphasis['high'] ?? []));
	}

	const seen = new Set<string>();
	const ordered: string[] = [];
	for (const slug of [...veryHigh, ...high]) {
		if (!seen.has(slug) && slug in COMPETENCIES) {
			seen.add(slug);
			ordered.push(slug);
		}
	}

	return ordered.slice(0, 6);
}

/** Slugified name to display name */
export function slugToName(slug: string): string {
	return COMPETENCIES[slug]?.name ?? slug.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
