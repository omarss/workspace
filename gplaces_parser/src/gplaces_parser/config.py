from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str

    # FastAPI service
    gplaces_api_key: str = ""  # required at runtime for `gplaces serve`
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_default_limit: int = 25
    api_max_limit: int = 50

    language: str = "ar"
    region: str = "sa"

    # Playwright scraper
    scraper_headless: bool = False
    scraper_slow_mo_ms: int = 0
    scraper_delay_seconds: float = 3.0
    scraper_page_timeout_ms: int = 30_000
    scraper_scroll_pause_ms: int = 2200
    scraper_max_scrolls: int = 80
    scraper_user_data_dir: str = str(Path.home() / ".cache" / "gplaces_parser" / "chromium")

    # Riyadh bounding box
    riyadh_lat_min: float = 24.50
    riyadh_lat_max: float = 25.05
    riyadh_lng_min: float = 46.45
    riyadh_lng_max: float = 47.10

    # Comma-separated category slug filter (empty = all). For smoke tests:
    #   CATEGORIES_FILTER=cafes
    categories_filter: str = ""

    tile_km: float = 3.0
    search_radius_km: float = 2.5
    results_per_query: int = 400
    reviews_per_place: int = 2000
    reviews_sort: str = "newest"
    # Playwright sync API is not thread-safe, so per-process concurrency is 1.
    # Run the CLI in multiple terminals to parallelize — SKIP LOCKED handles it.
    max_concurrent_jobs: int = 1


settings = Settings()  # type: ignore[call-arg]
