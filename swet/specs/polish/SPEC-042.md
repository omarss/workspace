# SPEC-042: Accessibility

## Status
Draft

## Priority
P2

## Dependencies
- SPEC-020 (Question renderer components)
- SPEC-033 (Results visualization)

## Overview
Ensure the SWET platform meets WCAG 2.1 AA compliance across all interactive surfaces, with particular attention to the assessment-taking experience (timed interactions, code editors, question navigation) and results visualization (charts, dynamic content). Accessibility is not an afterthought but a quality baseline that enables all users to complete assessments and review results effectively.

## Requirements

### Functional
1. All interactive elements (buttons, links, form inputs, radio groups, tabs) must be fully operable via keyboard alone
2. Implement logical focus management during question navigation:
   - When navigating to a new question, focus moves to the question title
   - When opening a modal/dialog, focus is trapped within it
   - When closing a modal, focus returns to the triggering element
3. Add ARIA labels and roles to all custom components:
   - Assessment timer: `role="timer"` with `aria-live="polite"` for periodic announcements (every 5 minutes and final minute)
   - Progress bar: `role="progressbar"` with `aria-valuenow`, `aria-valuemin`, `aria-valuemax`
   - Radar chart: `role="img"` with `aria-label` describing the data, plus a visually hidden data table alternative
   - Code editor: `role="textbox"` with `aria-label` describing the expected input
4. Provide screen reader announcements via `aria-live` regions for:
   - Answer auto-save confirmation
   - Question navigation (current position)
   - Timer warnings (5 minutes remaining, 1 minute remaining)
   - Grading progress updates
5. Ensure all color usage passes WCAG AA contrast ratios:
   - Normal text: minimum 4.5:1 contrast ratio
   - Large text (18px+ or 14px+ bold): minimum 3:1
   - UI components and graphical objects: minimum 3:1
6. Support `prefers-reduced-motion` media query:
   - Disable chart animations
   - Disable transition effects on question navigation
   - Replace animated progress indicators with static ones
7. Provide visible focus indicators on all interactive elements (not browser defaults; custom focus rings that meet 3:1 contrast)
8. Ensure all form errors are associated with their inputs via `aria-describedby` and announced to screen readers

### Non-Functional
1. All pages must score 90+ on Lighthouse Accessibility audit
2. No WCAG 2.1 AA violations detected by axe-core automated testing
3. Assessment flow must be completable using only keyboard and screen reader
4. Focus management changes must not cause unexpected context changes

## Technical Design

### Focus Management Utility
Add `app/src/lib/hooks/use-focus-management.ts`:

```typescript
export function useFocusOnMount(ref: RefObject<HTMLElement>) {
  useEffect(() => {
    ref.current?.focus();
  }, [ref]);
}

export function useFocusTrap(containerRef: RefObject<HTMLElement>) {
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const focusableElements = container.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const first = focusableElements[0] as HTMLElement;
    const last = focusableElements[focusableElements.length - 1] as HTMLElement;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key !== "Tab") return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    container.addEventListener("keydown", handleKeyDown);
    first?.focus();
    return () => container.removeEventListener("keydown", handleKeyDown);
  }, [containerRef]);
}
```

### Live Region Component
Add `app/src/components/ui/live-region.tsx`:

```typescript
interface LiveRegionProps {
  message: string;
  politeness?: "polite" | "assertive";
}

export function LiveRegion({ message, politeness = "polite" }: LiveRegionProps) {
  return (
    <div
      role="status"
      aria-live={politeness}
      aria-atomic="true"
      className="sr-only"
    >
      {message}
    </div>
  );
}
```

### Timer Accessibility
Update the assessment timer component:

```typescript
function AssessmentTimer({ timeRemaining }: { timeRemaining: number }) {
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    if (timeRemaining === 300) setAnnouncement("5 minutes remaining");
    if (timeRemaining === 60) setAnnouncement("1 minute remaining");
    if (timeRemaining === 0) setAnnouncement("Time is up");
  }, [timeRemaining]);

  return (
    <>
      <div role="timer" aria-label={`${formatTime(timeRemaining)} remaining`}>
        {formatTime(timeRemaining)}
      </div>
      <LiveRegion message={announcement} politeness="assertive" />
    </>
  );
}
```

### Radar Chart Accessibility
Provide a hidden data table alongside the SVG chart:

```typescript
function AccessibleRadarChart({ data }: { data: RadarDataPoint[] }) {
  return (
    <div>
      <div role="img" aria-label="Competency scores radar chart">
        <RadarChart data={data} />
      </div>
      {/* Hidden table for screen readers */}
      <table className="sr-only">
        <caption>Competency Scores</caption>
        <thead>
          <tr><th>Competency</th><th>Score</th></tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.competency}>
              <td>{d.competency}</td>
              <td>{d.score} out of 100</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

### Skip Navigation
Add a skip link at the top of the layout:

```typescript
// app/src/components/layout/header.tsx
<a
  href="#main-content"
  className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:p-2 focus:bg-background focus:border focus:rounded"
>
  Skip to main content
</a>
```

### Reduced Motion Support
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

### Custom Focus Styles
```css
/* Global focus styles in app/src/app/globals.css */
:focus-visible {
  outline: 2px solid hsl(var(--ring));
  outline-offset: 2px;
  border-radius: 2px;
}
```

## Implementation Notes
- Radix UI primitives (Dialog, DropdownMenu, RadioGroup, Tabs) already handle many ARIA patterns correctly; verify rather than re-implement
- The `sr-only` utility class is already available via Tailwind CSS for visually hidden content
- Test with multiple screen readers: NVDA (Windows), VoiceOver (macOS), Orca (Linux)
- The assessment timer `aria-live` should use `"assertive"` only for critical warnings (1 minute, time up) and `"polite"` for periodic updates to avoid overwhelming screen reader users
- Color choices for proficiency level badges must be verified against both light and dark backgrounds
- Do not rely solely on color to convey information (always pair with text labels or icons)

## Testing Strategy
- Unit tests for: `LiveRegion` renders with correct ARIA attributes, focus trap cycles focus correctly, skip link navigates to main content, reduced motion styles are applied
- Integration tests for: axe-core automated accessibility audit on every page (assessment, results, history) with zero violations, keyboard navigation through complete assessment flow, focus returns to correct element after dialog close
- E2E tests for: complete assessment using only keyboard inputs, screen reader announces timer warnings, radar chart data table is readable by screen reader, Lighthouse Accessibility score >= 90

## Acceptance Criteria
- [ ] All interactive elements are keyboard accessible with visible focus indicators
- [ ] Tab order follows a logical reading sequence on all pages
- [ ] Focus moves to question title when navigating between questions
- [ ] Focus is trapped in modals/dialogs and returns on close
- [ ] Assessment timer announces warnings at 5 minutes and 1 minute via `aria-live`
- [ ] Progress bar has correct `role` and `aria-value*` attributes
- [ ] Radar chart has a hidden data table alternative for screen readers
- [ ] All text meets WCAG AA contrast ratios (4.5:1 for normal, 3:1 for large)
- [ ] Animations are disabled when `prefers-reduced-motion` is set
- [ ] Skip navigation link is present and functional
- [ ] Form errors are associated with inputs via `aria-describedby`
- [ ] axe-core reports zero AA violations on all pages
- [ ] Lighthouse Accessibility score is 90+ on all pages
