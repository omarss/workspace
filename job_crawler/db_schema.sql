-- ============================================================================
-- job_crawler — database schema
-- ============================================================================
-- Target: PostgreSQL 18+
--
-- Design summary
-- --------------
-- The schema follows a **cluster dedupe model**:
--
--   sources ──< job_postings >── jobs (cluster) ──< job_skills >── skills
--                  │                  │
--                  │                  └──< job_fake_signals (heuristic evidence)
--                  │
--                  ├──< posting_snapshots   (per-fetch diff history)
--                  └──< posting_duplicate_edges (pairwise similarity evidence)
--
--   * Every crawled URL becomes one immutable `job_postings` row.
--   * A `jobs` row is a *cluster* — the canonical "real job" that one or many
--     postings represent. A posting may belong to no cluster (yet) or to
--     exactly one cluster. A cluster is what the API serves to users.
--   * Companies are de-duplicated independently via `company_aliases` +
--     `company_source_profiles` so the same employer crawled from LinkedIn,
--     Bayt, and Greenhouse resolves to one canonical row.
--   * Skills follow the same curated-taxonomy + aliases pattern, optionally
--     anchored to ESCO/O*NET ids for interop.
--
-- Conventions
-- -----------
--   * Primary keys are UUIDv7 (`uuidv7()` — PG 18 native) so they are
--     time-ordered, B-tree friendly, and safe to expose externally.
--   * All timestamps are `timestamptz`, stored in UTC.
--   * Bilingual text uses paired `*_ar` / `*_en` columns. Either may be NULL,
--     but at least one must be non-null where a CHECK enforces it.
--   * Soft deletes via `deleted_at timestamptz` only where audit history
--     matters; reference data is hard-deleted.
--   * Lookup tables use stable short string PKs (e.g. `'sa'`, `'riyadh'`)
--     instead of surrogate ids — they appear in URLs and code paths.
--   * JSONB `raw_payload` columns preserve the original source response so
--     re-extraction is possible without re-crawling.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Extensions
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;       -- digest() for content hashing
CREATE EXTENSION IF NOT EXISTS pg_trgm;        -- trigram similarity for misspelling-tolerant search
CREATE EXTENSION IF NOT EXISTS unaccent;       -- fold Latin diacritics (café -> cafe)
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;  -- levenshtein, metaphone, soundex for phonetic match
CREATE EXTENSION IF NOT EXISTS btree_gin;      -- composite GIN indexes
CREATE EXTENSION IF NOT EXISTS btree_gist;     -- exclusion constraints with btree types


-- ----------------------------------------------------------------------------
-- Enums
-- ----------------------------------------------------------------------------
-- Sources are typed so dedupe can weight ATS pages (canonical) above
-- aggregators (noisy) without per-source branching in app code.
CREATE TYPE source_kind AS ENUM (
    'aggregator',     -- LinkedIn, Indeed
    'regional_board', -- Bayt, Naukrigulf
    'local_board',    -- Tanqeeb, Mihnati, Wuzzuf
    'gov_board',      -- Jadarat (HRDF)
    'ats',            -- Greenhouse / Lever / Workday hosted careers pages
    'company_site'    -- bespoke careers pages
);

CREATE TYPE employment_type AS ENUM (
    'full_time',
    'part_time',
    'contract',
    'temporary',
    'internship',
    'freelance',
    'volunteer'
);

CREATE TYPE work_arrangement AS ENUM (
    'onsite',
    'hybrid',
    'remote'
);

CREATE TYPE experience_level AS ENUM (
    'entry',
    'junior',
    'mid',
    'senior',
    'lead',
    'manager',
    'director',
    'executive'
);

CREATE TYPE salary_period AS ENUM (
    'hourly',
    'daily',
    'weekly',
    'monthly',
    'annual',
    'project'
);

-- Lifecycle of an individual crawled posting (NOT the cluster).
CREATE TYPE posting_status AS ENUM (
    'active',     -- last fetch returned a live posting
    'expired',    -- source marked it closed/filled
    'removed',    -- 404 or otherwise vanished
    'error'       -- repeated fetch failures, status unknown
);

-- Cluster verdict — derived from fake-signal heuristics.
CREATE TYPE cluster_verdict AS ENUM (
    'pending',     -- not yet scored
    'legit',       -- score above legit threshold
    'suspicious',  -- in the grey band, surfaced with a warning
    'fake',        -- below threshold, hidden from default queries
    'recycled'     -- legit content but re-posted job that already exists
);

CREATE TYPE skill_kind AS ENUM (
    'hard',        -- technical / measurable
    'soft',        -- behavioural
    'language',    -- spoken/written language proficiency
    'certification', -- formal credential (PMP, AWS SAA, ...)
    'tool'         -- specific tool/software, subset of hard
);

CREATE TYPE skill_requirement AS ENUM (
    'required',
    'preferred',
    'nice_to_have'
);

CREATE TYPE duplicate_reason AS ENUM (
    'exact_url',           -- normalised URL identical
    'exact_content_hash',  -- description body byte-identical
    'near_content',        -- trigram similarity above threshold
    'title_company_loc',   -- same title + same company + same city
    'cross_source_repost', -- ATS canonical + aggregator mirror
    'manual'               -- human-set link
);

CREATE TYPE fake_signal_kind AS ENUM (
    'salary_outlier_high',
    'salary_outlier_low',
    'no_company_match',
    'newly_registered_company',
    'generic_description',
    'requests_payment',
    'requests_personal_docs_early',
    'broken_apply_link',
    'duplicate_across_unrelated_companies',
    'mismatched_location_visa',
    'mass_posted_template',     -- same body across 50+ companies
    'reposted_within_30d',
    'contact_via_personal_channel', -- whatsapp/personal email only
    'ai_generated_description'  -- description shows heavy LLM-generation tells
);

CREATE TYPE crawl_run_status AS ENUM (
    'queued',
    'running',
    'completed',
    'failed',
    'cancelled'
);

-- Whether a posting is restricted to a specific gender. Common in the
-- Saudi market (esp. retail, hospitality, education) where the role
-- description explicitly says "female candidates only" / "للنساء فقط".
-- 'any' = no restriction (the overwhelming default).
CREATE TYPE gender_preference AS ENUM (
    'any',
    'male_only',
    'female_only'
);

CREATE TYPE application_channel_kind AS ENUM (
    'url',         -- external apply URL (most common)
    'email',
    'whatsapp',
    'phone',
    'in_app',      -- in-source apply (LinkedIn Easy Apply, Bayt apply, ...)
    'fax'
);

-- Generic proficiency ladder. Maps cleanly to CEFR for languages
-- (basic≈A, intermediate≈B, advanced≈C1, expert≈C2) and to common
-- skill-rubric labels for hard skills / tools.
CREATE TYPE skill_proficiency AS ENUM (
    'basic',
    'intermediate',
    'advanced',
    'expert',
    'native'       -- meaningful for languages; ignored for hard skills
);

-- Coarse education requirement. Stored on the cluster; raw text kept on
-- the posting in `raw_payload` for forensics.
CREATE TYPE education_level AS ENUM (
    'none',
    'high_school',
    'diploma',
    'bachelor',
    'master',
    'phd'
);

-- Categorises a synonym group so query expansion can be scoped — e.g. only
-- expand `skill` synonyms when matching against the skill axis, not free text.
CREATE TYPE synonym_kind AS ENUM (
    'skill',       -- "k8s" <-> "kubernetes", "JS" <-> "JavaScript"
    'job_title',   -- "SWE" <-> "Software Engineer", "PM" <-> "Project Manager"
    'company',     -- "Aramco" <-> "Saudi Aramco" <-> "أرامكو"
    'location',    -- "Jeddah" <-> "Jiddah" <-> "جدة"
    'industry',    -- "IT" <-> "Information Technology" <-> "تقنية المعلومات"
    'general'      -- catch-all for free-text expansion
);

-- Direction of a synonym pair within a group. Most groups are pure synonyms
-- (bidirectional). Abbreviation/translation are tagged because the UI sometimes
-- displays the canonical form rather than the variant the user typed.
CREATE TYPE synonym_relation AS ENUM (
    'synonym',      -- fully interchangeable
    'abbreviation', -- short form of canonical
    'translation',  -- cross-language equivalent
    'broader',      -- term is broader than canonical ("Cloud" vs "AWS")
    'narrower'      -- term is narrower than canonical ("EKS" vs "Kubernetes")
);


-- ----------------------------------------------------------------------------
-- Helpers: bilingual text normalization + search configuration
-- ----------------------------------------------------------------------------
-- Search strategy
-- ---------------
-- Recall comes from three layers, combined at query time:
--
--   1) Token-level full-text search (tsvector @@ tsquery)
--        • English uses a custom `english_unaccent` config that unaccents
--          before stemming, so "café" matches "cafe" matches "cafes".
--        • Arabic uses the `simple` parser fed normalized text (see
--          normalize_ar below), since Postgres ships no Arabic stemmer.
--   2) Character-level trigram similarity (`%` / `word_similarity`)
--        • Tolerates misspellings, missing letters, transposition.
--        • Powered by `pg_trgm` GIN indexes on the *normalized* form so
--          the trigram matcher sees the same string regardless of casing,
--          diacritics, or Arabic letterform variants.
--   3) Synonym expansion via the `synonym_groups` / `synonym_terms` tables
--        • Maps abbreviations ("k8s" -> "kubernetes"), cross-language
--          equivalents ("Software Engineer" <-> "مهندس برمجيات"),
--          and broader/narrower concepts to a single concept group.
--        • Expansion happens in the *app layer* against the synonym tables
--          before tsquery / trigram matching, keeping the DB engine
--          dictionary-free and the synonyms versioned in the DB.
--
-- The app combines them, typically as:
--   1. expand :q via synonym_terms join on normalize_text(term)
--   2. build a tsquery OR of all expanded forms
--   3. retrieve candidates via WHERE search_en @@ q
--                            OR normalize_en(title_en) % normalize_en(:any_form)
--   4. rank with ts_rank_cd + word_similarity + synonym_terms.weight + source.trust_weight
--
-- For phonetic / extreme typo matching, `fuzzystrmatch.levenshtein` and
-- `metaphone` are available but not indexed by default (use as a final
-- re-ranking stage on top-N trigram candidates).

-- unaccent() is STABLE because the dictionary is loadable; wrap it as
-- IMMUTABLE so we can use it in generated columns and expression indexes.
CREATE OR REPLACE FUNCTION f_unaccent(input text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT public.unaccent('public.unaccent'::regdictionary, coalesce(input, ''))
$$;
COMMENT ON FUNCTION f_unaccent(text) IS
    'IMMUTABLE wrapper around unaccent() so it is usable in indexes and generated columns.';

-- English normalization: case-fold + strip Latin diacritics + collapse
-- internal whitespace. Cheap and reversible-ish.
-- Internal calls are schema-qualified because SQL-function inlining can
-- happen with a restricted search_path (e.g. inside expression indexes).
CREATE OR REPLACE FUNCTION normalize_en(input text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT regexp_replace(lower(public.f_unaccent(input)), '\s+', ' ', 'g')
$$;
COMMENT ON FUNCTION normalize_en(text) IS
    'Lowercase + unaccent + whitespace-collapse. Use on both indexed text and query input.';

-- Arabic normalization: fold letterform variants and strip tashkeel/tatweel
-- so "محمد", "مُحَمَّد", and "محـمد" all collide.
--
-- Mappings applied:
--   • strip U+064B..U+0652 (tashkeel: fatha, damma, kasra, shadda, sukun, ...)
--   • strip U+0640         (tatweel — visual letter-stretcher)
--   • strip U+0670         (superscript alef)
--   • إ أ آ → ا            (alef family → bare alef)
--   • ى → ي                (alef maksura → ya)
--   • ة → ه                (ta marbuta → ha — common search convention)
--   • Hindi-Arabic digits → ASCII digits (٠-٩ → 0-9)
CREATE OR REPLACE FUNCTION normalize_ar(input text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT translate(
        regexp_replace(
            coalesce(input, ''),
            '[ً-ْـٰ]', '', 'g'
        ),
        'إأآىة٠١٢٣٤٥٦٧٨٩',
        'ااايه0123456789'
    );
$$;
COMMENT ON FUNCTION normalize_ar(text) IS
    'Folds Arabic letterform variants, strips diacritics, maps Hindi-Arabic digits to ASCII.';

-- Bilingual normalizer for fields that mix scripts (aliases, raw company
-- names, posting titles like "Senior Engineer | مهندس أول"). Applies both
-- normalizations; they operate on disjoint character sets so the order
-- is irrelevant and the cost is small.
CREATE OR REPLACE FUNCTION normalize_text(input text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT public.normalize_en(public.normalize_ar(input))
$$;
COMMENT ON FUNCTION normalize_text(text) IS
    'Bilingual normalizer combining normalize_ar + normalize_en. Use for mixed-script columns and query input.';

-- English text-search configuration that unaccents *before* stemming, so
-- "café" and "cafe" both stem to 'cafe'. Required because the stock
-- `english` config keeps diacritics until after stemming.
CREATE TEXT SEARCH CONFIGURATION english_unaccent ( COPY = english );
ALTER TEXT SEARCH CONFIGURATION english_unaccent
    ALTER MAPPING FOR hword, hword_part, word
    WITH unaccent, english_stem;
COMMENT ON TEXT SEARCH CONFIGURATION english_unaccent IS
    'English search config that unaccents tokens before stemming. Used by all search_en generated columns.';


-- ----------------------------------------------------------------------------
-- Reference data: geography (Saudi Arabia-focused, extensible)
-- ----------------------------------------------------------------------------
-- ISO-3166-1 country codes; seeded with SA but ready for GCC expansion.
CREATE TABLE countries (
    code        char(2)     PRIMARY KEY,            -- ISO-3166-1 alpha-2, lowercase
    name_en     text        NOT NULL,
    name_ar     text        NOT NULL,
    dial_code   text        NOT NULL,
    currency    char(3)     NOT NULL                -- ISO-4217
);
COMMENT ON TABLE countries IS
    'ISO-3166-1 countries. Lowercase alpha-2 PKs so they appear cleanly in URLs.';

-- Administrative regions / first-level subdivisions, keyed per country.
-- Saudi Arabia's 13 mintaqah live here under country_code='sa'; UAE
-- emirates under 'ae'; etc. Stable text codes (e.g. 'riyadh', 'dubai')
-- appear in URLs + filters, so they are part of the composite PK along
-- with the country.
CREATE TABLE regions (
    country_code char(2)    NOT NULL REFERENCES countries(code),
    code         text       NOT NULL,
    name_en      text       NOT NULL,
    name_ar      text       NOT NULL,
    PRIMARY KEY (country_code, code)
);
COMMENT ON TABLE regions IS
    'First-level administrative subdivisions per country (mintaqah / emirate / governorate).';

-- Cities live under (country_code, region_code). The composite FK keeps
-- a Dubai city under the UAE Dubai emirate and a Riyadh city under the
-- Saudi Riyadh region — there is no way to accidentally attach a UAE
-- city to a Saudi region.
CREATE TABLE cities (
    id           uuid       PRIMARY KEY DEFAULT uuidv7(),
    country_code char(2)    NOT NULL,
    region_code  text       NOT NULL,
    name_en      text       NOT NULL,
    name_ar      text       NOT NULL,
    -- ISO 6709 lat/lon, optional, for distance queries
    latitude     numeric(9,6),
    longitude    numeric(9,6),
    FOREIGN KEY (country_code, region_code) REFERENCES regions(country_code, code),
    UNIQUE (country_code, region_code, name_en),
    UNIQUE (country_code, region_code, name_ar)
);
CREATE INDEX cities_name_en_trgm   ON cities USING gin (normalize_en(name_en) gin_trgm_ops);
CREATE INDEX cities_name_ar_trgm   ON cities USING gin (normalize_ar(name_ar) gin_trgm_ops);
CREATE INDEX cities_country_region ON cities (country_code, region_code);
COMMENT ON TABLE cities IS
    'Cities scoped by (country_code, region_code). Trigram indexes enable fuzzy matching of crawled location strings.';


-- ----------------------------------------------------------------------------
-- Reference data: occupational + industry taxonomies
-- ----------------------------------------------------------------------------
-- Industries — kept flat. ISIC rev. 4 codes optional for interop.
CREATE TABLE industries (
    code        text        PRIMARY KEY,            -- e.g. 'tech_software'
    name_en     text        NOT NULL,
    name_ar     text        NOT NULL,
    isic_code   text                                -- ISIC rev. 4, optional
);
COMMENT ON TABLE industries IS
    'Industry vertical of the hiring company. ISIC code is optional and informational.';

-- Job categories ("Software Engineering", "Sales", ...).
-- Self-referential parent_code so a 2-3 level tree is possible without an
-- extra closure table; depth is small enough that recursive CTEs are fine.
CREATE TABLE job_categories (
    code         text       PRIMARY KEY,
    parent_code  text       REFERENCES job_categories(code) ON DELETE RESTRICT,
    name_en      text       NOT NULL,
    name_ar      text       NOT NULL,
    -- ESCO occupation URI or O*NET-SOC code, optional
    esco_uri     text,
    onet_code    text,
    CHECK (parent_code IS DISTINCT FROM code)
);
COMMENT ON TABLE job_categories IS
    'Tree of job categories. parent_code = NULL for top-level. Optional ESCO/O*NET anchors enable cross-system mapping.';


-- ----------------------------------------------------------------------------
-- Sources — the websites being crawled
-- ----------------------------------------------------------------------------
CREATE TABLE sources (
    id              uuid          PRIMARY KEY DEFAULT uuidv7(),
    slug            text          NOT NULL UNIQUE,   -- 'linkedin', 'bayt', 'greenhouse'
    display_name    text          NOT NULL,
    kind            source_kind   NOT NULL,
    base_url        text          NOT NULL,
    -- Trust weight in [0,1]; ATS / company sites near 1.0, aggregators lower.
    -- Used as a tiebreaker when picking the canonical posting of a cluster
    -- and when computing the cluster's fake/legit score.
    trust_weight    numeric(3,2)  NOT NULL DEFAULT 0.50
                                  CHECK (trust_weight BETWEEN 0 AND 1),
    crawl_enabled   boolean       NOT NULL DEFAULT true,
    -- robots.txt / ToS notes, scraper module name, rate-limit hints, etc.
    config          jsonb         NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz   NOT NULL DEFAULT now(),
    updated_at      timestamptz   NOT NULL DEFAULT now()
);
COMMENT ON TABLE sources IS
    'One row per crawlable website. trust_weight feeds the dedupe + fake-score pipeline.';
COMMENT ON COLUMN sources.config IS
    'Free-form JSON: scraper module name, rate limit, custom headers, login state location, etc.';


-- ----------------------------------------------------------------------------
-- Companies
-- ----------------------------------------------------------------------------
-- Canonical companies. A company can be referenced under many names across
-- sources ("ARAMCO", "Saudi Aramco", "أرامكو السعودية") — those go in
-- `company_aliases` and resolve back here.
CREATE TABLE companies (
    id                  uuid          PRIMARY KEY DEFAULT uuidv7(),
    name_en             text          NOT NULL,
    name_ar             text,
    legal_name_en       text,
    legal_name_ar       text,
    -- Saudi-specific: 10-digit Commercial Registration. Optional but unique
    -- when present — strongest possible dedupe key for SA companies.
    cr_number           text          UNIQUE,
    website             text,
    linkedin_url        text          UNIQUE,
    logo_url            text,
    industry_code       text          REFERENCES industries(code),
    headquarters_city_id uuid         REFERENCES cities(id),
    country_code        char(2)       NOT NULL DEFAULT 'sa' REFERENCES countries(code),
    -- Approximate employee count; ranges from source pages are normalized to midpoint.
    employee_count      integer       CHECK (employee_count IS NULL OR employee_count >= 0),
    founded_year        smallint      CHECK (founded_year IS NULL
                                             OR founded_year BETWEEN 1800 AND extract(year from now())::int),
    -- True when a human has confirmed this is the official entity (not a
    -- recruiter, ghost company, or aggregator-fabricated stub).
    is_verified         boolean       NOT NULL DEFAULT false,
    verified_at         timestamptz,
    verified_by         text,         -- operator email/id, kept simple
    notes               text,
    created_at          timestamptz   NOT NULL DEFAULT now(),
    updated_at          timestamptz   NOT NULL DEFAULT now(),
    deleted_at          timestamptz,
    CHECK (name_en IS NOT NULL OR name_ar IS NOT NULL),
    CHECK ((is_verified = false) OR (verified_at IS NOT NULL))
);
CREATE INDEX companies_name_en_trgm ON companies USING gin (normalize_en(name_en) gin_trgm_ops);
CREATE INDEX companies_name_ar_trgm ON companies USING gin (normalize_ar(name_ar) gin_trgm_ops);
CREATE INDEX companies_legal_en_trgm ON companies USING gin (normalize_en(legal_name_en) gin_trgm_ops)
    WHERE legal_name_en IS NOT NULL;
CREATE INDEX companies_legal_ar_trgm ON companies USING gin (normalize_ar(legal_name_ar) gin_trgm_ops)
    WHERE legal_name_ar IS NOT NULL;
CREATE INDEX companies_industry      ON companies (industry_code) WHERE deleted_at IS NULL;
CREATE INDEX companies_active        ON companies (id) WHERE deleted_at IS NULL;
COMMENT ON TABLE companies IS
    'Canonical employer entity. cr_number is the gold dedupe key for SA companies.';

-- Every variant spelling / translation a crawler has seen for a company.
-- Looked up via trigram similarity before deciding to create a new company row.
CREATE TABLE company_aliases (
    id           uuid       PRIMARY KEY DEFAULT uuidv7(),
    company_id   uuid       NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    alias        text       NOT NULL,
    locale       text,                                -- 'en', 'ar', null = either
    source_id    uuid       REFERENCES sources(id),   -- where this alias was first seen
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, alias)
);
CREATE INDEX company_aliases_alias_trgm ON company_aliases USING gin (normalize_text(alias) gin_trgm_ops);
COMMENT ON TABLE company_aliases IS
    'Alternate names / spellings / translations per company. Drives fuzzy company resolution.';

-- The same company often has a profile URL on every source (LinkedIn company
-- page, Bayt employer page, Greenhouse subdomain). Capturing those URLs once
-- avoids re-discovering the mapping on every crawl.
CREATE TABLE company_source_profiles (
    id                       uuid        PRIMARY KEY DEFAULT uuidv7(),
    company_id               uuid        NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source_id                uuid        NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    source_company_external_id text,                  -- e.g. LinkedIn numeric id
    profile_url              text        NOT NULL,
    last_seen_at             timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, profile_url),
    UNIQUE (source_id, source_company_external_id)
);
COMMENT ON TABLE company_source_profiles IS
    'Per-source profile pages for one company. Lets the crawler map a posting''s employer to the canonical company in O(1).';


-- ----------------------------------------------------------------------------
-- Recruiters — individual people who post jobs
-- ----------------------------------------------------------------------------
-- Many postings (especially on LinkedIn and Bayt) are uploaded by individual
-- recruiters rather than the employer's HR account. Modelling recruiters
-- enables:
--   * de-anonymising "Confidential Company" listings by clustering on poster
--   * detecting recruiter-spam patterns (one recruiter, 200 stale postings)
--   * separating in-house TA from agency recruiters
CREATE TABLE recruiters (
    id                  uuid          PRIMARY KEY DEFAULT uuidv7(),
    full_name           text,
    headline            text,                                -- "Talent Acquisition at X"
    linkedin_url        text          UNIQUE,
    email               text,
    phone               text,
    -- The recruiting agency the person works for (themselves a company row).
    -- NULL when the recruiter is in-house or the agency is unknown.
    agency_company_id   uuid          REFERENCES companies(id) ON DELETE SET NULL,
    is_verified         boolean       NOT NULL DEFAULT false,
    verified_at         timestamptz,
    verified_by         text,
    notes               text,
    created_at          timestamptz   NOT NULL DEFAULT now(),
    updated_at          timestamptz   NOT NULL DEFAULT now(),
    CHECK (full_name IS NOT NULL OR linkedin_url IS NOT NULL OR email IS NOT NULL),
    CHECK ((is_verified = false) OR (verified_at IS NOT NULL))
);
CREATE INDEX recruiters_agency        ON recruiters (agency_company_id) WHERE agency_company_id IS NOT NULL;
CREATE INDEX recruiters_name_trgm     ON recruiters USING gin (normalize_en(full_name) gin_trgm_ops)
    WHERE full_name IS NOT NULL;
COMMENT ON TABLE recruiters IS
    'Individual job posters (often recruiters). Joined to job_postings via posted_by_recruiter_id.';


-- ----------------------------------------------------------------------------
-- Skills
-- ----------------------------------------------------------------------------
CREATE TABLE skills (
    id            uuid         PRIMARY KEY DEFAULT uuidv7(),
    slug          text         NOT NULL UNIQUE,       -- 'python', 'project-management'
    name_en       text         NOT NULL,
    name_ar       text,
    kind          skill_kind   NOT NULL,
    description   text,
    -- ESCO skill URI / O*NET element id for interop with external taxonomies.
    esco_uri      text         UNIQUE,
    onet_code     text,
    -- Optional parent so "AWS Lambda" can be linked under "AWS".
    parent_id     uuid         REFERENCES skills(id) ON DELETE RESTRICT,
    is_active     boolean      NOT NULL DEFAULT true,
    created_at    timestamptz  NOT NULL DEFAULT now(),
    updated_at    timestamptz  NOT NULL DEFAULT now(),
    CHECK (parent_id IS DISTINCT FROM id)
);
CREATE INDEX skills_kind         ON skills (kind) WHERE is_active;
CREATE INDEX skills_parent       ON skills (parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX skills_name_en_trgm ON skills USING gin (normalize_en(name_en) gin_trgm_ops);
CREATE INDEX skills_name_ar_trgm ON skills USING gin (normalize_ar(name_ar) gin_trgm_ops)
    WHERE name_ar IS NOT NULL;
COMMENT ON TABLE skills IS
    'Canonical skill taxonomy. parent_id makes a shallow tree (skill -> sub-skill). ESCO/O*NET ids optional for interop.';

-- Aliases let crawlers map free-text mentions ("py3", "Py", "بايثون") to the
-- canonical skill row without polluting `skills` itself.
CREATE TABLE skill_aliases (
    id          uuid         PRIMARY KEY DEFAULT uuidv7(),
    skill_id    uuid         NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    alias       text         NOT NULL,
    locale      text,                                  -- 'en', 'ar', null = either
    created_at  timestamptz  NOT NULL DEFAULT now(),
    UNIQUE (skill_id, alias)
);
CREATE INDEX skill_aliases_alias_trgm ON skill_aliases USING gin (normalize_text(alias) gin_trgm_ops);
COMMENT ON TABLE skill_aliases IS
    'Alternative spellings/translations/abbreviations per skill. The skill extractor matches against this table first.';


-- ----------------------------------------------------------------------------
-- Synonym groups — query-expansion thesaurus (general, bilingual)
-- ----------------------------------------------------------------------------
-- The aliases tables above (company_aliases, skill_aliases) attach variant
-- strings to a specific *entity*. The synonym-group tables here are for
-- query-time expansion of free terms that are not bound to any single entity
-- — abbreviations, translations, equivalent phrasings, broader/narrower
-- concepts.
--
-- Each `synonym_groups` row represents one concept; its `synonym_terms`
-- children are the surface forms. Expansion at query time looks like:
--
--   SELECT t2.term
--   FROM   synonym_terms t1
--   JOIN   synonym_terms t2 USING (group_id)
--   WHERE  normalize_text(t1.term) = normalize_text(:user_input)
--     AND  t2.id <> t1.id
--     AND  (t1.locale IS NULL OR :locale IS NULL OR t1.locale = :locale);
--
-- The expanded set is then OR-joined into a tsquery / trigram match. Matches
-- can carry the group's `weight` into ranking, so loose ("broader") expansions
-- score below tight ("synonym") ones.
CREATE TABLE synonym_groups (
    id              uuid          PRIMARY KEY DEFAULT uuidv7(),
    canonical_term  text          NOT NULL,        -- the display form
    canonical_locale text,                          -- 'en', 'ar', null = either
    kind            synonym_kind  NOT NULL DEFAULT 'general',
    notes           text,                          -- editorial notes, sources, etc.
    -- When the group is anchored to a specific entity row, point at it.
    -- All optional — most groups are entity-free.
    skill_id        uuid          REFERENCES skills(id) ON DELETE SET NULL,
    company_id      uuid          REFERENCES companies(id) ON DELETE SET NULL,
    category_code   text          REFERENCES job_categories(code) ON DELETE SET NULL,
    is_active       boolean       NOT NULL DEFAULT true,
    created_at      timestamptz   NOT NULL DEFAULT now(),
    updated_at      timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX synonym_groups_kind    ON synonym_groups (kind) WHERE is_active;
CREATE INDEX synonym_groups_skill   ON synonym_groups (skill_id) WHERE skill_id IS NOT NULL;
CREATE INDEX synonym_groups_company ON synonym_groups (company_id) WHERE company_id IS NOT NULL;
COMMENT ON TABLE synonym_groups IS
    'One row per "concept". Children in synonym_terms are the surface forms (abbreviations, translations, paraphrases) that the app expands at query time.';

CREATE TABLE synonym_terms (
    id          uuid              PRIMARY KEY DEFAULT uuidv7(),
    group_id    uuid              NOT NULL REFERENCES synonym_groups(id) ON DELETE CASCADE,
    term        text              NOT NULL,
    locale      text,                                  -- 'en', 'ar', null = either
    relation    synonym_relation  NOT NULL DEFAULT 'synonym',
    -- Weight applied during ranking when this term contributed to the match.
    -- 1.0 = full equivalent; lower for broader/narrower mappings.
    weight      numeric(4,3)      NOT NULL DEFAULT 1.000
                                  CHECK (weight BETWEEN 0 AND 1),
    created_at  timestamptz       NOT NULL DEFAULT now(),
    UNIQUE (group_id, term)
);
-- Expression index on the normalized term so the bilingual + typo-tolerant
-- lookup path uses the same form as the rest of the schema. Trigram GIN gives
-- both fast equality (via normalize_text(t)=normalize_text(q)) and fuzzy
-- matching (via the % operator) over the same index.
CREATE INDEX synonym_terms_term_trgm  ON synonym_terms USING gin (normalize_text(term) gin_trgm_ops);
CREATE INDEX synonym_terms_group      ON synonym_terms (group_id);
CREATE INDEX synonym_terms_relation   ON synonym_terms (relation);
COMMENT ON TABLE synonym_terms IS
    'Surface forms in a synonym group. Normalized-expression trigram index supports both exact-after-normalization lookup and misspelling-tolerant matching from one structure.';


-- ----------------------------------------------------------------------------
-- Jobs (cluster) + postings (per-source observations)
-- ----------------------------------------------------------------------------
-- A *cluster* represents one real-world job opening. It is created the first
-- time a posting is seen and updated as additional postings are linked to it
-- (or unlinked, in the case of a mis-merge).
CREATE TABLE jobs (
    id                  uuid              PRIMARY KEY DEFAULT uuidv7(),
    company_id          uuid              REFERENCES companies(id) ON DELETE RESTRICT,

    -- Canonical text. Picked from the highest-trust posting in the cluster.
    title_en            text,
    title_ar            text,
    description_en      text,
    description_ar      text,

    -- Canonical metadata. Each may be NULL if no posting in the cluster
    -- provided it.
    category_code       text              REFERENCES job_categories(code),
    employment_type     employment_type,
    work_arrangement    work_arrangement,
    experience_level    experience_level,
    min_experience_years smallint         CHECK (min_experience_years IS NULL
                                                 OR min_experience_years BETWEEN 0 AND 60),
    max_experience_years smallint         CHECK (max_experience_years IS NULL
                                                 OR max_experience_years BETWEEN 0 AND 60),
    CHECK (min_experience_years IS NULL
           OR max_experience_years IS NULL
           OR min_experience_years <= max_experience_years),

    -- Primary location. city_id NULL when location is "Remote" or unspecified.
    -- For jobs that recruit into multiple offices, the primary city goes here
    -- and every office goes into `job_locations` (see below). This duplication
    -- is intentional: keeps the common "filter by city" query fast.
    -- `country_code` + `region_code` form a composite FK to `regions`; either
    -- both populated together or both NULL (MATCH SIMPLE).
    city_id             uuid              REFERENCES cities(id),
    region_code         text,
    country_code        char(2)           NOT NULL DEFAULT 'sa' REFERENCES countries(code),
    FOREIGN KEY (country_code, region_code) REFERENCES regions(country_code, code),
    -- Street-level office address as printed on the source (canonical).
    office_address      text,
    -- Lat / lon of the canonical office, for map pinning.
    office_latitude     numeric(9,6),
    office_longitude    numeric(9,6),
    -- How many days/week in office for hybrid roles (1..5). NULL when N/A.
    hybrid_days_per_week smallint         CHECK (hybrid_days_per_week IS NULL
                                                 OR hybrid_days_per_week BETWEEN 0 AND 7),
    -- For remote roles: ISO-3166 alpha-2 of the country the candidate must reside in.
    -- NULL means no restriction ("hire from anywhere").
    remote_country_restriction char(2)    REFERENCES countries(code),
    relocation_assistance      boolean,   -- NULL = unknown

    -- Hiring manager (the team lead doing the actual hiring) — distinct from
    -- the recruiter who posted. Captured when discoverable on the source.
    hiring_manager_name        text,
    hiring_manager_linkedin_url text,

    -- Salary (canonical). Stored as integers in the smallest currency unit is
    -- avoided — postings come with vague rounded numbers, so numeric is honest.
    salary_min          numeric(12,2)     CHECK (salary_min IS NULL OR salary_min >= 0),
    salary_max          numeric(12,2)     CHECK (salary_max IS NULL OR salary_max >= 0),
    salary_currency     char(3)           DEFAULT 'SAR',
    salary_period       salary_period,
    salary_is_negotiable boolean          NOT NULL DEFAULT false,
    CHECK (salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max),
    CHECK ((salary_min IS NULL AND salary_max IS NULL) OR salary_period IS NOT NULL),

    -- Education requirement (cluster-level).
    min_education_level     education_level,
    -- Preferred fields of study, free-text array (e.g. {"Computer Science","Software Engineering"}).
    -- An array rather than its own table because it's a soft filter, rarely searched standalone.
    preferred_fields_of_study text[]      NOT NULL DEFAULT '{}',

    -- Saudi-specific
    saudi_nationals_only boolean          NOT NULL DEFAULT false,
    -- Gender preference declared on the posting. 'any' = no restriction.
    gender_preference    gender_preference NOT NULL DEFAULT 'any',
    visa_sponsorship     boolean,         -- NULL = unknown
    requires_arabic      boolean,         -- NULL = unknown

    -- Dedupe / fake state
    verdict             cluster_verdict   NOT NULL DEFAULT 'pending',
    legit_score         numeric(4,3)      CHECK (legit_score IS NULL
                                                 OR legit_score BETWEEN 0 AND 1),
    -- The posting whose text/metadata is mirrored into the canonical columns.
    -- Updated when a higher-trust posting joins the cluster.
    canonical_posting_id uuid,            -- FK added after job_postings exists
    posting_count       integer           NOT NULL DEFAULT 0
                                          CHECK (posting_count >= 0),

    -- Lifecycle (cluster-level, derived from postings).
    first_seen_at       timestamptz       NOT NULL DEFAULT now(),
    last_seen_at        timestamptz       NOT NULL DEFAULT now(),
    closed_at           timestamptz,      -- when all postings became expired/removed

    -- Full-text search columns are generated and indexed; combine title +
    -- description so a single query covers both. `unaccent` folds Latin
    -- diacritics; Arabic search uses the 'simple' config to avoid stemming
    -- mistakes on a language Postgres doesn't ship a full dictionary for.
    search_en           tsvector          GENERATED ALWAYS AS (
        setweight(to_tsvector('english_unaccent', coalesce(title_en, '')), 'A') ||
        setweight(to_tsvector('english_unaccent', coalesce(description_en, '')), 'B')
    ) STORED,
    search_ar           tsvector          GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', normalize_ar(title_ar)), 'A') ||
        setweight(to_tsvector('simple', normalize_ar(description_ar)), 'B')
    ) STORED,

    created_at          timestamptz       NOT NULL DEFAULT now(),
    updated_at          timestamptz       NOT NULL DEFAULT now(),
    deleted_at          timestamptz,

    CHECK (title_en IS NOT NULL OR title_ar IS NOT NULL)
);
COMMENT ON TABLE jobs IS
    'Cluster of postings believed to represent one real job. Canonical text + metadata mirrors the highest-trust posting in the cluster.';
COMMENT ON COLUMN jobs.canonical_posting_id IS
    'FK to job_postings; the posting whose data populates the canonical columns. Updated by the cluster-merge job.';

CREATE INDEX jobs_company           ON jobs (company_id) WHERE deleted_at IS NULL;
CREATE INDEX jobs_category          ON jobs (category_code) WHERE deleted_at IS NULL;
CREATE INDEX jobs_city              ON jobs (city_id) WHERE deleted_at IS NULL;
CREATE INDEX jobs_region            ON jobs (region_code) WHERE deleted_at IS NULL;
CREATE INDEX jobs_verdict_first_seen ON jobs (verdict, first_seen_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX jobs_open              ON jobs (last_seen_at DESC)
    WHERE deleted_at IS NULL AND closed_at IS NULL AND verdict IN ('legit', 'pending');
CREATE INDEX jobs_search_en_gin     ON jobs USING gin (search_en);
CREATE INDEX jobs_search_ar_gin     ON jobs USING gin (search_ar);

-- Trigram indexes for misspelling-tolerant matching. Same index can serve
-- both `LIKE '%foo%'` and `% / word_similarity()` queries. Built on the
-- *normalized* expression so the matcher sees the same text whether it
-- came from a query box or a crawl. Descriptions are large; their GIN
-- indexes take real space but make typo-tolerant body search feasible
-- without an external engine.
CREATE INDEX jobs_title_en_trgm        ON jobs USING gin (normalize_en(title_en) gin_trgm_ops)
    WHERE title_en IS NOT NULL;
CREATE INDEX jobs_title_ar_trgm        ON jobs USING gin (normalize_ar(title_ar) gin_trgm_ops)
    WHERE title_ar IS NOT NULL;
CREATE INDEX jobs_description_en_trgm  ON jobs USING gin (normalize_en(description_en) gin_trgm_ops)
    WHERE description_en IS NOT NULL;
CREATE INDEX jobs_description_ar_trgm  ON jobs USING gin (normalize_ar(description_ar) gin_trgm_ops)
    WHERE description_ar IS NOT NULL;


-- One row per (source, externally-identified posting). Immutable text fields
-- are captured at first-fetch; subsequent fetches produce `posting_snapshots`
-- rows. This split keeps the hot table small while preserving history.
CREATE TABLE job_postings (
    id                       uuid          PRIMARY KEY DEFAULT uuidv7(),
    source_id                uuid          NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    -- Source-side stable id (LinkedIn numeric id, Greenhouse posting id, ...).
    -- For sources without one we fall back to the URL's normalised slug.
    source_job_external_id   text          NOT NULL,
    canonical_url            text          NOT NULL,
    -- url_hash is a deterministic dedupe key for "exact same URL across crawls".
    -- Stored as bytea (sha256 over the normalised URL).
    url_hash                 bytea         NOT NULL,

    -- Cluster membership; NULL until clustering assigns it.
    cluster_job_id           uuid          REFERENCES jobs(id) ON DELETE SET NULL,

    -- Resolved company (may be NULL during initial fetch, set after company
    -- resolution runs).
    company_id               uuid          REFERENCES companies(id) ON DELETE SET NULL,
    -- The free-text employer name as printed on the source (kept verbatim).
    raw_company_name         text,

    -- Individual recruiter who uploaded the posting, when discoverable
    -- (LinkedIn + Bayt expose poster identity; ATS pages rarely do).
    posted_by_recruiter_id   uuid          REFERENCES recruiters(id) ON DELETE SET NULL,
    raw_poster_name          text,                    -- verbatim, even if recruiter row not resolved yet

    -- Text as posted on the source. Same column pairs as `jobs`, but here
    -- they are immutable evidence rather than derived canon.
    title                    text          NOT NULL,
    description              text,
    description_html         text,
    -- sha256 of normalised description text — drives the 'exact_content_hash'
    -- dedupe rule and lets us detect re-posts that copy-paste body.
    content_hash             bytea,

    employment_type          employment_type,
    work_arrangement         work_arrangement,
    experience_level         experience_level,
    raw_location             text,                    -- "Riyadh, KSA · Hybrid" verbatim
    city_id                  uuid          REFERENCES cities(id),
    region_code              text,
    country_code             char(2)       NOT NULL DEFAULT 'sa' REFERENCES countries(code),
    FOREIGN KEY (country_code, region_code) REFERENCES regions(country_code, code),
    office_address           text,                    -- as printed, sometimes ATS-only data
    hybrid_days_per_week     smallint      CHECK (hybrid_days_per_week IS NULL
                                                  OR hybrid_days_per_week BETWEEN 0 AND 7),
    remote_country_restriction char(2)     REFERENCES countries(code),
    relocation_assistance    boolean,
    -- True when the posting explicitly restricts the role to Saudi nationals
    -- (Nitaqat / Saudization). Detected by parsers via phrase matching on
    -- the description (Arabic + English). Mirrored to jobs.saudi_nationals_only
    -- on recompute_canonical.
    saudi_nationals_only     boolean       NOT NULL DEFAULT false,
    -- Gender preference declared on the posting. 'any' = no restriction.
    gender_preference        gender_preference NOT NULL DEFAULT 'any',

    -- Hiring manager (per-posting; the cluster mirrors the canonical posting's value).
    hiring_manager_name      text,
    hiring_manager_linkedin_url text,

    salary_min               numeric(12,2) CHECK (salary_min IS NULL OR salary_min >= 0),
    salary_max               numeric(12,2) CHECK (salary_max IS NULL OR salary_max >= 0),
    salary_currency          char(3),
    salary_period            salary_period,
    CHECK (salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max),

    -- Lifecycle on the source side.
    status                   posting_status NOT NULL DEFAULT 'active',
    posted_at                timestamptz,             -- as reported by source (first publish)
    -- When the source last modified the posting (Greenhouse `updated_at`,
    -- LinkedIn's edit-timestamp, etc.). Separate from our `last_fetch_at`
    -- which is "when WE last fetched it".
    source_updated_at        timestamptz,
    expires_at               timestamptz,
    first_seen_at            timestamptz   NOT NULL DEFAULT now(),
    last_seen_at             timestamptz   NOT NULL DEFAULT now(),
    last_fetch_at            timestamptz   NOT NULL DEFAULT now(),
    fetch_count              integer       NOT NULL DEFAULT 1
                                           CHECK (fetch_count >= 1),

    -- Full original payload from the scraper (HTML metadata, JSON-LD, ATS
    -- API response, ...). Lets us re-extract structured fields without
    -- re-crawling and aids forensics on bad parses.
    raw_payload              jsonb         NOT NULL DEFAULT '{}'::jsonb,

    -- A posting row is *never* deleted; status moves to 'removed' instead.
    -- This means the dedupe pipeline can still reason about disappeared posts.

    UNIQUE (source_id, source_job_external_id),
    UNIQUE (source_id, url_hash)
);
COMMENT ON TABLE job_postings IS
    'One row per crawled posting. Immutable evidence; mutations land in posting_snapshots. Never hard-deleted (status moves to removed).';
COMMENT ON COLUMN job_postings.content_hash IS
    'sha256 of the normalised description body. Drives exact-content dedupe and re-post detection.';
COMMENT ON COLUMN job_postings.raw_payload IS
    'Full scraper payload. Re-extraction-friendly; debug-friendly. Keep PII-free where possible.';

CREATE INDEX job_postings_cluster       ON job_postings (cluster_job_id) WHERE cluster_job_id IS NOT NULL;
CREATE INDEX job_postings_company       ON job_postings (company_id) WHERE company_id IS NOT NULL;
CREATE INDEX job_postings_recruiter     ON job_postings (posted_by_recruiter_id) WHERE posted_by_recruiter_id IS NOT NULL;
CREATE INDEX job_postings_source        ON job_postings (source_id, status);
CREATE INDEX job_postings_content_hash  ON job_postings (content_hash) WHERE content_hash IS NOT NULL;
CREATE INDEX job_postings_url_hash      ON job_postings (url_hash);
CREATE INDEX job_postings_active        ON job_postings (last_seen_at DESC)
    WHERE status = 'active';
CREATE INDEX job_postings_title_trgm    ON job_postings USING gin (normalize_text(title) gin_trgm_ops);
CREATE INDEX job_postings_raw_company_trgm ON job_postings USING gin (normalize_text(raw_company_name) gin_trgm_ops)
    WHERE raw_company_name IS NOT NULL;
CREATE INDEX job_postings_raw_payload   ON job_postings USING gin (raw_payload jsonb_path_ops);

-- Now that job_postings exists, close the loop with the canonical_posting_id FK.
-- DEFERRABLE so the cluster-merge transaction can update both sides safely.
ALTER TABLE jobs
    ADD CONSTRAINT jobs_canonical_posting_fk
    FOREIGN KEY (canonical_posting_id) REFERENCES job_postings(id)
    DEFERRABLE INITIALLY DEFERRED;


-- ----------------------------------------------------------------------------
-- Application channels — how a candidate applies (0..N per posting)
-- ----------------------------------------------------------------------------
-- Stored per posting, not per cluster, because the same job re-posted on
-- different sources may advertise different apply paths (ATS link vs
-- recruiter WhatsApp). Feeds the `contact_via_personal_channel` fake signal.
CREATE TABLE application_channels (
    id            uuid                     PRIMARY KEY DEFAULT uuidv7(),
    posting_id    uuid                     NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    kind          application_channel_kind NOT NULL,
    -- The destination: a URL, email address, phone number, etc. Validation
    -- per `kind` happens in the app layer; the DB stays format-agnostic.
    value         text                     NOT NULL,
    -- True for the primary apply path advertised on the posting.
    is_primary    boolean                  NOT NULL DEFAULT false,
    -- Captured at extraction time for forensics.
    raw_label     text,                    -- e.g. "Apply via WhatsApp", "Send CV to ..."
    created_at    timestamptz              NOT NULL DEFAULT now(),
    UNIQUE (posting_id, kind, value)
);
CREATE INDEX application_channels_posting   ON application_channels (posting_id);
CREATE INDEX application_channels_kind      ON application_channels (kind);
-- At most one primary channel per posting.
CREATE UNIQUE INDEX application_channels_one_primary
    ON application_channels (posting_id) WHERE is_primary;
COMMENT ON TABLE application_channels IS
    'How to apply to a posting. Multiple channels allowed; at most one marked primary. Used by both UI and the fake-detection pipeline.';


-- ----------------------------------------------------------------------------
-- Multi-office support for clusters
-- ----------------------------------------------------------------------------
-- Some companies recruit one role into several offices simultaneously
-- ("Software Engineer, open in Riyadh / Jeddah / Dammam"). The cluster's
-- canonical city is its primary location; every additional office lives here.
-- Filters that need to surface a job in any of its locations can join here:
--
--   SELECT j.* FROM jobs j
--   WHERE EXISTS (
--     SELECT 1 FROM job_locations l
--     WHERE l.job_id = j.id AND l.city_id = :wanted_city
--   ) OR j.city_id = :wanted_city;
CREATE TABLE job_locations (
    id              uuid          PRIMARY KEY DEFAULT uuidv7(),
    job_id          uuid          NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    city_id         uuid          REFERENCES cities(id),
    region_code     text,
    country_code    char(2)       NOT NULL DEFAULT 'sa' REFERENCES countries(code),
    FOREIGN KEY (country_code, region_code) REFERENCES regions(country_code, code),
    office_address  text,
    latitude        numeric(9,6),
    longitude       numeric(9,6),
    is_primary      boolean       NOT NULL DEFAULT false,
    notes           text,
    created_at      timestamptz   NOT NULL DEFAULT now(),
    -- At least one of city / region / country must be set; freestanding rows
    -- without geography would be useless.
    CHECK (city_id IS NOT NULL OR region_code IS NOT NULL OR country_code IS NOT NULL)
);
CREATE INDEX job_locations_job        ON job_locations (job_id);
CREATE INDEX job_locations_city       ON job_locations (city_id) WHERE city_id IS NOT NULL;
CREATE INDEX job_locations_region     ON job_locations (region_code) WHERE region_code IS NOT NULL;
-- At most one primary location per job.
CREATE UNIQUE INDEX job_locations_one_primary
    ON job_locations (job_id) WHERE is_primary;
COMMENT ON TABLE job_locations IS
    'Additional offices for a cluster. The primary location is also kept on jobs.city_id for fast filtering.';


-- Snapshot table — one row per fetch that observed a *change* to a posting.
-- Stores only the changed fields plus a checksum, so storage stays bounded
-- even for high-churn aggregator pages.
CREATE TABLE posting_snapshots (
    id              uuid          PRIMARY KEY DEFAULT uuidv7(),
    posting_id      uuid          NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    fetched_at      timestamptz   NOT NULL DEFAULT now(),
    -- Sparse JSON of {field: new_value}. Compact and queryable.
    changed_fields  jsonb         NOT NULL,
    content_hash    bytea,        -- description hash at this snapshot
    status          posting_status NOT NULL,
    UNIQUE (posting_id, fetched_at)
);
CREATE INDEX posting_snapshots_posting_time ON posting_snapshots (posting_id, fetched_at DESC);
COMMENT ON TABLE posting_snapshots IS
    'Append-only diff history for a posting. Lets us answer "when did salary change?" or "when did this go from active to expired?".';


-- ----------------------------------------------------------------------------
-- Dedupe: pairwise evidence between postings
-- ----------------------------------------------------------------------------
-- An undirected edge graph: (lower_id, higher_id) ordering avoids storing
-- a pair twice. Multiple reasons for the same pair → multiple rows, each
-- carrying its own score, so we keep audit trail of every signal that fired.
CREATE TABLE posting_duplicate_edges (
    id              uuid              PRIMARY KEY DEFAULT uuidv7(),
    posting_a_id    uuid              NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    posting_b_id    uuid              NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    reason          duplicate_reason  NOT NULL,
    similarity      numeric(4,3)      NOT NULL CHECK (similarity BETWEEN 0 AND 1),
    detected_at     timestamptz       NOT NULL DEFAULT now(),
    detector_version text             NOT NULL DEFAULT 'v1',
    CHECK (posting_a_id < posting_b_id),             -- canonical ordering
    UNIQUE (posting_a_id, posting_b_id, reason)
);
CREATE INDEX posting_dup_edges_a ON posting_duplicate_edges (posting_a_id);
CREATE INDEX posting_dup_edges_b ON posting_duplicate_edges (posting_b_id);
COMMENT ON TABLE posting_duplicate_edges IS
    'Pairwise similarity evidence between postings. The clustering job consumes these edges + trust weights to assign cluster_job_id.';


-- ----------------------------------------------------------------------------
-- Fake / recycled heuristics — evidence rows per cluster
-- ----------------------------------------------------------------------------
-- One row per fired signal. The cluster's `legit_score` and `verdict` are
-- recomputed from these rows by an offline job, so the heuristic mix can be
-- changed without losing historical evidence.
CREATE TABLE job_fake_signals (
    id              uuid             PRIMARY KEY DEFAULT uuidv7(),
    job_id          uuid             NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    posting_id      uuid             REFERENCES job_postings(id) ON DELETE CASCADE,
    kind            fake_signal_kind NOT NULL,
    -- Weight in [-1, 1]; negative = "more likely fake/recycled".
    weight          numeric(4,3)     NOT NULL CHECK (weight BETWEEN -1 AND 1),
    -- Free-form context: what number was the outlier, which company id matched, etc.
    details         jsonb            NOT NULL DEFAULT '{}'::jsonb,
    detected_at     timestamptz      NOT NULL DEFAULT now(),
    detector_version text            NOT NULL DEFAULT 'v1'
);
CREATE INDEX job_fake_signals_job  ON job_fake_signals (job_id);
CREATE INDEX job_fake_signals_kind ON job_fake_signals (kind, detected_at DESC);
COMMENT ON TABLE job_fake_signals IS
    'Append-only evidence rows from heuristics. legit_score on the cluster is recomputed from these so the model can evolve.';


-- ----------------------------------------------------------------------------
-- Skills <-> jobs linking
-- ----------------------------------------------------------------------------
-- Cluster-level resolved skills. These are the ones served to users.
-- Fields are chosen to support granular candidate-to-job matching:
--   * requirement       — coarse must/should/nice bucket
--   * importance        — fine-grained weight used in match scoring
--   * proficiency_level — depth expected (basic..expert/native)
--   * min_years         — minimum years of experience with this skill
--   * max_years         — rare; used when the role wants juniors only
--   * last_used_within_years — recency constraint (e.g. "used Python in last 3y")
--   * confidence        — extractor confidence in the resolution itself
CREATE TABLE job_skills (
    job_id                  uuid               NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    skill_id                uuid               NOT NULL REFERENCES skills(id) ON DELETE RESTRICT,
    requirement             skill_requirement  NOT NULL DEFAULT 'required',
    proficiency_level       skill_proficiency,
    min_years               smallint           CHECK (min_years IS NULL OR min_years BETWEEN 0 AND 60),
    max_years               smallint           CHECK (max_years IS NULL OR max_years BETWEEN 0 AND 60),
    last_used_within_years  smallint           CHECK (last_used_within_years IS NULL
                                                     OR last_used_within_years BETWEEN 0 AND 60),
    -- Weight used by the matching scorer; defaults derived from `requirement`
    -- but can be overridden when the role makes one skill disproportionately
    -- important (e.g. the entire role is "Salesforce Admin").
    importance              numeric(4,3)       NOT NULL DEFAULT 0.500
                                               CHECK (importance BETWEEN 0 AND 1),
    -- Confidence the extractor was correct about this skill being mentioned.
    confidence              numeric(4,3)       NOT NULL DEFAULT 1.000
                                               CHECK (confidence BETWEEN 0 AND 1),
    created_at              timestamptz        NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, skill_id),
    CHECK (min_years IS NULL OR max_years IS NULL OR min_years <= max_years)
);
CREATE INDEX job_skills_skill                ON job_skills (skill_id);
CREATE INDEX job_skills_skill_required       ON job_skills (skill_id) WHERE requirement = 'required';
CREATE INDEX job_skills_skill_proficiency    ON job_skills (skill_id, proficiency_level)
    WHERE proficiency_level IS NOT NULL;
COMMENT ON TABLE job_skills IS
    'Resolved skill requirements per cluster. Carries enough granularity (level, years, recency, weight) for candidate-to-job match scoring.';

-- Raw extracted skill mentions per posting, before normalization. Useful for
-- training the extractor and reconstructing per-source skill phrasings.
-- A `skill_id` of NULL means the extractor saw a phrase but no canonical
-- match was found yet — these feed the human-review queue for new aliases.
CREATE TABLE posting_skills_raw (
    id           uuid               PRIMARY KEY DEFAULT uuidv7(),
    posting_id   uuid               NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    skill_id     uuid               REFERENCES skills(id) ON DELETE SET NULL,
    raw_phrase   text               NOT NULL,
    extractor_version text          NOT NULL DEFAULT 'v1',
    confidence   numeric(4,3)       NOT NULL DEFAULT 1.000 CHECK (confidence BETWEEN 0 AND 1),
    created_at   timestamptz        NOT NULL DEFAULT now(),
    UNIQUE (posting_id, raw_phrase, extractor_version)
);
CREATE INDEX posting_skills_raw_skill   ON posting_skills_raw (skill_id) WHERE skill_id IS NOT NULL;
CREATE INDEX posting_skills_raw_unmatched ON posting_skills_raw (posting_id) WHERE skill_id IS NULL;
COMMENT ON TABLE posting_skills_raw IS
    'Every skill-like phrase the extractor saw, per posting. NULL skill_id = unmatched, feeds the alias-review queue.';


-- ----------------------------------------------------------------------------
-- Crawl operations
-- ----------------------------------------------------------------------------
CREATE TABLE crawl_runs (
    id            uuid              PRIMARY KEY DEFAULT uuidv7(),
    source_id     uuid              NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    status        crawl_run_status  NOT NULL DEFAULT 'queued',
    started_at    timestamptz,
    finished_at   timestamptz,
    -- Counters maintained by the worker.
    pages_fetched integer           NOT NULL DEFAULT 0 CHECK (pages_fetched >= 0),
    postings_seen integer           NOT NULL DEFAULT 0 CHECK (postings_seen >= 0),
    postings_new  integer           NOT NULL DEFAULT 0 CHECK (postings_new  >= 0),
    error_count   integer           NOT NULL DEFAULT 0 CHECK (error_count   >= 0),
    -- Crawl config used for this run (query terms, filters, seed URLs, etc.).
    config        jsonb             NOT NULL DEFAULT '{}'::jsonb,
    error_summary text,
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);
CREATE INDEX crawl_runs_source_started ON crawl_runs (source_id, started_at DESC);
CREATE INDEX crawl_runs_status         ON crawl_runs (status) WHERE status IN ('queued', 'running');
COMMENT ON TABLE crawl_runs IS
    'One row per scheduled crawl execution. Used for monitoring, retries, and back-pressure.';

-- Per-fetch ledger. High-volume — partition by month if it grows beyond
-- a few hundred million rows.
CREATE TABLE crawl_fetches (
    id            uuid          PRIMARY KEY DEFAULT uuidv7(),
    run_id        uuid          NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
    source_id     uuid          NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    posting_id    uuid          REFERENCES job_postings(id) ON DELETE SET NULL,
    url           text          NOT NULL,
    http_status   smallint,
    fetched_at    timestamptz   NOT NULL DEFAULT now(),
    duration_ms   integer       CHECK (duration_ms IS NULL OR duration_ms >= 0),
    bytes         integer       CHECK (bytes IS NULL OR bytes >= 0),
    -- 'created' | 'updated' | 'unchanged' | 'error'
    outcome       text          NOT NULL,
    error_message text
);
CREATE INDEX crawl_fetches_run     ON crawl_fetches (run_id);
CREATE INDEX crawl_fetches_posting ON crawl_fetches (posting_id) WHERE posting_id IS NOT NULL;
CREATE INDEX crawl_fetches_failed  ON crawl_fetches (fetched_at DESC) WHERE outcome = 'error';
COMMENT ON TABLE crawl_fetches IS
    'Per-HTTP-fetch audit trail. Partition by month if volume grows.';


-- ----------------------------------------------------------------------------
-- Crawler health — auto-detect-breakage state
-- ----------------------------------------------------------------------------
-- One row per source. Rolling parse-rate + canary status + breakage stamp.
-- Updated by `core.health.evaluate(source_id)` after every run.
--
-- Lifecycle of `broken_since`:
--   * NULL                 — healthy
--   * non-null timestamp   — breakage detected; the crawler is auto-disabled
--                            (sources.crawl_enabled set to false in the same
--                            transaction). Cleared by the next successful
--                            canary run on a new `crawler_version`.
CREATE TABLE crawler_health (
    source_id          uuid          PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    crawler_version    text          NOT NULL DEFAULT 'v1',

    last_run_at        timestamptz,
    last_success_at    timestamptz,
    -- 7-day rolling parse-success rate (parsed / fetched). NULL until 5+ runs.
    parse_success_rate numeric(4,3)  CHECK (parse_success_rate IS NULL
                                            OR parse_success_rate BETWEEN 0 AND 1),
    -- 7-day rolling required-field fill rate.
    field_fill_rate    numeric(4,3)  CHECK (field_fill_rate IS NULL
                                            OR field_fill_rate BETWEEN 0 AND 1),

    canary_last_at     timestamptz,
    canary_ok          boolean,
    canary_consecutive_failures integer NOT NULL DEFAULT 0
                                        CHECK (canary_consecutive_failures >= 0),
    canary_last_error  text,

    -- Breakage state.
    broken_since       timestamptz,
    breakage_reason    text,
    breakage_signal    text,        -- 'canary' | 'parse_rate' | 'field_fill' | 'manual'

    updated_at         timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX crawler_health_broken  ON crawler_health (broken_since)
    WHERE broken_since IS NOT NULL;
COMMENT ON TABLE crawler_health IS
    'Per-source health state. broken_since != NULL = auto-disabled. Updated after every run by core.health.evaluate().';


-- ----------------------------------------------------------------------------
-- updated_at maintenance
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_sources_updated_at         BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_companies_updated_at       BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_recruiters_updated_at      BEFORE UPDATE ON recruiters
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_skills_updated_at          BEFORE UPDATE ON skills
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_synonym_groups_updated_at  BEFORE UPDATE ON synonym_groups
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_crawler_health_updated_at  BEFORE UPDATE ON crawler_health
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_jobs_updated_at            BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ----------------------------------------------------------------------------
-- Convenience view: active, non-fake clusters (the default API surface)
-- ----------------------------------------------------------------------------
CREATE VIEW jobs_public AS
    SELECT j.*
    FROM jobs j
    WHERE j.deleted_at IS NULL
      AND j.closed_at  IS NULL
      AND j.verdict    IN ('legit', 'pending');
COMMENT ON VIEW jobs_public IS
    'Default user-facing job feed: not deleted, not closed, not flagged fake/recycled.';
