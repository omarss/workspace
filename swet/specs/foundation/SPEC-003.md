# SPEC-003: GitHub OAuth Authentication

## Status
Approved

## Priority
P0

## Dependencies
- SPEC-001

## Overview
Implement GitHub OAuth authentication using NextAuth.js v5 on the frontend and JWT validation via `fastapi-nextauth-jwt` on the backend. Users authenticate through GitHub, the frontend manages the OAuth flow and session, and the backend validates the JWT from the NextAuth session cookie or Authorization header on every request. On first login, the backend upserts the user record from the JWT claims.

## Requirements

### Functional
1. GitHub OAuth login via NextAuth.js v5 with the GitHub provider
2. NextAuth route handler at `app/api/auth/[...nextauth]/route.ts`
3. `SessionProvider` wrapping the application for client-side session access
4. `signIn("github")` and `signOut()` actions available via UI components
5. Backend JWT validation using `fastapi-nextauth-jwt` to decode NextAuth session tokens
6. User upsert on first login: create user record from JWT claims (`github_id`, `github_username`, `email`, `avatar_url`) or update if exists
7. `GET /api/v1/auth/me` endpoint returning the authenticated user's profile
8. `POST /api/v1/auth/callback` endpoint (optional) for explicit token exchange if needed
9. Support reading JWT from both the NextAuth session cookie (`next-auth.session-token`) and the `Authorization: Bearer <token>` header

### Non-Functional
1. OAuth flow completes in under 3 seconds (excluding GitHub response time)
2. JWT validation adds less than 5ms overhead per request
3. Tokens must be validated on every backend request -- no trust of unsigned claims
4. NEXTAUTH_SECRET must be shared between frontend and backend for JWT decode
5. No user credentials are stored -- only GitHub OAuth metadata

## Technical Design

### Frontend Auth Configuration

**`src/lib/auth.ts`** - NextAuth.js v5 configuration
```typescript
// NextAuth config with GitHub provider
// Callbacks: jwt (attach github_id, login), session (expose to client)
// Pages: custom sign-in page (optional)
```

**`src/app/api/auth/[...nextauth]/route.ts`** - Route handler
```typescript
// Export GET and POST handlers from NextAuth
```

**`src/app/providers.tsx`** - Session provider wrapper
```typescript
// SessionProvider from next-auth/react wrapping children
// QueryClientProvider from TanStack Query
```

### Frontend Components
- `SignInButton` - Calls `signIn("github")`, shown when unauthenticated
- `UserMenu` - Displays avatar + username, dropdown with sign-out option
- `(auth)/layout.tsx` - Protected layout that redirects unauthenticated users

### Backend Auth Configuration

**`src/auth/service.py`** - User upsert logic
```python
async def upsert_user(db: AsyncSession, jwt_claims: dict) -> User:
    """Create or update user from NextAuth JWT claims.

    Extracts github_id, github_username/login, email, avatar_url from claims.
    Uses INSERT ... ON CONFLICT (github_id) DO UPDATE for atomicity.
    """
```

**`src/dependencies.py`** - JWT decode dependency
```python
# Uses fastapi-nextauth-jwt to decode the session token
# Reads from cookie (next-auth.session-token) or Authorization header
# Returns decoded JWT claims dict
```

### API Endpoints

- `GET /api/v1/auth/me` - Returns the currently authenticated user
  - Response 200: `{ id, github_id, github_username, email, avatar_url, is_active, onboarding_completed, created_at }`
  - Response 401: `{ error: "Unauthorized" }`

### Auth Flow Sequence
1. User clicks "Sign in with GitHub" on the frontend
2. NextAuth redirects to GitHub OAuth consent screen
3. GitHub redirects back with authorization code
4. NextAuth exchanges code for access token, fetches user profile
5. NextAuth creates a signed JWT session token (stored as httpOnly cookie)
6. Frontend redirects to dashboard/onboarding
7. Subsequent API requests include the session cookie automatically
8. Backend `fastapi-nextauth-jwt` middleware decodes and validates the JWT
9. Backend upserts user record from JWT claims on first request
10. `get_current_user` dependency injects the `User` model into route handlers

### Environment Variables
| Variable | Service | Description |
|----------|---------|-------------|
| NEXTAUTH_SECRET | Both | Shared secret for JWT signing/validation |
| NEXTAUTH_URL | Frontend | Canonical URL (e.g., `http://localhost:3000`) |
| GITHUB_CLIENT_ID | Frontend | GitHub OAuth app client ID |
| GITHUB_CLIENT_SECRET | Frontend | GitHub OAuth app client secret |

## Implementation Notes
- `fastapi-nextauth-jwt` decodes the same JWT that NextAuth produces, using the shared `NEXTAUTH_SECRET`. No separate token exchange is needed.
- The JWT contains claims like `sub` (user ID), `email`, `name`, `picture`, and custom fields added in the NextAuth `jwt` callback.
- The `github_id` and GitHub username (`login`) must be explicitly added to the JWT in the NextAuth `jwt` callback.
- NextAuth v5 uses `auth()` server-side and `useSession()` client-side to access the session.
- The `(auth)/layout.tsx` route group uses NextAuth's `auth()` to check for a session and redirects to the landing page if absent.
- Cookie name varies by environment: `next-auth.session-token` in development, `__Secure-next-auth.session-token` in production (HTTPS).

## Testing Strategy
- Unit tests for: User upsert service (create new user, update existing user), JWT claims extraction
- Integration tests for: `/api/v1/auth/me` returns user data with valid JWT, `/api/v1/auth/me` returns 401 without JWT, user upsert idempotency
- E2E tests for: Full OAuth flow via Playwright (mocked GitHub provider), sign-in redirects to dashboard, sign-out clears session

## Acceptance Criteria
- [ ] Clicking "Sign in with GitHub" initiates the OAuth flow and redirects to GitHub
- [ ] Successful OAuth callback creates a session and redirects to the dashboard
- [ ] `GET /api/v1/auth/me` returns the authenticated user's data
- [ ] `GET /api/v1/auth/me` returns 401 when no valid session exists
- [ ] First login creates a new user record in the database
- [ ] Subsequent logins update the existing user record (`github_username`, `avatar_url` changes)
- [ ] Sign-out clears the session cookie and redirects to the landing page
- [ ] Backend correctly decodes JWT from both cookie and Authorization header
- [ ] Protected frontend routes redirect unauthenticated users to sign-in
- [ ] Environment variables are documented in `.env.example` files
