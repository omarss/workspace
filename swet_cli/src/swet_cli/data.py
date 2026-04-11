"""Static data: competency definitions, role emphasis, and technology taxonomy.

Loaded from the software engineering competency matrix JSON. The matrix defines
29 competencies, 12 roles, 5 levels, and 30 technology domains with specific
technologies per domain.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Competency:
    """A software engineering competency area."""

    slug: str
    name: str
    technology_domains: tuple[str, ...]
    # Level descriptions: level name -> description of what's expected
    levels: dict[str, str] = field(default_factory=dict)


# Load the competency matrix from the bundled JSON file
_MATRIX_PATH = Path(__file__).parent / "competency_matrix.json"
with open(_MATRIX_PATH) as _f:
    MATRIX = json.load(_f)

# --- Levels ---

LEVELS = MATRIX["dimensions"]["levels"]  # ["junior", "mid", "senior", "staff", "principal"]
LEVEL_DEFINITIONS = MATRIX["level_definitions"]

# Map difficulty 1-5 to level names
DIFFICULTY_TO_LEVEL: dict[int, str] = {
    1: "junior",
    2: "mid",
    3: "senior",
    4: "staff",
    5: "principal",
}
LEVEL_TO_DIFFICULTY: dict[str, int] = {v: k for k, v in DIFFICULTY_TO_LEVEL.items()}

# --- Competencies ---

COMPETENCIES: list[Competency] = []
for _slug, _data in MATRIX["competency_matrix"].items():
    COMPETENCIES.append(
        Competency(
            slug=_slug,
            name=_slug.replace("_", " ").title(),
            technology_domains=tuple(_data.get("technology_domains", [])),
            levels=_data.get("levels", {}),
        )
    )

# Lookup by slug for quick access
COMPETENCY_BY_SLUG: dict[str, Competency] = {c.slug: c for c in COMPETENCIES}
COMPETENCY_SLUGS: list[str] = [c.slug for c in COMPETENCIES]

# --- Roles ---

ROLES: list[str] = MATRIX["dimensions"]["roles"]

# Role emphasis matrix: role -> {emphasis_level -> [competency_slugs]}
ROLE_EMPHASIS: dict[str, dict[str, list[str]]] = MATRIX["role_emphasis_matrix"]

# Emphasis levels mapped to numeric weights for question selection
EMPHASIS_WEIGHTS: dict[str, float] = {
    "very_high": 0.30,
    "high": 0.20,
    "medium": 0.10,
    "low": 0.05,
}


def get_role_competency_weights(roles: list[str]) -> dict[str, float]:
    """Compute blended competency weights from multiple roles.

    For each role, maps emphasis levels (very_high, high, medium, low) to
    numeric weights, then averages across all selected roles. Competencies
    not mentioned in a role's emphasis matrix get a baseline weight.

    Returns:
        Dict of competency_slug -> weight (not normalized, raw blended weights).
    """
    baseline_weight = 0.02  # weight for competencies not mentioned in any role
    blended: dict[str, float] = {}

    if not roles:
        # No roles selected — all competencies get equal baseline weight
        return {comp.slug: baseline_weight for comp in COMPETENCIES}

    for role in roles:
        emphasis = ROLE_EMPHASIS.get(role, {})
        role_weights: dict[str, float] = {}

        for level_name, comp_slugs in emphasis.items():
            weight = EMPHASIS_WEIGHTS.get(level_name, 0.05)
            for slug in comp_slugs:
                role_weights[slug] = weight

        # Apply weights for this role, using baseline for unlisted competencies
        for comp in COMPETENCIES:
            w = role_weights.get(comp.slug, baseline_weight)
            blended[comp.slug] = blended.get(comp.slug, 0.0) + w

    # Average across roles
    return {slug: w / len(roles) for slug, w in blended.items()}


# --- Technology Taxonomy ---

TECHNOLOGY_TAXONOMY: dict[str, dict] = MATRIX["technology_taxonomy"]
TECHNOLOGY_DOMAIN_NAMES: list[str] = MATRIX["dimensions"]["technology_domains"]


def get_technologies_for_domains(domains: list[str]) -> list[str]:
    """Flatten technology taxonomy for given domains into a list of tech names."""
    techs: list[str] = []
    for domain in domains:
        domain_data = TECHNOLOGY_TAXONOMY.get(domain, {})
        if isinstance(domain_data, dict):
            for subcategory_techs in domain_data.values():
                if isinstance(subcategory_techs, list):
                    techs.extend(subcategory_techs)
    return techs


# --- Available Question Formats ---

QUESTION_FORMATS = ["mcq", "code_review", "debugging", "short_answer", "design_prompt"]

# --- Flattened language and framework lists for setup choices ---
# These are extracted from the technology taxonomy for the setup wizard

LANGUAGES: list[str] = []
for _cat_langs in TECHNOLOGY_TAXONOMY.get("languages", {}).values():
    if isinstance(_cat_langs, list):
        LANGUAGES.extend(_cat_langs)

FRAMEWORKS: list[str] = []
for _fw_category in ["backend_frameworks", "frontend_frameworks", "mobile_frameworks"]:
    for _cat_fws in TECHNOLOGY_TAXONOMY.get(_fw_category, {}).values():
        if isinstance(_cat_fws, list):
            FRAMEWORKS.extend(_cat_fws)

# ---------------------------------------------------------------------------
# Setup filtering: role → language subcategories, role → tool domains,
# language → per-item tool filtering
# ---------------------------------------------------------------------------

# Which language taxonomy subcategories each role should see.
# All roles see general_purpose. Some also see query/scripting/config languages.
_ROLE_LANGUAGE_SUBCATEGORIES: dict[str, list[str]] = {
    "backend_engineer": ["general_purpose", "data_query_and_modeling", "scripting_and_shell"],
    "frontend_engineer": ["general_purpose"],
    "mobile_engineer": ["general_purpose"],
    "full_stack_engineer": ["general_purpose", "data_query_and_modeling"],
    "data_engineer": ["general_purpose", "data_query_and_modeling", "scripting_and_shell"],
    "platform_engineer": ["general_purpose", "scripting_and_shell", "data_serialization_and_config"],
    "site_reliability_engineer": ["general_purpose", "scripting_and_shell", "data_serialization_and_config"],
    "security_engineer": ["general_purpose", "scripting_and_shell"],
    "data_scientist": ["general_purpose", "data_query_and_modeling"],
    "machine_learning_engineer": ["general_purpose"],
    "ai_engineer": ["general_purpose"],
    "qa_automation_engineer": ["general_purpose", "scripting_and_shell"],
}

# Which taxonomy domains each role should see in the framework/tools selection.
_ROLE_TOOL_DOMAINS: dict[str, list[str]] = {
    "backend_engineer": [
        "backend_frameworks",
        "databases",
        "orms_and_data_access",
        "messaging_and_streaming",
        "containers_and_orchestration",
    ],
    "frontend_engineer": ["frontend_frameworks"],
    "mobile_engineer": ["mobile_frameworks"],
    "full_stack_engineer": [
        "backend_frameworks",
        "frontend_frameworks",
        "databases",
        "orms_and_data_access",
    ],
    "data_engineer": ["databases", "data_platforms_and_processing", "messaging_and_streaming"],
    "platform_engineer": [
        "cloud_and_infrastructure",
        "containers_and_orchestration",
        "iac_and_configuration",
        "ci_cd_and_build",
    ],
    "site_reliability_engineer": [
        "cloud_and_infrastructure",
        "containers_and_orchestration",
        "observability_and_apm",
        "iac_and_configuration",
    ],
    "security_engineer": [
        "security_and_identity",
        "cloud_and_infrastructure",
        "containers_and_orchestration",
    ],
    "data_scientist": [
        "scientific_computing_and_notebooks",
        "classical_ml_libraries",
        "analytics_and_bi",
    ],
    "machine_learning_engineer": [
        "deep_learning_frameworks",
        "machine_learning_frameworks",
        "model_serving_and_inference",
        "mlops_and_orchestration",
    ],
    "ai_engineer": [
        "llm_and_genai_frameworks",
        "vector_databases_and_retrieval",
        "agent_and_workflow_frameworks",
        "ai_evaluation_and_guardrails",
    ],
    "qa_automation_engineer": [
        "testing_and_quality_tools",
        "frontend_frameworks",
        "ci_cd_and_build",
    ],
}

# Exhaustive mapping of every technology item to the language ecosystems it
# belongs to. Items not listed here are considered language-agnostic and are
# shown to all users regardless of language selection.
# Built by hand from the taxonomy to ensure correctness.
_TECH_TO_LANGUAGES: dict[str, set[str]] = {
    # --- backend_frameworks ---
    "Spring Boot": {"Java", "Kotlin"},
    "Spring MVC": {"Java", "Kotlin"},
    "Spring WebFlux": {"Java", "Kotlin"},
    "Quarkus": {"Java"},
    "Micronaut": {"Java", "Kotlin"},
    "Dropwizard": {"Java"},
    "Ktor": {"Kotlin"},
    "NestJS": {"TypeScript", "JavaScript"},
    "Express": {"TypeScript", "JavaScript"},
    "Fastify": {"TypeScript", "JavaScript"},
    "Hono": {"TypeScript", "JavaScript"},
    "Koa": {"TypeScript", "JavaScript"},
    "AdonisJS": {"TypeScript", "JavaScript"},
    "FastAPI": {"Python"},
    "Django": {"Python"},
    "Flask": {"Python"},
    "Starlette": {"Python"},
    "Gin": {"Go"},
    "Echo": {"Go"},
    "Fiber": {"Go"},
    "chi": {"Go"},
    "ASP.NET Core": {"C#", "F#"},
    "Ruby on Rails": {"Ruby"},
    "Laravel": {"PHP"},
    "Phoenix": {"Elixir"},
    # --- orms_and_data_access ---
    "JPA": {"Java", "Kotlin"},
    "Hibernate": {"Java", "Kotlin"},
    "Spring Data": {"Java", "Kotlin"},
    "jOOQ": {"Java", "Kotlin"},
    "MyBatis": {"Java"},
    "Exposed": {"Kotlin"},
    "Prisma": {"TypeScript", "JavaScript"},
    "TypeORM": {"TypeScript", "JavaScript"},
    "Drizzle ORM": {"TypeScript", "JavaScript"},
    "Sequelize": {"TypeScript", "JavaScript"},
    "Mongoose": {"TypeScript", "JavaScript"},
    "SQLAlchemy": {"Python"},
    "Django ORM": {"Python"},
    "Pydantic": {"Python"},
    "Entity Framework Core": {"C#", "F#"},
    "Dapper": {"C#", "F#"},
    "GORM": {"Go"},
    "sqlc": {"Go"},
    # --- runtime_and_sdk ---
    "JDK": {"Java", "Kotlin", "Scala", "Groovy"},
    "Spring Runtime": {"Java", "Kotlin"},
    "Quarkus Runtime": {"Java"},
    "Node.js": {"TypeScript", "JavaScript"},
    "Deno": {"TypeScript", "JavaScript"},
    "Bun": {"TypeScript", "JavaScript"},
    "CPython": {"Python"},
    "PyPy": {"Python"},
    ".NET": {"C#", "F#"},
    ".NET Aspire": {"C#", "F#"},
    "Android SDK": {"Kotlin", "Java"},
    "iOS SDK": {"Swift"},
    # --- testing (language-specific items only) ---
    "JUnit": {"Java", "Kotlin"},
    "Mockito": {"Java", "Kotlin"},
    "AssertJ": {"Java", "Kotlin"},
    "Jest": {"TypeScript", "JavaScript"},
    "Vitest": {"TypeScript", "JavaScript"},
    "Mocha": {"TypeScript", "JavaScript"},
    "Pytest": {"Python"},
    "unittest": {"Python"},
    "Go test": {"Go"},
    "xUnit": {"C#", "F#"},
    "JMH": {"Java", "Kotlin"},
    "BenchmarkDotNet": {"C#", "F#"},
    "ESLint": {"TypeScript", "JavaScript"},
    "Prettier": {"TypeScript", "JavaScript"},
    "Checkstyle": {"Java"},
    "SpotBugs": {"Java"},
    "Spotless": {"Java", "Kotlin"},
    "Ruff": {"Python"},
    "Pylint": {"Python"},
    "mypy": {"Python"},
    "golangci-lint": {"Go"},
    # language-agnostic testing tools: Testcontainers, WireMock, Playwright,
    # Cypress, Selenium, Appium, Detox, Pact, Postman, Newman, Karate,
    # k6, Gatling, Locust, JMeter, Semgrep, SonarQube, SonarCloud
    # --- ci_cd_and_build (language-specific build tools) ---
    "Maven": {"Java", "Kotlin", "Scala"},
    "Gradle": {"Java", "Kotlin", "Scala", "Groovy"},
    "npm": {"TypeScript", "JavaScript"},
    "pnpm": {"TypeScript", "JavaScript"},
    "yarn": {"TypeScript", "JavaScript"},
    "Poetry": {"Python"},
    "uv": {"Python"},
    "pip": {"Python"},
    "Cargo": {"Rust"},
    "Nx": {"TypeScript", "JavaScript"},
    "Turborepo": {"TypeScript", "JavaScript"},
    "Lerna": {"TypeScript", "JavaScript"},
    # language-agnostic: Bazel, Pants, GitHub Actions, GitLab CI, Jenkins, etc.
    # --- mobile_frameworks ---
    "Jetpack Compose": {"Kotlin"},
    "SwiftUI": {"Swift"},
    "UIKit": {"Swift"},
    "React Native": {"TypeScript", "JavaScript"},
    "Expo": {"TypeScript", "JavaScript"},
    "Flutter": {"Dart"},
    "Kotlin Multiplatform": {"Kotlin"},
    # --- frontend_frameworks (all JS/TS, shown via role not language) ---
    # --- scientific computing (all Python) ---
    "NumPy": {"Python"},
    "SciPy": {"Python"},
    "Pandas": {"Python"},
    "Polars": {"Python"},
    "Statsmodels": {"Python"},
    "Matplotlib": {"Python"},
    "Plotly": {"Python"},
    "Seaborn": {"Python"},
    "Altair": {"Python"},
    "Jupyter": {"Python"},
    "JupyterLab": {"Python"},
    "Streamlit": {"Python"},
    "Gradio": {"Python"},
    # --- ML/DL (all Python) ---
    "scikit-learn": {"Python"},
    "XGBoost": {"Python"},
    "LightGBM": {"Python"},
    "CatBoost": {"Python"},
    "statsmodels": {"Python"},
    "PyTorch": {"Python"},
    "TensorFlow": {"Python"},
    "Keras": {"Python"},
    "JAX": {"Python"},
    "PyTorch Lightning": {"Python"},
    "scikit-learn Pipelines": {"Python"},
    "Transformers": {"Python"},
    "Hugging Face Hub": {"Python"},
    "Diffusers": {"Python"},
    "sentence-transformers": {"Python"},
    "LangChain": {"Python", "TypeScript", "JavaScript"},
    "LlamaIndex": {"Python"},
    "DSPy": {"Python"},
    "Haystack": {"Python"},
    "Semantic Kernel": {"Python", "C#"},
    "LangGraph": {"Python"},
    "CrewAI": {"Python"},
    "AutoGen": {"Python"},
    "Ragas": {"Python"},
    "DeepEval": {"Python"},
    "PydanticAI": {"Python"},
    "Guardrails AI": {"Python"},
    "Langfuse": {"Python"},
}


def get_languages_for_roles(roles: list[str]) -> list[str]:
    """Get programming languages relevant to the selected roles.

    Filters the language taxonomy to only show subcategories relevant to
    the user's roles (e.g., backend sees SQL/Bash, frontend does not).
    """
    lang_taxonomy = TECHNOLOGY_TAXONOMY.get("languages", {})
    subcategories: set[str] = set()
    for role in roles:
        subcategories.update(_ROLE_LANGUAGE_SUBCATEGORIES.get(role, ["general_purpose"]))

    langs: list[str] = []
    for subcat in subcategories:
        items = lang_taxonomy.get(subcat, [])
        if isinstance(items, list):
            langs.extend(items)
    return langs


def get_frameworks_for_roles(
    roles: list[str],
    languages: list[str] | None = None,
) -> list[str]:
    """Get frameworks/tools relevant to the selected roles and languages.

    Three-layer filtering:
    1. Role filter: only show taxonomy domains relevant to the user's roles.
    2. Language filter: for items that have a language association in
       _TECH_TO_LANGUAGES, only include them if the user selected that language.
       Items NOT in _TECH_TO_LANGUAGES are language-agnostic and always shown.
    3. Deduplication: return unique items preserving insertion order.

    This means a backend_engineer who selects Python will see FastAPI, Django,
    SQLAlchemy, Pytest but NOT Spring Boot, Express, or JUnit. They will still
    see language-agnostic tools like PostgreSQL, Kafka, Docker, Kubernetes.
    """
    # Step 1: collect relevant taxonomy domains from all selected roles
    domains: set[str] = set()
    for role in roles:
        domains.update(_ROLE_TOOL_DOMAINS.get(role, []))

    # Step 2: flatten all items from those domains
    all_items: list[str] = get_technologies_for_domains(list(domains))

    # Step 3: filter by language if languages were selected
    if not languages:
        return all_items

    selected_langs = set(languages)
    filtered: list[str] = []
    for item in all_items:
        item_langs = _TECH_TO_LANGUAGES.get(item)
        if item_langs is None:
            # Language-agnostic item — always include
            filtered.append(item)
        elif item_langs & selected_langs:
            # Language-specific item that matches the user's selection
            filtered.append(item)
        # else: language-specific item that doesn't match — skip

    return filtered
