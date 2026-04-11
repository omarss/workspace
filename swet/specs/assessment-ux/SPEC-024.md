# SPEC-024: Assessment Navigation

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-020
- SPEC-021

## Overview
Provides the UI for navigating between questions during an assessment. A sidebar displays all 100 question positions as compact, color-coded cells, allowing the user to jump to any question instantly. Sequential navigation (next/previous) and a "flag for review" toggle let users move through the assessment efficiently. Keyboard shortcuts accelerate navigation for power users. On mobile viewports, the sidebar collapses into a bottom sheet.

## Requirements

### Functional
1. A question sidebar displays 100 question position cells in a grid layout (10 columns x 10 rows). Each cell shows the question number (1-100).
2. Cells are color-coded by status:
   - **Unanswered**: neutral/muted background (e.g., `bg-muted`)
   - **Answered**: green/success background (e.g., `bg-green-100 dark:bg-green-900`)
   - **Flagged for review**: amber/warning background (e.g., `bg-amber-100 dark:bg-amber-900`)
   - **Current**: primary/ring indicator (e.g., `ring-2 ring-primary`)
   - A cell can be both answered and flagged (answered takes background color, flag is indicated by a small corner triangle or dot).
3. Clicking a cell navigates to that question immediately. The current question's response is auto-saved (SPEC-022) before navigation.
4. "Next" and "Previous" buttons are displayed below the question content area. "Previous" is disabled on question 1; "Next" is disabled on question 100 (replaced by "Finish Assessment" on question 100).
5. A "Flag for Review" toggle button allows the user to mark the current question. Flagged questions persist in the assessment store and are visible in the sidebar.
6. Keyboard shortcuts:
   - `ArrowRight` or `ArrowDown`: next question
   - `ArrowLeft` or `ArrowUp`: previous question
   - `f` or `F`: toggle flag on current question
   - Shortcuts are disabled when a textarea or input element has focus to avoid conflicts with typing.
7. A summary bar above or beside the sidebar shows counts: "X answered, Y flagged, Z remaining".
8. On viewports below `md` breakpoint, the sidebar is replaced by a collapsible bottom sheet. A trigger button shows the current question number and progress. Tapping it opens the bottom sheet with the same grid and summary.

### Non-Functional
1. Navigating between questions must feel instant (under 100ms perceived latency). Question content should be pre-rendered or cached so that switching does not trigger a loading state.
2. The sidebar must not cause layout shift when question statuses update. Cell dimensions are fixed.
3. Keyboard shortcuts must not interfere with browser defaults (no hijacking of Ctrl/Cmd combinations).
4. The bottom sheet on mobile must support swipe-to-dismiss and have a max height of 60vh to keep the question content partially visible.

## Technical Design

### Assessment Store (augmented)

Add to the existing assessment store (SPEC-014):

```tsx
interface AssessmentState {
  // ... existing fields

  currentQuestionIndex: number;
  flaggedQuestions: Set<string>;   // set of questionIds

  // Actions
  goToQuestion: (index: number) => void;
  nextQuestion: () => void;
  previousQuestion: () => void;
  toggleFlag: (questionId: string) => void;
}
```

`goToQuestion` triggers auto-save for the current question before updating `currentQuestionIndex` and calls `timerStore.switchQuestion()` to update per-question time tracking.

### Components

```
src/components/assessment/
  QuestionSidebar.tsx       # desktop sidebar with grid
  QuestionCell.tsx           # individual cell in the grid
  NavigationButtons.tsx      # next / previous / finish buttons
  FlagToggle.tsx             # flag for review button
  NavigationSummary.tsx      # answered / flagged / remaining counts
  MobileNavSheet.tsx         # bottom sheet for mobile
  useNavigationShortcuts.ts  # keyboard shortcut hook
```

#### QuestionSidebar

```tsx
interface QuestionSidebarProps {
  questions: { id: string; index: number }[];
  currentIndex: number;
  answeredIds: Set<string>;
  flaggedIds: Set<string>;
  onNavigate: (index: number) => void;
}
```

- Renders a `10x10` CSS grid of `QuestionCell` components.
- Wrapped in a `<nav aria-label="Question navigation">` for accessibility.
- On desktop (`md+`), rendered as a fixed-width sidebar (240px) to the left of the question content.

#### QuestionCell

```tsx
interface QuestionCellProps {
  number: number;
  status: 'unanswered' | 'answered' | 'flagged' | 'answered-flagged';
  isCurrent: boolean;
  onClick: () => void;
}
```

- Fixed dimensions (`w-8 h-8` or similar) to prevent layout shift.
- Uses `cva` (class-variance-authority) for variant-based styling.
- `aria-current="step"` when `isCurrent` is true.
- For `answered-flagged` status, background is green with a small amber triangle in the top-right corner via a CSS pseudo-element.

#### NavigationButtons

```tsx
interface NavigationButtonsProps {
  currentIndex: number;
  totalCount: number;
  onPrevious: () => void;
  onNext: () => void;
  onFinish: () => void;
}
```

- "Previous" button: disabled at index 0.
- "Next" button: visible for indices 0-98.
- "Finish Assessment" button: replaces "Next" at index 99. Opens a confirmation dialog (via `@radix-ui/react-dialog`) showing the summary (answered, flagged, unanswered counts) before submission.

#### FlagToggle

- A toggle button with a flag icon (from `lucide-react`).
- `aria-pressed` reflects the flagged state.
- Visual: outlined flag when unflagged, filled amber flag when flagged.

#### useNavigationShortcuts

```tsx
function useNavigationShortcuts(
  onNext: () => void,
  onPrevious: () => void,
  onToggleFlag: () => void
): void
```

- Registers a `keydown` listener on `document`.
- Checks `event.target`: if the target is a `<textarea>`, `<input>`, or has `contentEditable`, the shortcut is suppressed.
- Handles `ArrowRight`, `ArrowDown` (next), `ArrowLeft`, `ArrowUp` (previous), `f`/`F` (flag toggle).
- Calls `event.preventDefault()` only for handled keys to avoid interfering with other shortcuts.

#### MobileNavSheet

- Uses `@radix-ui/react-dialog` styled as a bottom sheet (positioned at bottom, rounded top corners, max-height 60vh, scrollable).
- Trigger button is a compact bar showing "Question {n} of 100" with a chevron-up icon.
- Inside the sheet: `NavigationSummary` + `QuestionSidebar` grid (same component, responsive sizing).
- Dismissible via swipe-down gesture (CSS `touch-action` + pointer event handling) or tapping outside.

### Layout Integration

The assessment page layout at `md+` viewports:

```
+--------------------+------------------------------------+
| QuestionSidebar    | QuestionRenderer                   |
| (fixed, 240px)     | (flex-1)                           |
|                    |                                    |
|                    | NavigationButtons                  |
+--------------------+------------------------------------+
```

At viewports below `md`:

```
+--------------------------------------------+
| QuestionRenderer                           |
|                                            |
| NavigationButtons                          |
+--------------------------------------------+
| MobileNavSheet trigger bar                 |
+--------------------------------------------+
```

## Implementation Notes
- The `Set<string>` for `flaggedQuestions` in Zustand should be stored as an array internally (since Zustand's `persist` middleware cannot serialize `Set`), with a selector that converts it to a `Set` for consumers.
- `goToQuestion` should be debounce-proof: if the user rapidly clicks through cells, only the final destination should trigger a full save + timer switch. Use `requestAnimationFrame` or a microtask to batch rapid navigations.
- The finish confirmation dialog is a critical UX gate. It must clearly show how many questions are unanswered and flagged so the user can make an informed decision.
- Keyboard shortcuts are deliberately simple (single keys) for discoverability. A small tooltip or help text ("Press F to flag") can be shown near the flag button.

## Testing Strategy
- **Unit tests (Vitest + Testing Library):** Render `QuestionSidebar` with mixed statuses, verify correct CSS classes per cell. Click a cell, verify `onNavigate` is called with the correct index.
- **Unit tests (Vitest + Testing Library):** Render `QuestionCell` for each status variant, snapshot the class list for regression.
- **Unit tests (Vitest + Testing Library):** Render `NavigationButtons` at index 0 (Previous disabled), index 50 (both enabled), index 99 (Finish shown). Verify button states.
- **Unit tests (Vitest):** Test `useNavigationShortcuts`: dispatch keyboard events, verify callbacks are invoked. Dispatch from a textarea target, verify callbacks are not invoked.
- **Unit tests (Vitest + Testing Library):** Render `FlagToggle`, verify aria-pressed state toggles on click.
- **Integration tests (Vitest):** Mount the full navigation layout with a mock assessment store. Navigate via sidebar, verify `currentQuestionIndex` updates. Flag a question, verify it appears flagged in the sidebar.
- **E2E tests (Playwright):** Complete assessment navigation flow: jump to question 50 via sidebar, flag it, use arrow keys to navigate to 51, verify sidebar reflects all changes. Test at mobile viewport (375px) with bottom sheet interaction.
- **Accessibility (Playwright):** Run axe-core on the sidebar and navigation buttons, assert zero violations. Verify focus management: after clicking a cell, focus moves to the question content area.

## Acceptance Criteria
- [ ] Sidebar displays 100 cells in a 10x10 grid with correct color coding per status
- [ ] Clicking a cell navigates to that question and auto-saves the current response
- [ ] Next/Previous buttons work correctly with proper disabled states at boundaries
- [ ] "Finish Assessment" button appears at question 100 with a confirmation dialog showing summary counts
- [ ] Flag toggle marks/unmarks the current question and updates the sidebar cell
- [ ] Keyboard shortcuts (arrows for nav, F for flag) work when no text input is focused
- [ ] Keyboard shortcuts are suppressed when textarea or input has focus
- [ ] Summary bar shows correct answered, flagged, and remaining counts
- [ ] Mobile bottom sheet opens/closes correctly and contains the same navigation grid
- [ ] Navigation between questions is perceived as instant (under 100ms)
- [ ] Sidebar cells have fixed dimensions and do not cause layout shift on status changes
- [ ] All navigation elements pass axe-core accessibility audit
