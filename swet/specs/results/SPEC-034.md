# SPEC-034: Results Persistence and History

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-032 (Results computation engine)

## Overview
Provide users with a history view of all their completed assessments, including score trends over time and the ability to compare results across assessments. This page serves as the primary landing experience for returning users, showing their growth trajectory and linking to detailed results for each assessment.

## Requirements

### Functional
1. Display an assessment history page listing all completed assessments for the current user, ordered by date (most recent first)
2. Each history entry shows: assessment date, overall score, proficiency label, total time, grading status, and a link to the full results page
3. Render a score trend line chart showing overall score over time across all completed assessments
4. Support filtering the history list by:
   - Date range (from/to date pickers)
   - Grading status (all, auto_complete, grading, complete)
5. Display a comparison view when the user selects two assessments, showing side-by-side radar charts and per-competency score deltas
6. Show summary statistics at the top of the page: total assessments completed, average score, highest score, most recent proficiency level
7. Handle empty state when user has no completed assessments (prompt to start first assessment)

### Non-Functional
1. History page must load within 1 second for users with up to 50 assessments
2. Pagination: display 10 assessments per page with load-more or pagination controls
3. Trend chart must render smoothly with up to 100 data points
4. Date filtering should update the list without a full page reload

## Technical Design

### API Endpoints
- `GET /api/v1/results/history` - List all assessment results for the current user
  - Query params: `page` (default 1), `per_page` (default 10), `status` (optional), `from_date` (optional), `to_date` (optional)
  - Response: paginated list of `ResultSummary` items plus `total_count`
- `GET /api/v1/results/history/stats` - Summary statistics for the user
  - Response: `{ total_assessments, average_score, highest_score, latest_proficiency_label }`
- `GET /api/v1/results/history/trend` - Score trend data points
  - Response: list of `{ date, score }` for the trend chart
- `GET /api/v1/results/compare?ids=uuid1,uuid2` - Comparison data for two assessments
  - Response: two full result objects with competency scores for side-by-side display

### New Schemas
Add to `src/scoring/schemas.py`:

```python
class ResultSummary(BaseModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    overall_score: float
    proficiency_label: str
    total_time_seconds: int
    grading_status: str
    created_at: datetime

class HistoryResponse(BaseModel):
    items: list[ResultSummary]
    total_count: int
    page: int
    per_page: int

class HistoryStatsResponse(BaseModel):
    total_assessments: int
    average_score: float
    highest_score: float
    latest_proficiency_label: str

class TrendDataPoint(BaseModel):
    date: datetime
    score: float

class TrendResponse(BaseModel):
    data: list[TrendDataPoint]

class CompareResponse(BaseModel):
    results: list[ResultResponse]
```

### Frontend Components

**Page: `app/src/app/(auth)/history/page.tsx`**
- Server component with client-side filtering and pagination
- Fetches initial history data and stats on mount

**`HistoryList`** (`app/src/components/results/history-list.tsx`)
- Table or card list of assessment history entries
- Each row links to `/results/{assessment_id}`
- Includes pagination controls
- Props: `items: ResultSummary[]`, `totalCount`, `page`, `onPageChange`

**`HistoryStats`** (`app/src/components/results/history-stats.tsx`)
- Summary cards showing total assessments, average score, highest score, latest level
- Props: `stats: HistoryStatsResponse`

**`TrendChart`** (`app/src/components/results/trend-chart.tsx`)
- Line chart (Recharts `LineChart`) showing score over time
- X-axis: assessment dates, Y-axis: 0-100 score
- Tooltip showing exact score and date on hover
- Props: `data: TrendDataPoint[]`

**`HistoryFilters`** (`app/src/components/results/history-filters.tsx`)
- Date range inputs and status dropdown
- Emits filter changes to parent to trigger refetch
- Props: `onFilterChange: (filters) => void`

**`CompareView`** (`app/src/components/results/compare-view.tsx`)
- Side-by-side radar charts for two selected assessments
- Competency delta table showing improvement/regression per competency
- Props: `results: [ResultResponse, ResultResponse]`

### Data Fetching
```typescript
const useHistory = (filters: HistoryFilters) =>
  useQuery({
    queryKey: ["history", filters],
    queryFn: () => api.get("/results/history", { params: filters }),
  });

const useHistoryStats = () =>
  useQuery({
    queryKey: ["history-stats"],
    queryFn: () => api.get("/results/history/stats"),
  });

const useTrend = () =>
  useQuery({
    queryKey: ["history-trend"],
    queryFn: () => api.get("/results/history/trend"),
  });

const useCompare = (id1: string, id2: string) =>
  useQuery({
    queryKey: ["compare", id1, id2],
    queryFn: () => api.get(`/results/compare?ids=${id1},${id2}`),
    enabled: !!id1 && !!id2,
  });
```

### Database Queries
- History list: `SELECT * FROM assessment_results WHERE user_id = :uid ORDER BY created_at DESC LIMIT :limit OFFSET :offset` with optional `WHERE` clauses for status and date range
- Stats: aggregate query with `COUNT`, `AVG`, `MAX` over `assessment_results` for the user
- Trend: `SELECT created_at, overall_score FROM assessment_results WHERE user_id = :uid ORDER BY created_at ASC`
- Add index on `assessment_results(user_id, created_at)` for efficient history queries

### Database Changes
- Add composite index: `CREATE INDEX ix_assessment_results_user_date ON assessment_results (user_id, created_at DESC)`

## Implementation Notes
- Use `next/dynamic` with `ssr: false` for the trend chart (Recharts SSR issues)
- Comparison requires selecting exactly two assessments; use checkbox selection in the history list with a "Compare" button that enables when exactly two are checked
- Empty state should include a call-to-action button linking to `/assessment/start`
- Consider using URL search params for filter state so filtered views are shareable/bookmarkable
- Pagination uses offset-based approach since assessment history is append-only and reordering is unlikely

## Testing Strategy
- Unit tests for: `HistoryList` renders correct number of rows, `HistoryStats` displays formatted stats, `TrendChart` handles empty data, `HistoryFilters` emits correct filter objects, pagination controls
- Integration tests for: history API returns paginated results, filtering by date range works, filtering by status works, stats computation is correct, trend data is sorted chronologically
- E2E tests for: history page loads with assessments listed, clicking an entry navigates to results page, filter changes update the list, compare view shows two radar charts side by side

## Acceptance Criteria
- [ ] History page lists all completed assessments for the current user
- [ ] Each entry displays score, proficiency label, time, date, and grading status
- [ ] Clicking an entry navigates to the full results page
- [ ] Score trend chart renders with correct data points over time
- [ ] Date range filter narrows the displayed assessments
- [ ] Status filter shows only assessments matching the selected status
- [ ] Summary statistics (total, average, highest, latest level) are accurate
- [ ] Comparison view shows side-by-side radar charts with competency deltas
- [ ] Empty state is shown when the user has no completed assessments
- [ ] Pagination works correctly with 10 items per page
- [ ] History page loads within 1 second for 50 assessments
