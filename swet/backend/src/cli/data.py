"""Static data for competencies and role weights.

Extracted from seed.py to avoid importing database dependencies.
Used by both the seed command and the CLI practice mode.
"""

# The 12 engineering competency groups
COMPETENCIES: list[dict[str, str | int]] = [
    {
        "id": 1,
        "slug": "problem_solving",
        "name": "Problem Solving",
        "description": (
            "Ability to break down complex problems, identify root causes, "
            "and design effective solutions"
        ),
        "category": "transferable",
    },
    {
        "id": 2,
        "slug": "code_quality",
        "name": "Code Quality",
        "description": (
            "Writing clean, maintainable, readable code following established "
            "patterns and conventions"
        ),
        "category": "transferable",
    },
    {
        "id": 3,
        "slug": "system_design",
        "name": "System Design",
        "description": (
            "Designing scalable, resilient architectures and making sound technical trade-offs"
        ),
        "category": "transferable",
    },
    {
        "id": 4,
        "slug": "testing",
        "name": "Testing & QA",
        "description": (
            "Writing effective tests, understanding test strategies, "
            "and ensuring software reliability"
        ),
        "category": "transferable",
    },
    {
        "id": 5,
        "slug": "debugging",
        "name": "Debugging",
        "description": (
            "Systematic approach to identifying, isolating, and fixing defects in software"
        ),
        "category": "transferable",
    },
    {
        "id": 6,
        "slug": "security",
        "name": "Security",
        "description": (
            "Understanding security principles, common vulnerabilities, and secure coding practices"
        ),
        "category": "transferable",
    },
    {
        "id": 7,
        "slug": "performance",
        "name": "Performance",
        "description": (
            "Optimizing code and systems for speed, efficiency, and resource utilization"
        ),
        "category": "transferable",
    },
    {
        "id": 8,
        "slug": "api_design",
        "name": "API Design",
        "description": ("Designing clear, consistent, and well-documented APIs and interfaces"),
        "category": "transferable",
    },
    {
        "id": 9,
        "slug": "data_modeling",
        "name": "Data Modeling",
        "description": (
            "Designing effective database schemas, data structures, and data flow patterns"
        ),
        "category": "context",
    },
    {
        "id": 10,
        "slug": "devops",
        "name": "DevOps & Infrastructure",
        "description": ("CI/CD, containerization, cloud infrastructure, and deployment practices"),
        "category": "context",
    },
    {
        "id": 11,
        "slug": "concurrency",
        "name": "Concurrency & Async",
        "description": ("Managing concurrent operations, async patterns, and parallel processing"),
        "category": "context",
    },
    {
        "id": 12,
        "slug": "architecture_patterns",
        "name": "Architecture Patterns",
        "description": (
            "Knowledge of design patterns, architectural styles, and when to apply them"
        ),
        "category": "context",
    },
]

# Role-specific competency weights
# Each entry: (competency_id, weight, question_count)
# question_count must sum to 100 per role
ROLE_WEIGHTS: dict[str, list[tuple[int, float, int]]] = {
    "backend": [
        (1, 0.12, 12),
        (2, 0.10, 10),
        (3, 0.12, 12),
        (4, 0.08, 8),
        (5, 0.08, 8),
        (6, 0.10, 10),
        (7, 0.10, 10),
        (8, 0.10, 10),
        (9, 0.08, 8),
        (10, 0.04, 4),
        (11, 0.04, 4),
        (12, 0.04, 4),
    ],
    "frontend": [
        (1, 0.10, 10),
        (2, 0.12, 12),
        (3, 0.08, 8),
        (4, 0.10, 10),
        (5, 0.10, 10),
        (6, 0.08, 8),
        (7, 0.10, 10),
        (8, 0.08, 8),
        (9, 0.04, 4),
        (10, 0.04, 4),
        (11, 0.08, 8),
        (12, 0.08, 8),
    ],
    "fullstack": [
        (1, 0.10, 10),
        (2, 0.10, 10),
        (3, 0.10, 10),
        (4, 0.08, 8),
        (5, 0.08, 8),
        (6, 0.08, 8),
        (7, 0.08, 8),
        (8, 0.10, 10),
        (9, 0.08, 8),
        (10, 0.06, 6),
        (11, 0.06, 6),
        (12, 0.08, 8),
    ],
    "devops": [
        (1, 0.08, 8),
        (2, 0.06, 6),
        (3, 0.12, 12),
        (4, 0.08, 8),
        (5, 0.10, 10),
        (6, 0.12, 12),
        (7, 0.10, 10),
        (8, 0.06, 6),
        (9, 0.04, 4),
        (10, 0.14, 14),
        (11, 0.04, 4),
        (12, 0.06, 6),
    ],
    "data": [
        (1, 0.12, 12),
        (2, 0.08, 8),
        (3, 0.08, 8),
        (4, 0.08, 8),
        (5, 0.06, 6),
        (6, 0.06, 6),
        (7, 0.12, 12),
        (8, 0.06, 6),
        (9, 0.14, 14),
        (10, 0.06, 6),
        (11, 0.06, 6),
        (12, 0.08, 8),
    ],
    "mobile": [
        (1, 0.10, 10),
        (2, 0.12, 12),
        (3, 0.08, 8),
        (4, 0.10, 10),
        (5, 0.10, 10),
        (6, 0.08, 8),
        (7, 0.12, 12),
        (8, 0.08, 8),
        (9, 0.04, 4),
        (10, 0.04, 4),
        (11, 0.08, 8),
        (12, 0.06, 6),
    ],
    "ml": [
        (1, 0.14, 14),
        (2, 0.06, 6),
        (3, 0.08, 8),
        (4, 0.08, 8),
        (5, 0.08, 8),
        (6, 0.04, 4),
        (7, 0.12, 12),
        (8, 0.06, 6),
        (9, 0.12, 12),
        (10, 0.06, 6),
        (11, 0.08, 8),
        (12, 0.08, 8),
    ],
    "security": [
        (1, 0.10, 10),
        (2, 0.08, 8),
        (3, 0.10, 10),
        (4, 0.08, 8),
        (5, 0.10, 10),
        (6, 0.18, 18),
        (7, 0.06, 6),
        (8, 0.06, 6),
        (9, 0.04, 4),
        (10, 0.08, 8),
        (11, 0.06, 6),
        (12, 0.06, 6),
    ],
    "qa": [
        (1, 0.10, 10),
        (2, 0.10, 10),
        (3, 0.06, 6),
        (4, 0.18, 18),
        (5, 0.14, 14),
        (6, 0.08, 8),
        (7, 0.08, 8),
        (8, 0.08, 8),
        (9, 0.04, 4),
        (10, 0.06, 6),
        (11, 0.04, 4),
        (12, 0.04, 4),
    ],
    "gamedev": [
        (1, 0.10, 10),
        (2, 0.10, 10),
        (3, 0.08, 8),
        (4, 0.08, 8),
        (5, 0.08, 8),
        (6, 0.04, 4),
        (7, 0.14, 14),
        (8, 0.06, 6),
        (9, 0.06, 6),
        (10, 0.04, 4),
        (11, 0.12, 12),
        (12, 0.10, 10),
    ],
}

# Available options for profile setup (mirrors onboarding.service.get_onboarding_options)
ONBOARDING_OPTIONS: dict[str, list[str]] = {
    "roles": [
        "backend",
        "frontend",
        "fullstack",
        "mobile",
        "devops",
        "data",
        "ml",
        "security",
        "qa",
        "gamedev",
    ],
    "interests": [
        "web_development",
        "mobile_development",
        "cloud_infrastructure",
        "data_engineering",
        "machine_learning",
        "security",
        "distributed_systems",
        "embedded_systems",
        "game_development",
        "developer_tools",
    ],
    "languages": [
        "python",
        "javascript",
        "typescript",
        "java",
        "csharp",
        "go",
        "rust",
        "cpp",
        "ruby",
        "swift",
        "kotlin",
        "php",
        "scala",
        "elixir",
    ],
    "frameworks": [
        "react",
        "nextjs",
        "vue",
        "angular",
        "svelte",
        "django",
        "fastapi",
        "flask",
        "spring",
        "express",
        "nestjs",
        "rails",
        "dotnet",
        "phoenix",
        "gin",
        "actix",
    ],
}
