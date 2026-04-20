from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str

    # Corpus
    docs_bundle_root: str = "/home/omar/workspace/vrtx-ai/docs-bundle"

    # Generation — shells out to the `claude` CLI (Claude Code login)
    claude_cli: str = "claude"
    claude_model: str = "sonnet"

    # FastAPI
    mcqs_api_key: str = ""  # required at runtime for `mcqs serve`
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_default_limit: int = 25
    api_max_limit: int = 100

    # Generation tuning
    mcqs_batch_size: int = 10
    mcqs_per_type_target: int = 100
    mcqs_chunk_tokens: int = 1000
    mcqs_chunk_overlap: int = 150


settings = Settings()  # type: ignore[call-arg]
