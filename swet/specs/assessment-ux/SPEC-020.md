# SPEC-020: Question Renderer Components

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-015

## Overview
A set of five specialized React components that render different question formats during an assessment, plus a dispatcher component that selects the correct renderer based on the question's format. Each renderer is a controlled component accepting `value` and `onChange` props so that parent state management (Zustand / React Query) owns the response data. All renderers share consistent layout patterns, accessibility attributes, and responsive behavior.

## Requirements

### Functional
1. **QuestionRenderer dispatcher** receives a `format` prop (enum: `mcq`, `code_review`, `debugging`, `short_answer`, `design_prompt`) and delegates to the matching renderer. Unknown formats render an error fallback.
2. **MCQRenderer** displays the question body as Markdown (via `react-markdown` with `remark-gfm`) and presents exactly four options as a radio group (via `@radix-ui/react-radio-group`). Selecting an option calls `onChange` with the selected option key.
3. **CodeReviewRenderer** displays a horizontally split pane: left side shows a code snippet with syntax highlighting (via Shiki), right side shows a textarea for the review response. On viewports narrower than `md` breakpoint, the layout stacks vertically (code on top).
4. **DebuggingRenderer** displays a scenario description, a collapsible section for logs/error output, and three structured response fields: root cause (textarea), fix (textarea), and prevention (textarea). Collapsible section uses native `<details>/<summary>` for zero-JS progressive enhancement.
5. **ShortAnswerRenderer** displays a Markdown-rendered prompt followed by a large textarea. A live character count is shown below the textarea with guidance text (e.g., "Aim for 200-500 characters"). No hard limit enforced, only guidance.
6. **DesignPromptRenderer** displays a scenario description followed by four labeled response areas: Architecture, Components, Trade-offs, and Scalability. Each area is an independent textarea.
7. All renderers display the question number and competency tag above the question body.

### Non-Functional
1. Each renderer must render its initial frame in under 50ms (no heavy computation on mount).
2. Shiki highlighting in CodeReviewRenderer must load the language grammar lazily to avoid blocking initial render.
3. All interactive elements must be keyboard-navigable and include appropriate ARIA labels.
4. Components must be fully responsive from 320px to 1440px viewport width.
5. Renderer `format` values must match the canonical enum from SPEC-015 exactly (`mcq`, `code_review`, `debugging`, `short_answer`, `design_prompt`).

## Technical Design

### Components

```
src/components/assessment/
  QuestionRenderer.tsx        # dispatcher
  renderers/
    MCQRenderer.tsx
    CodeReviewRenderer.tsx
    DebuggingRenderer.tsx
    ShortAnswerRenderer.tsx
    DesignPromptRenderer.tsx
  QuestionHeader.tsx           # shared: question number + competency tag
```

#### QuestionRenderer (dispatcher)

```tsx
interface QuestionRendererProps {
  question: Question;          // from SPEC-015 types
  value: ResponseValue;        // union type varying by format
  onChange: (value: ResponseValue) => void;
}
```

Uses a `switch` on `question.format` to render the correct child. Wraps output in a consistent `<section>` with `<QuestionHeader>`.

#### MCQRenderer

```tsx
interface MCQRendererProps {
  body: string;                // markdown
  options: { key: string; text: string }[];
  value: string | null;        // selected option key
  onChange: (key: string) => void;
}
```

- Renders `body` via `<ReactMarkdown remarkPlugins={[remarkGfm]}>`.
- Renders options via `<RadioGroup.Root>` / `<RadioGroup.Item>`, each wrapped in a styled label card that highlights on selection.

#### CodeReviewRenderer

```tsx
interface CodeReviewRendererProps {
  body: string;                // markdown context
  code: string;                // source code to review
  language: string;            // language identifier for Shiki
  value: string;               // review text
  onChange: (value: string) => void;
}
```

- Code pane uses `shiki.codeToHtml()` called inside a `useMemo` with `React.use()` for the async grammar load, wrapped in `<Suspense>` with a skeleton fallback.
- Split layout via CSS `grid-template-columns: 1fr 1fr` at `md+`, single column below.

#### DebuggingRenderer

```tsx
interface DebuggingValue {
  rootCause: string;
  fix: string;
  prevention: string;
}

interface DebuggingRendererProps {
  scenario: string;            // markdown
  logs: string;                // preformatted log output
  value: DebuggingValue;
  onChange: (value: DebuggingValue) => void;
}
```

- Logs rendered inside `<details><summary>Logs & Errors</summary><pre>...</pre></details>`.
- Each textarea field has a descriptive label.

#### ShortAnswerRenderer

```tsx
interface ShortAnswerRendererProps {
  prompt: string;              // markdown
  guidance: { min: number; max: number }; // character count guidance
  value: string;
  onChange: (value: string) => void;
}
```

- Character count indicator changes color: muted when under min, default when within range, warning when over max.

#### DesignPromptRenderer

```tsx
interface DesignPromptValue {
  architecture: string;
  components: string;
  tradeoffs: string;
  scalability: string;
}

interface DesignPromptRendererProps {
  scenario: string;            // markdown
  value: DesignPromptValue;
  onChange: (value: DesignPromptValue) => void;
}
```

- Four labeled textareas, each with a short helper subtitle explaining what to include.

### QuestionHeader

```tsx
interface QuestionHeaderProps {
  questionNumber: number;
  total: number;
  competency: string;
}
```

- Renders `"Question {questionNumber} of {total}"` and a competency badge.

## Implementation Notes
- Shiki must be imported dynamically (`import('shiki')`) and its highlighter instance cached at module scope to avoid re-initialization across question navigations.
- `react-markdown` is a relatively heavy component; wrap each Markdown block in `React.memo` keyed on the markdown string to prevent unnecessary re-renders when only the response value changes.
- The `ResponseValue` union type should use a discriminated union keyed by format so TypeScript narrows correctly inside each renderer.
- All textareas should use `rows` sizing with `resize: vertical` to keep the layout stable.

## Testing Strategy
- **Unit tests (Vitest + Testing Library):** Render each renderer with mock props, verify output structure, simulate interactions (radio select, textarea input), assert `onChange` called with correct value.
- **Unit test:** QuestionRenderer dispatcher renders the correct child for each format and renders the error fallback for an unknown format.
- **Integration tests (Vitest):** Mount QuestionRenderer connected to a mock Zustand store, verify two-way data binding (store -> renderer -> onChange -> store).
- **Visual regression (Playwright):** Screenshot each renderer at 375px and 1280px widths to catch layout regressions.
- **Accessibility (Playwright):** Run `axe-core` audit on each renderer, assert zero violations.

## Acceptance Criteria
- [ ] QuestionRenderer correctly dispatches to all five renderers based on `format`
- [ ] MCQRenderer renders Markdown body and four radio options; selecting an option calls `onChange`
- [ ] CodeReviewRenderer shows syntax-highlighted code and a review textarea; layout splits at `md` breakpoint
- [ ] DebuggingRenderer shows collapsible logs and three structured response fields
- [ ] ShortAnswerRenderer shows Markdown prompt, textarea, and live character count with guidance
- [ ] DesignPromptRenderer shows scenario and four labeled response textareas
- [ ] All renderers are fully controlled via `value` / `onChange`
- [ ] All renderers pass axe-core accessibility audit with zero violations
- [ ] Shiki grammar loads lazily without blocking initial render
- [ ] Components render correctly from 320px to 1440px viewport width
