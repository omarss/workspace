"""Multi-office locations per cluster.

A `jobs` row carries one primary location (city_id + region_code +
office_address). When the same role recruits into several offices, the
extra offices live here. Filters that need to match a job to *any* of
its offices should UNION across `jobs.city_id` and `job_locations.city_id`.
"""

from __future__ import annotations

from uuid import UUID

from ..models import JobLocation
from .base import Repo


class JobLocationsRepo(Repo):
    async def add(
        self,
        job_id: UUID,
        *,
        city_id: UUID | None = None,
        region_code: str | None = None,
        country_code: str = "sa",
        office_address: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        is_primary: bool = False,
        notes: str | None = None,
    ) -> JobLocation:
        """Add a location to a cluster.

        If `is_primary=True`, demotes any previous primary first (the schema
        unique-partial index would otherwise raise). Wrapped in a transaction
        so the swap is atomic.
        """
        async with self._pool.connection() as conn, conn.transaction():
            async with conn.cursor() as cur:
                if is_primary:
                    await cur.execute(
                        "UPDATE job_locations SET is_primary = false "
                        "WHERE job_id = %(j)s AND is_primary",
                        {"j": job_id},
                    )
            from psycopg.rows import dict_row

            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                        INSERT INTO job_locations
                          (job_id, city_id, region_code, country_code,
                           office_address, latitude, longitude, is_primary, notes)
                        VALUES (%(j)s, %(city)s, %(region)s, %(country)s,
                                %(addr)s, %(lat)s, %(lon)s, %(prim)s, %(notes)s)
                        RETURNING *;
                        """,
                    {
                        "j": job_id,
                        "city": city_id,
                        "region": region_code,
                        "country": country_code,
                        "addr": office_address,
                        "lat": latitude,
                        "lon": longitude,
                        "prim": is_primary,
                        "notes": notes,
                    },
                )
                row = await cur.fetchone()
        assert row is not None
        return JobLocation.model_validate(row)

    async def list_for_job(self, job_id: UUID) -> list[JobLocation]:
        rows = await self._fetchall(
            """
            SELECT * FROM job_locations
            WHERE job_id = %(j)s
            ORDER BY is_primary DESC, created_at;
            """,
            {"j": job_id},
        )
        return self._to_models(JobLocation, rows)

    async def remove(self, location_id: UUID) -> None:
        await self._execute(
            "DELETE FROM job_locations WHERE id = %(id)s",
            {"id": location_id},
        )
