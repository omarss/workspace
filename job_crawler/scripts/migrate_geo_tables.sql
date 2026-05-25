-- One-time migration: rename `sa_regions`/`sa_cities` → `regions`/`cities`
-- with composite (country_code, region_code) keys.
--
-- Pre-conditions:
--   * Run `bash scripts/db_clear.sh crawl --confirm` first so job_postings /
--     jobs / job_locations have no rows referencing the old city ids.
--   * No company should reference `headquarters_city_id`; the schema as
--     of the time this migration was written had zero such rows in
--     production (verified before the rename).
--
-- Safe to run twice: every CREATE / DROP is guarded by IF [NOT] EXISTS.
-- Wraps in a single transaction so a partial failure rolls back cleanly.
BEGIN;

-- Drop FKs that point at the old tables so we can drop them.
ALTER TABLE IF EXISTS companies
    DROP CONSTRAINT IF EXISTS companies_headquarters_city_id_fkey;
ALTER TABLE IF EXISTS jobs
    DROP CONSTRAINT IF EXISTS jobs_city_id_fkey,
    DROP CONSTRAINT IF EXISTS jobs_region_code_fkey;
ALTER TABLE IF EXISTS job_postings
    DROP CONSTRAINT IF EXISTS job_postings_city_id_fkey;
ALTER TABLE IF EXISTS job_locations
    DROP CONSTRAINT IF EXISTS job_locations_city_id_fkey,
    DROP CONSTRAINT IF EXISTS job_locations_region_code_fkey;

-- Drop legacy tables. CASCADE handles indexes + comments.
DROP TABLE IF EXISTS sa_cities  CASCADE;
DROP TABLE IF EXISTS sa_regions CASCADE;

-- New tables. Identical to the definitions in db_schema.sql so re-applying
-- the schema later is a no-op.
CREATE TABLE IF NOT EXISTS regions (
    country_code char(2)    NOT NULL REFERENCES countries(code),
    code         text       NOT NULL,
    name_en      text       NOT NULL,
    name_ar      text       NOT NULL,
    PRIMARY KEY (country_code, code)
);

CREATE TABLE IF NOT EXISTS cities (
    id           uuid       PRIMARY KEY DEFAULT uuidv7(),
    country_code char(2)    NOT NULL,
    region_code  text       NOT NULL,
    name_en      text       NOT NULL,
    name_ar      text       NOT NULL,
    latitude     numeric(9,6),
    longitude    numeric(9,6),
    FOREIGN KEY (country_code, region_code) REFERENCES regions(country_code, code),
    UNIQUE (country_code, region_code, name_en),
    UNIQUE (country_code, region_code, name_ar)
);
CREATE INDEX IF NOT EXISTS cities_name_en_trgm
    ON cities USING gin (normalize_en(name_en) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS cities_name_ar_trgm
    ON cities USING gin (normalize_ar(name_ar) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS cities_country_region
    ON cities (country_code, region_code);

-- Re-add FKs on the dependent tables. Composite FKs use MATCH SIMPLE so a
-- NULL region_code skips the FK check (matches the schema in db_schema.sql).
ALTER TABLE companies
    ADD CONSTRAINT companies_headquarters_city_id_fkey
        FOREIGN KEY (headquarters_city_id) REFERENCES cities(id);

ALTER TABLE jobs
    ADD CONSTRAINT jobs_city_id_fkey
        FOREIGN KEY (city_id) REFERENCES cities(id),
    ADD CONSTRAINT jobs_country_code_region_code_fkey
        FOREIGN KEY (country_code, region_code) REFERENCES regions(country_code, code);

-- job_postings did not previously carry region_code/country_code; add both.
ALTER TABLE job_postings
    ADD COLUMN IF NOT EXISTS region_code  text,
    ADD COLUMN IF NOT EXISTS country_code char(2) NOT NULL DEFAULT 'sa'
        REFERENCES countries(code);
ALTER TABLE job_postings
    ADD CONSTRAINT job_postings_city_id_fkey
        FOREIGN KEY (city_id) REFERENCES cities(id),
    ADD CONSTRAINT job_postings_country_code_region_code_fkey
        FOREIGN KEY (country_code, region_code) REFERENCES regions(country_code, code);

ALTER TABLE job_locations
    ADD CONSTRAINT job_locations_city_id_fkey
        FOREIGN KEY (city_id) REFERENCES cities(id),
    ADD CONSTRAINT job_locations_country_code_region_code_fkey
        FOREIGN KEY (country_code, region_code) REFERENCES regions(country_code, code);

COMMIT;
