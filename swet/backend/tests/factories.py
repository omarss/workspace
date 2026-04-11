"""Factory Boy factories for generating test data."""

import uuid
from datetime import UTC, datetime

import factory


class UserFactory(factory.Factory):
    """Factory for creating User test instances."""

    class Meta:
        model = dict

    id = factory.LazyFunction(uuid.uuid4)
    github_id = factory.Sequence(lambda n: 10000000 + n)
    github_username = factory.Sequence(lambda n: f"testuser{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.github_username}@example.com")
    avatar_url = factory.LazyAttribute(
        lambda obj: f"https://avatars.githubusercontent.com/u/{obj.github_id}"
    )
    is_active = True
    onboarding_completed = False
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))


class ProfileFactory(factory.Factory):
    """Factory for creating UserProfile test instances."""

    class Meta:
        model = dict

    id = factory.LazyFunction(uuid.uuid4)
    user_id = factory.LazyFunction(uuid.uuid4)
    primary_role = "backend"
    interests = factory.LazyFunction(lambda: ["web_development", "cloud_infrastructure"])
    technologies = factory.LazyFunction(
        lambda: {"languages": ["python", "typescript"], "frameworks": ["fastapi", "nextjs"]}
    )
    experience_years = 5
    config_hash = factory.LazyFunction(lambda: "a" * 64)


class AssessmentFactory(factory.Factory):
    """Factory for creating Assessment test instances."""

    class Meta:
        model = dict

    id = factory.LazyFunction(uuid.uuid4)
    user_id = factory.LazyFunction(uuid.uuid4)
    config_hash = factory.LazyFunction(lambda: "b" * 64)
    status = "in_progress"
    total_questions = 100
    current_question_index = 0
    is_timed = False
    time_limit_minutes = None
    started_at = factory.LazyFunction(lambda: datetime.now(UTC))
    completed_at = None
