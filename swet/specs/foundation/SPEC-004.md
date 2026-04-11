# SPEC-004: Session and Authorization Middleware

## Status
Approved

## Priority
P0

## Dependencies
- SPEC-002
- SPEC-003

## Overview
Implement the backend middleware chain and dependency injection pattern for session management and authorization. This spec covers the `get_current_user` FastAPI dependency, CORS middleware configuration, request state JWT injection, and active user validation. Together these form the security boundary that every authenticated endpoint passes through.

## Requirements

### Functional
1. `get_current_user` FastAPI dependency that extracts and validates the JWT, upserts the user, and returns the `User` model instance
2. CORS middleware allowing the frontend origin (`http://localhost:3000`) with credentials support
3. Request state injection: decoded JWT claims attached to `request.state` for access in middleware and dependencies
4. Active user check: requests from deactivated users (`is_active=False`) are rejected with 403
5. Optional `get_optional_user` dependency for endpoints that work both authenticated and unauthenticated
6. All protected endpoints use `Depends(get_current_user)` -- never manual JWT parsing in route handlers

### Non-Functional
1. Middleware chain executes in under 10ms total overhead per request (excluding DB queries)
2. CORS configuration must be restrictive -- only the configured frontend origin is allowed
3. Failed authentication must return a clear 401 response with the standardized error format (see SPEC-005)
4. Failed authorization (inactive user) must return a clear 403 response

## Technical Design

### Middleware Chain Order
Middleware executes in registration order (outermost first):
1. **CORS Middleware** - Handles preflight OPTIONS and injects CORS headers
2. **JWT Decode Middleware** (optional, via `fastapi-nextauth-jwt`) - Decodes JWT and attaches to request state
3. **Route handler** with `Depends(get_current_user)` - Validates user and injects into handler

### CORS Configuration
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],  # e.g., "http://localhost:3000"
    allow_credentials=True,                  # Required for cookie-based auth
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Dependencies (`src/dependencies.py`)

**`get_current_user`**
```python
async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract JWT from request, validate, upsert user, check active status.

    1. Read JWT from cookie or Authorization header via fastapi-nextauth-jwt
    2. If no valid JWT, raise UnauthorizedError
    3. Upsert user from JWT claims
    4. If user.is_active is False, raise ForbiddenError
    5. Return User model instance
    """
```

**`get_optional_user`**
```python
async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Same as get_current_user but returns None instead of raising on missing JWT.

    Used for endpoints that have different behavior for authenticated vs anonymous users.
    """
```

**`get_db`**
```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, ensuring proper cleanup."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### Request State
After JWT decode, the following are available on `request.state`:
- `request.state.jwt_claims` - Raw decoded JWT claims dict (or None)

### CORS Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| FRONTEND_URL | `http://localhost:3000` | Allowed CORS origin |
| BACKEND_CORS_ORIGINS | `["http://localhost:3000"]` | Additional allowed origins (JSON array) |

### Protected Route Example
```python
@router.get("/api/assessments")
async def list_assessments(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # user is guaranteed to be authenticated and active
    return await assessment_service.list_for_user(db, user.id)
```

## Implementation Notes
- The `get_current_user` dependency is the single source of truth for authentication in all route handlers. No route should attempt its own JWT parsing.
- `fastapi-nextauth-jwt` handles the JWT decoding using the shared `NEXTAUTH_SECRET`. The dependency wraps this with user upsert and active status checks.
- The `get_db` dependency uses a context manager pattern with commit on success and rollback on exception, so route handlers do not need explicit commit/rollback calls.
- CORS `allow_credentials=True` is required because the NextAuth session cookie must be sent cross-origin from the frontend (port 3000) to the backend (port 8000).
- In production, `allow_origins` should be updated to the actual deployment domain. Never use `["*"]` with `allow_credentials=True` as browsers reject this combination.
- The middleware does not perform authorization beyond checking `is_active`. Role-based access control is not needed for SWET since all authenticated users have the same permissions.

## Testing Strategy
- Unit tests for: `get_current_user` with valid JWT returns User, `get_current_user` with missing JWT raises 401, `get_current_user` with inactive user raises 403, `get_optional_user` with missing JWT returns None, `get_db` yields session and commits on success, `get_db` rolls back on exception
- Integration tests for: Full request through middleware chain with valid cookie, CORS preflight response includes correct headers, Cross-origin request with credentials succeeds, Request without auth to protected endpoint returns 401 with error format
- E2E tests for: Frontend API call with session cookie succeeds, Frontend API call after sign-out returns 401

## Acceptance Criteria
- [ ] `Depends(get_current_user)` in a route handler injects an authenticated `User` instance
- [ ] Requests without a valid JWT to protected endpoints return `401 Unauthorized`
- [ ] Requests from inactive users return `403 Forbidden`
- [ ] `get_optional_user` returns `None` for unauthenticated requests without raising
- [ ] CORS preflight (`OPTIONS`) requests return correct `Access-Control-Allow-*` headers
- [ ] Cross-origin requests from `http://localhost:3000` with credentials succeed
- [ ] Cross-origin requests from unauthorized origins are rejected
- [ ] The `get_db` dependency commits on success and rolls back on exception
- [ ] No route handler contains manual JWT parsing or cookie reading logic
- [ ] Error responses from auth failures follow the standardized error format from SPEC-005
