"""The `JobCrawlerDB` facade — single entry point for the library.

Design
------
* One instance owns one `AsyncConnectionPool`.
* Each domain repo is exposed as an attribute (`.companies`, `.postings`,
  `.search`, ...). Repos are lazily constructed on first access so creating
  the facade is cheap.
* The facade is an async context manager:

      async with JobCrawlerDB.from_env() as db:
          source = await db.sources.upsert(...)
          posting = await db.postings.upsert(...)
          hits = await db.search.find_jobs("senior python", required_skill_ids=[...])

  Closing the context drains and closes the pool.

* For one-off scripts / tests, `db.open()` / `db.close()` are also exposed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from psycopg_pool import AsyncConnectionPool

from .pool import build_pool
from .settings import Settings

if TYPE_CHECKING:
    from .repos.companies import CompaniesRepo
    from .repos.crawl import CrawlRepo
    from .repos.crawler_health import CrawlerHealthRepo
    from .repos.dedupe import DedupeRepo
    from .repos.fake_signals import FakeSignalsRepo
    from .repos.geo import GeoRepo
    from .repos.job_locations import JobLocationsRepo
    from .repos.jobs import JobsRepo
    from .repos.postings import PostingsRepo
    from .repos.recruiters import RecruitersRepo
    from .repos.reference import ReferenceRepo
    from .repos.search import SearchRepo
    from .repos.skills import SkillsRepo
    from .repos.sources import SourcesRepo
    from .repos.synonyms import SynonymsRepo


class JobCrawlerDB:
    """Async facade over the job_crawler PostgreSQL schema.

    Construct with `from_env()` for the standard env-driven config, or
    `__init__(settings)` to inject a custom `Settings`.

    The facade is reentrant-safe but not threadsafe — share one instance
    per event loop, not across loops.
    """

    __slots__ = (
        "_companies",
        "_crawl",
        "_crawler_health",
        "_dedupe",
        "_fake_signals",
        "_geo",
        "_job_locations",
        "_jobs",
        "_owns_pool",
        "_pool",
        "_postings",
        "_recruiters",
        "_reference",
        "_search",
        "_settings",
        "_skills",
        "_sources",
        "_synonyms",
    )

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        pool: AsyncConnectionPool | None = None,
    ) -> None:
        """Build the facade.

        Pass `pool` to share an externally-managed pool (rare; useful
        for embedding the lib in an existing app that already owns the pool).
        """
        if settings is None and pool is None:
            raise ValueError("Either `settings` or `pool` must be provided.")
        self._settings = settings
        if pool is None:
            assert settings is not None
            self._pool = build_pool(settings)
            self._owns_pool = True
        else:
            self._pool = pool
            self._owns_pool = False

        # Repos materialised lazily — see __getattr__ below.
        self._sources = None
        self._companies = None
        self._recruiters = None
        self._skills = None
        self._synonyms = None
        self._jobs = None
        self._job_locations = None
        self._postings = None
        self._dedupe = None
        self._fake_signals = None
        self._crawl = None
        self._crawler_health = None
        self._geo = None
        self._reference = None
        self._search = None

    # -- alternative constructor ----------------------------------------

    @classmethod
    def from_env(cls, *, prefix: str = "JCDB_") -> Self:
        """Build from the JCDB_* environment variables."""
        return cls(Settings.from_env(prefix=prefix))

    # -- lifecycle -------------------------------------------------------

    async def open(self) -> None:
        """Open the underlying pool (no-op if the pool is already owned externally)."""
        if self._owns_pool:
            await self._pool.open()
            await self._pool.wait()  # raise if any connection fails early

    async def close(self) -> None:
        if self._owns_pool:
            await self._pool.close()

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    @property
    def pool(self) -> AsyncConnectionPool:
        """Escape hatch for power users who want raw access to the pool."""
        return self._pool

    # -- repos -----------------------------------------------------------

    @property
    def sources(self) -> SourcesRepo:
        if self._sources is None:
            from .repos.sources import SourcesRepo

            self._sources = SourcesRepo(self._pool)
        return self._sources

    @property
    def companies(self) -> CompaniesRepo:
        if self._companies is None:
            from .repos.companies import CompaniesRepo

            self._companies = CompaniesRepo(self._pool)
        return self._companies

    @property
    def recruiters(self) -> RecruitersRepo:
        if self._recruiters is None:
            from .repos.recruiters import RecruitersRepo

            self._recruiters = RecruitersRepo(self._pool)
        return self._recruiters

    @property
    def skills(self) -> SkillsRepo:
        if self._skills is None:
            from .repos.skills import SkillsRepo

            self._skills = SkillsRepo(self._pool)
        return self._skills

    @property
    def synonyms(self) -> SynonymsRepo:
        if self._synonyms is None:
            from .repos.synonyms import SynonymsRepo

            self._synonyms = SynonymsRepo(self._pool)
        return self._synonyms

    @property
    def jobs(self) -> JobsRepo:
        if self._jobs is None:
            from .repos.jobs import JobsRepo

            self._jobs = JobsRepo(self._pool)
        return self._jobs

    @property
    def job_locations(self) -> JobLocationsRepo:
        if self._job_locations is None:
            from .repos.job_locations import JobLocationsRepo

            self._job_locations = JobLocationsRepo(self._pool)
        return self._job_locations

    @property
    def postings(self) -> PostingsRepo:
        if self._postings is None:
            from .repos.postings import PostingsRepo

            self._postings = PostingsRepo(self._pool)
        return self._postings

    @property
    def dedupe(self) -> DedupeRepo:
        if self._dedupe is None:
            from .repos.dedupe import DedupeRepo

            self._dedupe = DedupeRepo(self._pool)
        return self._dedupe

    @property
    def fake_signals(self) -> FakeSignalsRepo:
        if self._fake_signals is None:
            from .repos.fake_signals import FakeSignalsRepo

            self._fake_signals = FakeSignalsRepo(self._pool)
        return self._fake_signals

    @property
    def crawl(self) -> CrawlRepo:
        if self._crawl is None:
            from .repos.crawl import CrawlRepo

            self._crawl = CrawlRepo(self._pool)
        return self._crawl

    @property
    def crawler_health(self) -> CrawlerHealthRepo:
        if self._crawler_health is None:
            from .repos.crawler_health import CrawlerHealthRepo

            self._crawler_health = CrawlerHealthRepo(self._pool)
        return self._crawler_health

    @property
    def geo(self) -> GeoRepo:
        if self._geo is None:
            from .repos.geo import GeoRepo

            self._geo = GeoRepo(self._pool)
        return self._geo

    @property
    def reference(self) -> ReferenceRepo:
        if self._reference is None:
            from .repos.reference import ReferenceRepo

            self._reference = ReferenceRepo(self._pool)
        return self._reference

    @property
    def search(self) -> SearchRepo:
        if self._search is None:
            from .repos.search import SearchRepo

            # SearchRepo depends on the synonym expander — wire it lazily so we
            # don't materialise SynonymsRepo unless someone actually searches.
            self._search = SearchRepo(
                self._pool,
                synonym_expander=self.synonyms.expand,
            )
        return self._search
