# SPEC-021: Assessment Timer and Progress

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-014

## Overview
Provides real-time timing and progress tracking during an assessment. A dedicated Zustand store manages timer state independently from the main assessment store to prevent every 1-second tick from re-rendering question content. The system tracks per-question time spent, displays overall progress, and optionally enforces a time limit with visual warnings.

## Requirements

### Functional
1. A global assessment timer counts elapsed seconds from the moment the assessment starts. The timer ticks at a 1-second interval via `setInterval`.
2. Per-question time tracking records how many seconds the user spends on each question. When the user navigates to a different question, the elapsed time for the previous question is accumulated.
3. An overall progress bar shows the fraction of questions answered out of the total (e.g., 23 answered / 100 total). The bar uses `@radix-ui/react-progress`.
4. A question counter displays the current position in text form (e.g., "23 / 100").
5. When the assessment has an optional time limit, a countdown timer is displayed instead of (or alongside) the elapsed timer.
6. Visual warnings appear at 5 minutes remaining (amber indicator) and 1 minute remaining (red indicator with pulse animation).
7. The timer pauses automatically when the browser tab loses visibility (`document.visibilitychange` event) or the window loses focus (`window.blur`). It resumes on visibility restoration or `window.focus`.
8. When the countdown reaches zero, the assessment auto-submits (delegates to the assessment store's submit action).

### Non-Functional
1. Timer state updates must not cause re-renders in question renderer components. Only timer display components subscribe to the timer store.
2. The 1-second interval must be cleaned up on unmount to prevent memory leaks.
3. Timer drift must be corrected by anchoring to `Date.now()` rather than accumulating interval counts.
4. Progress bar transitions must be animated (CSS transition on width, 200ms ease).

## Technical Design

### Zustand Store

```
src/stores/timer-store.ts
```

```tsx
interface PerQuestionTime {
  [questionId: string]: number; // seconds spent
}

interface TimerState {
  // State
  startedAt: number | null;          // Date.now() when started
  elapsed: number;                   // total seconds elapsed
  currentQuestionId: string | null;
  currentQuestionStart: number | null; // Date.now() when navigated to this question
  perQuestionTime: PerQuestionTime;
  timeLimit: number | null;          // seconds, null = unlimited
  isPaused: boolean;
  isExpired: boolean;

  // Actions
  start: (timeLimit: number | null) => void;
  pause: () => void;
  resume: () => void;
  tick: () => void;
  switchQuestion: (questionId: string) => void;
  reset: () => void;
}
```

**Tick logic:** On each `tick()`, compute `elapsed = Math.floor((Date.now() - startedAt) / 1000) - totalPausedDuration`. This avoids drift from imprecise `setInterval` timing. A `totalPausedDuration` accumulator tracks time spent paused.

**Pause/resume via visibility:** A single `useEffect` in a `<TimerManager>` component registers `visibilitychange` and `blur`/`focus` listeners and calls `pause()` / `resume()` accordingly.

### Components

```
src/components/assessment/
  TimerManager.tsx       # headless: setInterval + visibility listeners
  TimerDisplay.tsx       # renders elapsed or countdown
  ProgressBar.tsx        # progress bar + question counter
  TimerWarning.tsx       # warning overlay at 5min / 1min
```

#### TimerManager

- Headless component (renders `null`). Owns the `setInterval` lifecycle.
- Calls `timerStore.tick()` every 1000ms.
- Registers `visibilitychange` and `blur/focus` event listeners.
- On unmount, clears interval and removes listeners.

#### TimerDisplay

```tsx
interface TimerDisplayProps {
  className?: string;
}
```

- Subscribes to `elapsed`, `timeLimit`, and `isExpired` from the timer store using Zustand selectors.
- Formats time as `HH:MM:SS` for elapsed or countdown.
- Applies warning styles when remaining time crosses 5min / 1min thresholds.

#### ProgressBar

```tsx
interface ProgressBarProps {
  answeredCount: number;
  totalCount: number;
}
```

- Uses `@radix-ui/react-progress` with a CSS transition on the indicator width.
- Displays `"{answeredCount} / {totalCount}"` as companion text.

#### TimerWarning

- Conditionally renders an amber banner at 5min remaining and a red pulsing banner at 1min remaining.
- At 0 remaining, triggers `assessmentStore.submit()`.

## Implementation Notes
- The timer store is intentionally separate from the assessment store. Components that render question content should never subscribe to the timer store. Only `TimerDisplay`, `TimerWarning`, and `TimerManager` subscribe.
- Use `zustand`'s selector pattern (`useTimerStore(state => state.elapsed)`) to ensure minimal re-renders; avoid subscribing to the entire store object.
- `setInterval` in browsers is throttled when the tab is backgrounded. The visibility-based pause handles this gracefully: when the tab returns to foreground, `resume()` recalculates from `Date.now()`, so no time is lost or double-counted.
- Per-question time data is useful for post-assessment analytics (SPEC-032) and is included in the assessment submission payload.

## Testing Strategy
- **Unit tests (Vitest):** Test timer store actions in isolation: `start`, `tick`, `pause`, `resume`, `switchQuestion`. Mock `Date.now()` via `vi.spyOn` to control time progression.
- **Unit tests (Vitest + Testing Library):** Render `TimerDisplay` with controlled store state, verify formatted output and warning styles at various remaining-time thresholds.
- **Unit tests:** Render `ProgressBar` with various `answeredCount` / `totalCount` values, verify accessible progress value and text.
- **Integration tests (Vitest):** Mount `TimerManager` and verify it calls `tick` on interval and `pause`/`resume` on simulated visibility changes.
- **E2E tests (Playwright):** Start an assessment with a short time limit (e.g., 10 seconds), verify countdown display, warning appearance, and auto-submit at expiration.

## Acceptance Criteria
- [ ] Timer starts counting when assessment begins and displays elapsed time in `HH:MM:SS` format
- [ ] Per-question time is tracked and accumulated correctly across question navigations
- [ ] Progress bar reflects the number of answered questions with animated transitions
- [ ] Question counter displays current answered count out of total (e.g., "23 / 100")
- [ ] Countdown timer displays remaining time when a time limit is set
- [ ] Amber warning appears at 5 minutes remaining
- [ ] Red pulsing warning appears at 1 minute remaining
- [ ] Timer pauses on tab hidden / window blur and resumes on visibility restore / focus
- [ ] Auto-submit triggers when countdown reaches zero
- [ ] Timer ticks do not cause re-renders in question renderer components
- [ ] No memory leaks: interval and listeners are cleaned up on unmount
