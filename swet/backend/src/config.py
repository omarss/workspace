from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_env: str = "development"
    app_name: str = "SWET API"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://swet:swet_local@localhost:5432/swet"

    # Auth - NextAuth.js secret for JWT validation
    nextauth_secret: str = "change-me-in-production"

    # CORS
    cors_origins: str = "http://localhost:3000"

    # AI
    anthropic_api_key: str = ""
    # Set to use an OpenAI-compatible proxy (e.g. http://127.0.0.1:3456/v1)
    llm_base_url: str = ""
    llm_api_key: str = "not-needed"
    # Model IDs (override to use different models)
    llm_generation_model: str = "claude-sonnet-4-6"
    llm_grading_model: str = "claude-sonnet-4-6"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
