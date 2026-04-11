# SPEC-041: Error Handling and Resilience

## Status
Draft

## Priority
P2

## Dependencies
- SPEC-031 (AI grading for open-ended questions)

## Overview
Harden the SWET platform against failures in external services (Claude API), network disruptions, and transient errors. This spec introduces a circuit breaker for the Claude API, offline support for answer drafts, retry queues for failed operations, and graceful degradation patterns so that the user experience remains functional even when components fail.

## Requirements

### Functional
1. Implement a circuit breaker for Claude API calls (question generation and AI grading) with three states:
   - **Closed** (normal): requests pass through to Claude
   - **Open** (tripped): requests fail fast without calling Claude; return fallback response
   - **Half-open** (probing): allow one request through to test recovery
2. When the circuit is open during question generation, serve questions from the cached question pool instead of generating new ones
3. When the circuit is open during AI grading, queue answers for later grading and notify the user that grading is delayed
4. Implement offline support on the frontend:
   - Detect online/offline status using a `useOnlineStatus` hook
   - When offline, save answer drafts to IndexedDB via a `draftStore`
   - When connectivity is restored, sync all pending drafts to the backend
   - Show an offline indicator banner in the UI
5. Implement a retry queue for failed backend API calls:
   - Auto-retry failed submissions (answers, assessment completion) with exponential backoff
   - Maximum 3 retries before surfacing the error to the user
6. Provide graceful degradation for non-critical features:
   - If Recharts fails to load, show a text-based score table instead of the radar chart
   - If Shiki fails to load, render code in a plain `<pre>` block

### Non-Functional
1. Circuit breaker must trip after 5 consecutive failures within 60 seconds
2. Circuit breaker recovery probe interval: 30 seconds
3. Offline-saved drafts must persist across browser sessions (IndexedDB, not sessionStorage)
4. Draft sync on reconnect must complete within 5 seconds for up to 100 saved answers
5. Error messages shown to users must be actionable (not raw HTTP errors or stack traces)

## Technical Design

### Backend: Circuit Breaker

Add `src/scoring/circuit_breaker.py`:

```python
import time
from enum import Enum

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        failure_window: float = 60.0,
    ):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_window = failure_window

    async def call(self, func, *args, **kwargs):
        """Execute func through the circuit breaker."""
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitOpenError("Claude API circuit is open")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
```

Inject `CircuitBreaker` as a dependency into the AI grader and question generator services.

### Backend: Retry Queue

Add `src/scoring/retry_queue.py`:

```python
class RetryQueue:
    """In-memory queue for failed grading tasks with persistence fallback."""

    async def enqueue(self, task: GradingTask) -> None:
        """Add a failed grading task to the retry queue."""

    async def process(self) -> None:
        """Process all queued tasks with exponential backoff."""

    async def get_pending_count(self) -> int:
        """Return count of tasks awaiting retry."""
```

Register a periodic background task (via FastAPI lifespan or `asyncio.create_task`) that processes the retry queue every 60 seconds.

### Frontend: Offline Support

**`useOnlineStatus` hook** (`app/src/lib/hooks/use-online-status.ts`):
```typescript
export function useOnlineStatus(): boolean {
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  useEffect(() => {
    const onOnline = () => setIsOnline(true);
    const onOffline = () => setIsOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  return isOnline;
}
```

**`draftStore`** (`app/src/lib/stores/draft-store.ts`):
```typescript
// Uses IndexedDB via idb library for persistent draft storage
interface DraftAnswer {
  assessmentId: string;
  questionId: string;
  responseText: string | null;
  selectedOption: string | null;
  timeSpentSeconds: number;
  savedAt: number; // timestamp
}

export const draftStore = {
  save: async (draft: DraftAnswer) => { ... },
  getAll: async (assessmentId: string) => DraftAnswer[] { ... },
  delete: async (assessmentId: string, questionId: string) => { ... },
  sync: async (assessmentId: string) => { ... },  // POST all drafts to API
};
```

**Offline Banner** (`app/src/components/layout/offline-banner.tsx`):
- Fixed banner at the top of the viewport when offline
- Text: "You're offline. Your answers are saved locally and will sync when you reconnect."
- Auto-dismisses 3 seconds after connectivity is restored

### Frontend: Graceful Degradation

**Chart Fallback:**
```typescript
const RadarChart = dynamic(
  () => import("./radar-chart").catch(() => import("./radar-chart-fallback")),
  { ssr: false }
);
```

**Code Highlighting Fallback:**
```typescript
try {
  const highlighted = await highlighter.codeToHtml(code, { lang });
  return <div dangerouslySetInnerHTML={{ __html: highlighted }} />;
} catch {
  return <pre className="font-mono text-sm bg-muted p-4 rounded">{code}</pre>;
}
```

### Error Boundary
Wrap key page sections in React error boundaries that show a retry button instead of crashing the entire page.

## Implementation Notes
- The circuit breaker is a singleton per service (one for grading, one for question generation); use module-level instances
- IndexedDB operations are async and can throw `QuotaExceededError`; handle by evicting oldest drafts
- The `idb` npm package provides a clean Promise-based wrapper around IndexedDB; prefer it over raw IndexedDB APIs
- Service worker registration is out of scope for this spec (could be a future enhancement for full PWA support)
- Error messages should be mapped from backend error codes to user-friendly strings in a central `error-messages.ts` file
- Log all circuit breaker state transitions for observability

## Testing Strategy
- Unit tests for: circuit breaker state transitions (closed->open after 5 failures, open->half_open after timeout, half_open->closed on success), retry queue enqueue/dequeue/backoff timing, `useOnlineStatus` hook with simulated events, draft store CRUD operations
- Integration tests for: circuit breaker integration with mocked Claude API (trip and recovery), retry queue processes tasks on schedule, draft sync sends correct API requests on reconnect
- E2E tests for: offline banner appears when network is disconnected (via Playwright network emulation), answers are preserved in IndexedDB during offline, chart fallback renders when Recharts fails to load

## Acceptance Criteria
- [ ] Circuit breaker trips after 5 consecutive Claude API failures within 60 seconds
- [ ] Tripped circuit returns fallback (cached questions or delayed grading) instead of errors
- [ ] Circuit breaker probes recovery every 30 seconds and resets on success
- [ ] Offline banner appears when the browser goes offline
- [ ] Answer drafts are saved to IndexedDB when offline
- [ ] Saved drafts sync to the backend within 5 seconds of reconnecting
- [ ] Failed API calls retry up to 3 times with exponential backoff
- [ ] Radar chart degrades to a text table if Recharts fails to load
- [ ] Code blocks degrade to plain `<pre>` if Shiki fails to load
- [ ] User-facing error messages are actionable and do not expose technical details
- [ ] Circuit breaker state transitions are logged for monitoring
