# SPEC-040: Performance Optimization

## Status
Draft

## Priority
P2

## Dependencies
- SPEC-033 (Results visualization)

## Overview
Optimize the SWET platform for production-grade performance across frontend bundle size, backend response times, and database query efficiency. This spec targets the most impactful bottlenecks: large client-side bundles from question renderers and Shiki, slow database queries missing indexes, and uncached API responses.

## Requirements

### Functional
1. Code-split question renderer components so only the active renderer is loaded (MCQ renderer should not load the code editor bundle)
2. Lazy-load results visualization charts (radar chart, trend chart) using Next.js dynamic imports with `ssr: false`
3. Optimize the Shiki syntax highlighter bundle to include only the languages used in assessments (not the full ~150 language pack)
4. Add database indexes for the most common query patterns identified in the assessment and scoring flows
5. Configure API response caching headers for static/semi-static data (competency definitions, role weights)
6. Tune PostgreSQL connection pooling for concurrent assessment sessions

### Non-Functional
1. Initial page load (LCP) must be under 2.5 seconds on a 4G connection
2. JavaScript bundle per route must not exceed 200KB gzipped
3. API endpoints must respond within 200ms at the 95th percentile under 100 concurrent users
4. Database connection pool must handle 50 concurrent connections without exhaustion
5. Time to Interactive (TTI) must be under 3 seconds on mid-range mobile devices

## Technical Design

### Frontend: Code Splitting

**Question Renderers:**
```typescript
// app/src/components/assessment/question-renderer.tsx
import dynamic from "next/dynamic";

const renderers = {
  multiple_choice: dynamic(() => import("./renderers/mcq-renderer")),
  code_review: dynamic(() => import("./renderers/code-review-renderer")),
  debugging: dynamic(() => import("./renderers/debugging-renderer")),
  short_answer: dynamic(() => import("./renderers/short-answer-renderer")),
  design_prompt: dynamic(() => import("./renderers/design-prompt-renderer")),
};
```

**Results Charts:**
```typescript
const RadarChart = dynamic(
  () => import("@/components/results/radar-chart"),
  { ssr: false, loading: () => <ChartSkeleton /> }
);

const TrendChart = dynamic(
  () => import("@/components/results/trend-chart"),
  { ssr: false, loading: () => <ChartSkeleton /> }
);
```

### Frontend: Shiki Optimization
Configure Shiki to load only required language grammars:

```typescript
import { createHighlighter } from "shiki";

const SUPPORTED_LANGUAGES = [
  "javascript", "typescript", "python", "java", "go",
  "rust", "sql", "bash", "json", "yaml", "html", "css",
];

const highlighter = await createHighlighter({
  themes: ["github-dark", "github-light"],
  langs: SUPPORTED_LANGUAGES,
});
```

Use `shiki/bundle/web` instead of the full `shiki` import to reduce the base bundle.

### Backend: Database Indexes
Add the following indexes via Alembic migration:

```sql
-- Assessment queries by user
CREATE INDEX ix_assessments_user_status ON assessments (user_id, status);

-- Answer lookups during grading
CREATE INDEX ix_answers_assessment_question ON answers (assessment_id, question_id);

-- Grade lookups by answer
CREATE INDEX ix_answer_grades_answer ON answer_grades (answer_id);

-- Question pool lookups
CREATE INDEX ix_question_pools_config_competency ON question_pools (config_hash, competency_id, difficulty);

-- Results history
CREATE INDEX ix_assessment_results_user_date ON assessment_results (user_id, created_at DESC);

-- Competency score lookups
CREATE INDEX ix_competency_scores_result ON competency_scores (result_id);
```

### Backend: Connection Pooling
Update `src/database.py` to tune SQLAlchemy async pool:

```python
engine = create_async_engine(
    settings.database_url,
    pool_size=20,           # base connections
    max_overflow=30,        # burst capacity (total max = 50)
    pool_timeout=30,        # wait for connection before error
    pool_recycle=1800,      # recycle connections every 30 min
    pool_pre_ping=True,     # validate connections before use
)
```

### Backend: Response Caching
Add cache headers for semi-static endpoints:

```python
from fastapi import Response

@router.get("/competencies")
async def list_competencies(response: Response):
    response.headers["Cache-Control"] = "public, max-age=3600"  # 1 hour
    ...

@router.get("/role-weights/{role}")
async def get_role_weights(role: str, response: Response):
    response.headers["Cache-Control"] = "public, max-age=3600"
    ...
```

For user-specific endpoints, use `Cache-Control: private, no-cache` to prevent CDN caching of personal data.

### Bundle Analysis
Add `@next/bundle-analyzer` to the dev dependencies:

```javascript
// next.config.ts
const withBundleAnalyzer = require("@next/bundle-analyzer")({
  enabled: process.env.ANALYZE === "true",
});
module.exports = withBundleAnalyzer(nextConfig);
```

## Implementation Notes
- Measure before optimizing: use `ANALYZE=true pnpm build` and Lighthouse CI to establish baselines before making changes
- Shiki lazy loading is particularly important because the full bundle can be 2MB+; the subset approach reduces it to ~200KB
- Connection pool `pool_size=20` is tuned for a single backend instance; adjust if running multiple replicas
- Index creation should be done in a non-locking migration (`CREATE INDEX CONCURRENTLY`) for zero-downtime deployments
- Consider adding `react-window` or similar virtualization if the history list grows beyond 100 items
- Do not cache endpoints that include user-specific or assessment-specific data unless using `Vary` headers properly

## Testing Strategy
- Unit tests for: dynamic imports resolve correctly, Shiki loads only specified languages
- Integration tests for: database queries use expected indexes (check `EXPLAIN ANALYZE` output), connection pool handles concurrent requests without errors, cache headers are present on appropriate endpoints
- E2E tests for: Lighthouse performance score >= 90 on key pages (assessment, results, history), page load time under 3s on throttled connection

## Acceptance Criteria
- [ ] Question renderers are code-split (only active renderer's JS is loaded)
- [ ] Results charts load via dynamic import with `ssr: false`
- [ ] Shiki bundle includes only the 12 supported languages
- [ ] All identified database queries have appropriate indexes
- [ ] Connection pool is configured with `pool_size=20`, `max_overflow=30`
- [ ] Semi-static API endpoints return `Cache-Control` headers
- [ ] Bundle analyzer is available via `ANALYZE=true pnpm build`
- [ ] No single route bundle exceeds 200KB gzipped
- [ ] API 95th percentile response time is under 200ms with 100 concurrent users
- [ ] LCP is under 2.5 seconds on simulated 4G
