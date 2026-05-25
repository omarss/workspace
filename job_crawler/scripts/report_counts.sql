-- Counts per source × normalized job title.
-- Run via:  PGPASSWORD=$JC_DB_PASSWORD psql -U job_crawler -h 127.0.0.1 -d job_crawler -f scripts/report_counts.sql
--
-- Position grouping uses `normalize_text()` (folds Arabic letterforms,
-- strips diacritics, lowercases + unaccents Latin) so trivial variants
-- — whitespace, punctuation, HTML-entity leftovers, casing,
-- "Sr." vs "Senior" suffixes once aliased — collapse into one row.
-- `MIN(p.title)` is shown as a representative display value; the
-- normalized key drives the grouping but is hidden from output.

\echo '== Per-source total ==\n'
SELECT s.slug                                        AS source,
       COUNT(p.id)                                   AS postings,
       COUNT(DISTINCT p.company_id)                  AS companies,
       COUNT(p.id) FILTER (WHERE p.saudi_nationals_only) AS saudi_only,
       COUNT(p.id) FILTER (WHERE p.gender_preference <> 'any') AS gendered,
       MIN(p.first_seen_at)::date                    AS first_seen,
       MAX(p.last_seen_at)::date                     AS last_seen
FROM   sources s
LEFT   JOIN job_postings p ON p.source_id = s.id
GROUP  BY s.slug
ORDER  BY postings DESC NULLS LAST;

\echo '\n== Top 30 positions (titles) — across all sources ==\n'
SELECT MIN(p.title)                                  AS position,
       COUNT(*)                                      AS postings,
       string_agg(DISTINCT s.slug, ', ' ORDER BY s.slug) AS sources
FROM   job_postings p
JOIN   sources s ON s.id = p.source_id
GROUP  BY normalize_text(p.title)
HAVING COUNT(*) >= 2
ORDER  BY postings DESC, position
LIMIT  30;

\echo '\n== Per-source × normalized-position matrix (top 20 per source) ==\n'
WITH ranked AS (
    SELECT s.slug                       AS source,
           MIN(p.title)                  AS position,
           COUNT(*)                     AS postings,
           ROW_NUMBER() OVER (PARTITION BY s.slug
                              ORDER BY COUNT(*) DESC, MIN(p.title)) AS rn
    FROM   job_postings p
    JOIN   sources s ON s.id = p.source_id
    GROUP  BY s.slug, normalize_text(p.title)
)
SELECT source, postings, position
FROM   ranked
WHERE  rn <= 20
ORDER  BY source, postings DESC, position;
