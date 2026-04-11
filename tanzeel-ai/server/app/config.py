import sys

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/tanzeel"

    # JWT
    jwt_secret_key: str = "change-me-in-production-use-a-real-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    # RunPod
    runpod_api_key: str = ""
    runpod_endpoint_id: str = ""

    # App
    max_audio_duration_seconds: int = 30
    max_audio_size_bytes: int = 10_000_000  # 10MB
    guest_daily_limit: int = 10

    # CORS - comma-separated origins, e.g. "http://localhost:8081,https://tanzeel.app"
    allowed_origins: str = "http://localhost:8081,http://localhost:19006"

    model_config = {"env_file": ".env", "extra": "ignore"}

    def validate_startup(self) -> list[str]:
        """Return list of warnings for missing/insecure config."""
        warnings: list[str] = []
        if self.jwt_secret_key == "change-me-in-production-use-a-real-secret":
            warnings.append("JWT_SECRET_KEY is using the default value. Set a real secret in .env")
        if not self.runpod_api_key:
            warnings.append("RUNPOD_API_KEY is empty. ASR calls will fail")
        if not self.runpod_endpoint_id:
            warnings.append("RUNPOD_ENDPOINT_ID is empty. ASR calls will fail")
        return warnings


settings = Settings()

# Print startup warnings (non-fatal so dev server can still run)
for warning in settings.validate_startup():
    print(f"⚠ CONFIG WARNING: {warning}", file=sys.stderr)
