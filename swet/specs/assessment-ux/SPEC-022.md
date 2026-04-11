# SPEC-022: Auto-save and Pause/Resume

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-014
- SPEC-020

## Overview
Ensures no user work is lost during an assessment. Responses are auto-saved to the server via debounced mutations, with different debounce strategies for text-based and selection-based inputs. A visible save indicator communicates current save status. Users can pause an assessment, which stops the timer and persists the full state to sessionStorage, and resume exactly where they left off. Failed saves are queued and retried automatically when connectivity is restored.

## Requirements

### Functional
1. Text-based responses (short answer, code review, debugging fields, design prompt fields) auto-save after 800ms of inactivity (debounced via `use-debounce`).
2. MCQ selections auto-save immediately on change (no debounce).
3. A save indicator is always visible during an active assessment, showing one of three states: **Saved** (check icon, muted), **Saving...** (spinner), or **Error** (warning icon, red, with retry option).
4. A "Pause Assessment" button stops the timer (SPEC-021), persists the current assessment state (responses, current question index, timer state) to `sessionStorage` via Zustand's `persist` middleware, and navigates to a paused confirmation screen.
5. On the paused screen, a "Resume" button restores the state from `sessionStorage`, re-initializes the timer, and navigates back to the last active question.
6. If the browser is closed while paused, the session can be resumed as long as `sessionStorage` is intact (same tab lineage). A server-side assessment status of `in_progress` allows the server to also serve the last saved responses as a fallback.
7. Failed save requests are enqueued in an in-memory queue. When the browser regains connectivity (detected via `navigator.onLine` and the `online` window event), the queue is drained in order.
8. If the save queue grows beyond 10 items, older entries for the same question are deduplicated (only the latest response per question is kept).

### Non-Functional
1. Auto-save must not block or freeze the UI; all mutations run asynchronously.
2. The save indicator must update within 100ms of state change (saved/saving/error).
3. Persisted sessionStorage data must not exceed 2MB (well within the 5MB limit). Large code review responses should be truncated at 10,000 characters per field.
4. Retry logic must use exponential backoff: 1s, 2s, 4s, capped at 30s, with a maximum of 5 retries per save before surfacing a persistent error to the user.

## Technical Design

### API Endpoints

```
POST /api/v1/assessments/{assessment_id}/answers
```

Request body:
```json
{
  "question_id": "uuid",
  "response_text": "string | null",
  "selected_option": "A | B | C | D | null",
  "time_spent_seconds": 45,
  "is_auto_saved": true
}
```

Response: `200 OK` with `{ id: string, saved: true }` or appropriate error.

### Auto-save Hook

```
src/hooks/use-auto-save.ts
```

```tsx
function useAutoSave(
  assessmentId: string,
  questionId: string,
  value: ResponseValue,
  format: QuestionFormat
): { status: 'saved' | 'saving' | 'error'; retry: () => void }
```

- Uses `@tanstack/react-query` `useMutation` for the POST call.
- For text formats, wraps the mutation trigger in `useDebouncedCallback` from `use-debounce` with 800ms delay.
- For `mcq` format, calls the mutation immediately on every `value` change.
- Tracks `status` derived from the mutation state (`idle` / `isPending` / `isSuccess` / `isError`).

### Save Queue (offline resilience)

```
src/lib/save-queue.ts
```

```tsx
interface QueuedSave {
  assessmentId: string;
  questionId: string;
  value: ResponseValue;
  timeSpent: number;
  retries: number;
  nextRetryAt: number;
}
```

- On mutation error and `!navigator.onLine`, the failed payload is pushed to the queue.
- A `useOnlineStatus` hook (wrapping `navigator.onLine` + `online`/`offline` events) triggers queue drain when connectivity returns.
- Drain processes items sequentially to preserve ordering. Each successful drain removes the item; failures re-enqueue with incremented retry count and exponential backoff delay.
- Deduplication: before enqueuing, remove any existing entry with the same `questionId`.

### Pause/Resume (Zustand Persist)

```
src/stores/assessment-store.ts  (augmented)
```

- Add `persist` middleware from `zustand/middleware` scoped to `sessionStorage`.
- Persisted keys: `responses`, `currentQuestionIndex`, `questionOrder`, `assessmentId`, `status`.
- Timer state from `timer-store.ts` is persisted separately (elapsed, perQuestionTime, isPaused, timeLimit).
- On pause: set `status = 'paused'` and call `timerStore.pause()`.
- On resume: hydrate from sessionStorage, set `status = 'in_progress'`, and call `timerStore.resume()`.

### Components

```
src/components/assessment/
  SaveIndicator.tsx          # visual saved/saving/error indicator
  PauseButton.tsx            # triggers pause flow
  PauseScreen.tsx            # confirmation screen with resume button
```

#### SaveIndicator

- Subscribes to the auto-save hook's status.
- Renders a small inline indicator (icon + text) positioned in the assessment header bar.
- On error state, includes a "Retry" button that calls `retry()`.

## Implementation Notes
- The 800ms debounce for text responses balances responsiveness with server load. If users type continuously for 30 seconds, only one save fires (at 800ms after the last keystroke), not 30+.
- `sessionStorage` was chosen over `localStorage` deliberately: it scopes to the tab, preventing stale state from leaking across tabs. If the user opens a new assessment in another tab, it gets its own session.
- Server-side `in_progress` status acts as a safety net. If sessionStorage is cleared (e.g., browser crash), the resume flow falls back to fetching the last server-saved responses via `GET /api/v1/assessments/{id}`.
- The save queue is in-memory only. If the page is fully unloaded while offline with unsaved responses, those responses are lost. This is an acceptable trade-off since `sessionStorage` persist captures the response values themselves, and they will be re-saved on resume.

## Testing Strategy
- **Unit tests (Vitest):** Test `useAutoSave` hook: mock `useMutation`, verify debounce timing for text (800ms) vs. immediate for MCQ. Use `vi.useFakeTimers()`.
- **Unit tests (Vitest):** Test `save-queue.ts`: enqueue, dedup, drain sequentially, exponential backoff calculation, max retry cap.
- **Unit tests (Vitest + Testing Library):** Render `SaveIndicator` with each status, verify correct icon and text. Verify retry button calls retry on error state.
- **Integration tests (Vitest):** Mount a renderer with `useAutoSave`, type into a textarea, advance timers by 800ms, assert PATCH request fired via MSW handler.
- **Integration tests (Vitest):** Simulate offline (mock `navigator.onLine = false`), trigger a save, verify it is queued. Set `navigator.onLine = true` and dispatch `online` event, verify queued save is retried.
- **E2E tests (Playwright):** Start assessment, answer a question, reload the page, verify response is preserved via server fetch. Pause, verify paused screen, resume, verify question and timer state restored.

## Acceptance Criteria
- [ ] Text responses auto-save 800ms after the user stops typing
- [ ] MCQ selections auto-save immediately on change
- [ ] Save indicator displays "Saved", "Saving...", or "Error" accurately
- [ ] Error state shows a retry button that re-attempts the failed save
- [ ] Pausing stops the timer and navigates to the pause screen
- [ ] Resuming restores exact state: current question, all responses, timer elapsed time
- [ ] Server is notified of pause/resume status changes
- [ ] Failed saves are queued when offline and retried when connectivity returns
- [ ] Queue deduplicates entries per question (only latest response kept)
- [ ] Retry uses exponential backoff capped at 30 seconds with max 5 retries
- [ ] sessionStorage persisted data does not exceed 2MB
- [ ] If sessionStorage is unavailable on resume, fallback to server-saved responses works
