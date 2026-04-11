# SPEC-010: User Onboarding Flow

## Status
Draft

## Priority
P1

## Dependencies
- SPEC-003 (GitHub OAuth authentication)
- SPEC-004 (Session and authorization middleware)

## Overview
The onboarding flow is the first interaction a newly authenticated user has with SWET. It collects the user's engineering role, technology preferences, and areas of interest through a guided 3-step wizard. This data drives question pool generation (via `config_hash`) and ensures each assessment is tailored to the user's professional context.

Users who have not completed onboarding are redirected to `/onboarding` on every authenticated page load. Once submitted, the profile can be updated before the first assessment begins.

## Requirements

### Functional
1. New users must complete onboarding before accessing any assessment features.
2. The onboarding wizard consists of 3 sequential steps:
   - **Step 1 - Role Selection**: User selects exactly one primary role from the available roles grid.
   - **Step 2 - Technology Selection**: User selects programming languages, frameworks, and interest areas via multi-select inputs. At least one language must be selected.
   - **Step 3 - Confirmation**: User reviews their selections and submits. Experience years (optional) can be entered here.
3. The backend computes a deterministic `config_hash` (SHA-256) from the profile data on creation and update.
4. The `config_hash` is computed from: `role` + sorted `interests` + sorted `languages` + sorted `frameworks`, serialized as compact JSON with sorted keys.
5. The `GET /api/v1/onboarding/options` endpoint returns all available roles, interests, languages, and frameworks without requiring authentication.
6. Profile creation (`POST /api/v1/onboarding/profile`) sets `user.onboarding_completed = True`.
7. Profile updates (`PUT /api/v1/onboarding/profile`) are permitted only before the user starts their first assessment.
8. `GET /api/v1/onboarding/profile` returns the current user's profile or 404 if none exists.

### Non-Functional
1. The onboarding wizard must be completable in under 60 seconds for a typical user.
2. Validation feedback appears inline (not as toasts or alerts) within 100ms of user interaction.
3. Step navigation preserves previous selections when going back.
4. The options endpoint should be cacheable (static data, no DB queries).

## Technical Design

### API Endpoints
- `GET /api/v1/onboarding/options` - Returns available roles, interests, languages, and frameworks. No auth required. Returns `OnboardingOptionsResponse`.
- `POST /api/v1/onboarding/profile` - Creates user profile. Requires auth. Returns `ProfileResponse` (201).
- `GET /api/v1/onboarding/profile` - Gets current user's profile. Requires auth. Returns `ProfileResponse` or 404.
- `PUT /api/v1/onboarding/profile` - Updates user profile. Requires auth. Returns `ProfileResponse`.

### Available Roles
```
backend, frontend, fullstack, mobile, devops, data, ml, security, qa, gamedev
```

### config_hash Computation
```python
config = {
    "role": role,
    "interests": sorted(interests),
    "languages": sorted(languages),
    "frameworks": sorted(frameworks),
}
config_str = json.dumps(config, sort_keys=True, separators=(",", ":"))
config_hash = hashlib.sha256(config_str.encode()).hexdigest()
```

Users with identical role + technology selections share the same `config_hash`, enabling question pool reuse.

### Database Changes
- `user_profiles` table (already defined in `src/onboarding/models.py`):
  - `id` (UUID, PK)
  - `user_id` (UUID, FK -> users.id, unique)
  - `primary_role` (VARCHAR(100))
  - `interests` (JSONB, list of strings)
  - `technologies` (JSONB, `{languages: [...], frameworks: [...]}`)
  - `experience_years` (INTEGER, nullable)
  - `config_hash` (VARCHAR(64), indexed)
  - `created_at`, `updated_at` (TIMESTAMPTZ)

### Components (Frontend)

#### `OnboardingPage` (`/onboarding`)
- Route guard: redirect to `/dashboard` if `user.onboarding_completed` is true.
- Manages wizard state (current step, selections).

#### `OnboardingStepper`
- Horizontal stepper UI showing steps 1/2/3 with labels.
- Active step is highlighted; completed steps show a checkmark.

#### `RoleSelectionStep`
- Grid of role cards (icon + label for each of the 10 roles).
- Single-select: clicking one deselects the previous.

#### `TechnologySelectionStep`
- Three multi-select sections: Languages, Frameworks, Interests.
- Chip-based selection with search/filter.
- Options fetched from `GET /api/v1/onboarding/options`.

#### `ConfirmationStep`
- Summary view of selections grouped by category.
- Optional experience years numeric input (0-50).
- "Start Assessment" submit button.

## Implementation Notes
- The `config_hash` is the cornerstone of the caching system. Two users who select the same role and technologies will share question pools, avoiding redundant Claude API calls.
- `get_onboarding_options()` is a pure function returning hardcoded data. No database query is needed since roles and technologies are static.
- The `ConflictError` is raised if a user tries to create a profile when one already exists, guiding them to use `PUT` instead.
- The frontend should use TanStack Query to fetch onboarding options and manage profile mutations.
- Zustand can hold local wizard state (current step, draft selections) to survive re-renders without unnecessary API calls.

## Testing Strategy
- **Unit tests**: `compute_config_hash` determinism (same input -> same output, different input -> different output), `get_onboarding_options` returns correct structure.
- **Integration tests**: Profile CRUD lifecycle (create, read, update), conflict on duplicate creation, 404 on missing profile, `onboarding_completed` flag set after profile creation.
- **E2E tests**: Full wizard flow from role selection through confirmation, back-navigation preserving state, redirect behavior for completed/incomplete onboarding.

## Acceptance Criteria
- [ ] `GET /api/v1/onboarding/options` returns all 10 roles, 10 interests, 14 languages, and 16 frameworks.
- [ ] `POST /api/v1/onboarding/profile` creates a profile with a valid `config_hash` and sets `onboarding_completed = True`.
- [ ] `POST /api/v1/onboarding/profile` returns 409 if profile already exists.
- [ ] `GET /api/v1/onboarding/profile` returns 404 when no profile exists.
- [ ] `PUT /api/v1/onboarding/profile` recomputes `config_hash` when role or technologies change.
- [ ] `config_hash` is deterministic: identical inputs always produce the same hash.
- [ ] Frontend wizard allows step-by-step progression and back-navigation.
- [ ] Role selection step enforces exactly one selection before proceeding.
- [ ] Technology step enforces at least one language selection.
- [ ] Confirmation step shows a complete summary of all selections.
- [ ] Unauthenticated users cannot access profile endpoints (401).
