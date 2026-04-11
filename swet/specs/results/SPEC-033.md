# SPEC-033: Results Visualization

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-032 (Results computation engine)

## Overview
Build the frontend results page that presents a user's assessment outcome through a radar chart of competency scores, detailed per-competency breakdowns, proficiency level badges, and actionable growth recommendations. The page provides an at-a-glance summary and drill-down capability for each of the 12 competencies.

## Requirements

### Functional
1. Display an overall results summary showing: overall score (0-100), proficiency label and level badge, total time taken (formatted as HH:MM:SS), assessment date, and grading status
2. Render a radar chart showing the user's score across all 12 competencies, with competency names as axis labels and scores scaled 0-100
3. Display detailed competency breakdown cards, each showing:
   - Competency name and category (transferable/context)
   - Score (0-100) with a visual progress bar
   - Proficiency level badge (novice/beginner/intermediate/advanced/expert)
   - Questions total and correct count
   - AI-graded average (if applicable)
4. Generate growth recommendations per competency based on proficiency level:
   - Novice/Beginner: foundational learning resources
   - Intermediate: practice exercises and deeper concepts
   - Advanced/Expert: advanced topics and mentoring suggestions
5. Show a loading/polling state while AI grading is in progress, auto-refreshing until `grading_status = "complete"`
6. Handle error states: result not found, grading failed, network errors

### Non-Functional
1. Results page must render within 1 second after data is fetched
2. Radar chart must be responsive and readable on screens from 375px to 1920px wide
3. Charts must support reduced motion preferences (no animation if `prefers-reduced-motion` is set)
4. Color scheme for proficiency levels must maintain sufficient contrast (WCAG AA)

## Technical Design

### API Endpoints
All endpoints are under `/api/v1/results` (already scaffolded):
- `GET /api/v1/results/{assessment_id}` - Full results with competency scores
- `GET /api/v1/results/{assessment_id}/radar` - Radar chart data points
- `GET /api/v1/results/{assessment_id}/breakdown` - Detailed per-competency breakdown with recommendations
- `GET /api/v1/results/{assessment_id}/grading-status` - Polling endpoint for grading progress

### New Schema: Breakdown Response
Add to `src/scoring/schemas.py`:

```python
class CompetencyBreakdownResponse(BaseModel):
    competency_id: int
    competency_name: str
    category: str
    score: float
    proficiency_level: int
    proficiency_label: str
    questions_total: int
    questions_correct: int
    ai_graded_avg: float | None
    recommendations: list[str]

class BreakdownResponse(BaseModel):
    competencies: list[CompetencyBreakdownResponse]
```

### Frontend Components

**Page: `app/src/app/(auth)/results/[id]/page.tsx`**
- Server component that fetches initial results data
- Handles loading, error, and grading-in-progress states

**`ResultsSummary`** (`app/src/components/results/results-summary.tsx`)
- Displays overall score as a large number with proficiency badge
- Shows total time, date completed, and question count
- Props: `overallScore`, `proficiencyLabel`, `totalTime`, `createdAt`

**`RadarChart`** (`app/src/components/results/radar-chart.tsx`)
- Wraps Recharts `RadarChart` component
- Displays 12-axis radar with competency labels
- Responsive container with `ResponsiveContainer`
- Props: `data: RadarDataPoint[]`

**`CompetencyBreakdown`** (`app/src/components/results/competency-breakdown.tsx`)
- Grid of cards, one per competency
- Each card shows score bar, level badge, and expand toggle for recommendations
- Props: `competencies: CompetencyBreakdownResponse[]`

**`LevelBadge`** (`app/src/components/results/level-badge.tsx`)
- Color-coded badge displaying proficiency level
- Colors: novice=slate, beginner=blue, intermediate=amber, advanced=green, expert=purple
- Props: `level: number`, `label: string`

**`GradingProgress`** (`app/src/components/results/grading-progress.tsx`)
- Shown while `grading_status` is not `"complete"`
- Displays progress bar and "X of Y answers graded" text
- Auto-polls grading-status endpoint every 3 seconds
- Props: `assessmentId: string`

### Data Fetching
Use TanStack Query hooks:

```typescript
// Fetch full results
const useResults = (assessmentId: string) =>
  useQuery({
    queryKey: ["results", assessmentId],
    queryFn: () => api.get(`/results/${assessmentId}`),
    enabled: !!assessmentId,
  });

// Poll grading status
const useGradingStatus = (assessmentId: string, enabled: boolean) =>
  useQuery({
    queryKey: ["grading-status", assessmentId],
    queryFn: () => api.get(`/results/${assessmentId}/grading-status`),
    refetchInterval: enabled ? 3000 : false,
  });
```

## Implementation Notes
- Recharts `RadarChart` requires data in `[{ subject, value, fullMark }]` format; transform `RadarDataPoint` accordingly
- Use `next/dynamic` with `ssr: false` for the radar chart to avoid SSR hydration issues with Recharts
- The breakdown endpoint should join `CompetencyScore` with `Competency` to include names and categories
- Recommendations can be static mappings per proficiency level initially; a future iteration could make them AI-generated
- The polling interval of 3 seconds balances responsiveness with server load; stop polling once `grading_status === "complete"`
- Use Radix UI `Progress` for score bars in competency cards

## Testing Strategy
- Unit tests for: `LevelBadge` renders correct color per level, `ResultsSummary` displays formatted time, `CompetencyBreakdown` renders all 12 cards, `GradingProgress` shows correct percentage
- Integration tests for: TanStack Query hooks return and cache data correctly, polling stops when grading completes, results page renders with mocked API data
- E2E tests for: full results page loads after completing a graded assessment, radar chart renders visible SVG, competency cards expand to show recommendations

## Acceptance Criteria
- [ ] Results page displays overall score, proficiency badge, and time taken
- [ ] Radar chart renders all 12 competency axes with correct scores
- [ ] Competency breakdown shows a card for each competency with score, level, and question stats
- [ ] `LevelBadge` displays correct color and label for each proficiency level
- [ ] Recommendations appear per competency based on proficiency level
- [ ] Grading progress component polls and auto-updates until grading is complete
- [ ] Polling stops when `grading_status` reaches `"complete"`
- [ ] Results page handles loading, error, and not-found states gracefully
- [ ] Radar chart is responsive and readable on mobile (375px)
- [ ] Charts respect `prefers-reduced-motion` media query
