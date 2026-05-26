// Phase 13 — step-up authentication middleware.
//
// AGENTS.md §18.4 mandates that destructive control-plane endpoints
// (upgrade / rollback / purge / freeze-keys / impersonation-sessions /
// detach-domain) require a *fresh* MFA assertion. "Fresh" is defined
// as `auth_time < now - 5min` AND `acr == gold` AND HasStrongAMR().
//
// The middleware refuses the request with a 403 + RFC 9457 problem
// of type `step-up-required` carrying a `kc_acr=gold` hint so the
// saasctl client can pop the OIDC re-auth screen. The IdP supplies
// `auth_time` automatically; we re-read it from context rather than
// from the token bytes because the verifier has already parsed the
// JWT once.
//
// Why server-side instead of relying on Keycloak's prompt=login: KC's
// `max_age` parameter does enforce a re-auth at the IdP, but it cannot
// retroactively refuse an already-issued token. The platform-side
// check is the authoritative gate — KC's prompt=login is the UX
// convenience that lets saasctl initiate the re-auth automatically.

package operatorjwt

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/problem"
)

// StepUpWindow is the max permitted age of the upstream `auth_time` claim
// for a request to count as MFA-fresh. AGENTS.md §18.4 pins it at 5 min;
// the constant is exported so tests can clock against the same value.
const StepUpWindow = 5 * time.Minute

// StepUpACR is the value the operators-realm assigns when MFA is fresh.
// Mapped via the realm-level `acr.loa.map` attribute (see operators-realm.json).
const StepUpACR = "gold"

// RequireStepUp wraps the next handler in a step-up freshness gate.
// Returns 403 problem-details:
//
//   - missing principal               → unauthorized (401)
//   - non-operator principal          → forbidden (403) — only operators
//                                       hit destructive control-plane paths
//   - principal has no strong AMR     → step-up-required (403)
//   - principal acr != gold           → step-up-required (403)
//   - principal auth_time > window    → step-up-required (403)
//
// The middleware reads `nowFn` for clock injection in tests; production
// callers leave it nil (defaults to time.Now).
func RequireStepUp(nowFn func() time.Time) func(http.Handler) http.Handler {
	if nowFn == nil {
		nowFn = time.Now
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			p, ok := auth.PrincipalFromContext(r.Context())
			if !ok {
				writeProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized,
					"Missing or invalid operator token.", "")
				return
			}
			// A non-operator hitting a destructive control-plane endpoint is
			// a routing bug, not a step-up failure. 403 rather than 403 +
			// step-up-required so the client doesn't pointlessly re-auth.
			if p.ActorType != auth.ActorOperator {
				writeProblem(w, r, http.StatusForbidden, problem.TypeForbidden,
					"Destructive endpoint reserved for operators.", "")
				return
			}
			if err := CheckStepUp(p, nowFn()); err != nil {
				writeProblem(w, r, http.StatusForbidden, problem.TypeStepUpRequired,
					err.Error(), "kc_acr=gold max_age=0")
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// CheckStepUp returns nil when the principal satisfies the step-up
// requirements, otherwise an error suitable for the problem-details
// `detail` field. Exported for handler-level use when middleware
// composition isn't convenient (e.g. inside a strict-handler call).
func CheckStepUp(p auth.Principal, now time.Time) error {
	if !p.HasStrongAMR() {
		return errStepUp("no strong MFA in the token's amr claim")
	}
	if p.ACR != StepUpACR {
		return errStepUp("acr claim is not gold (LoA 2)")
	}
	if p.AuthTime.IsZero() {
		return errStepUp("auth_time claim missing")
	}
	if now.Sub(p.AuthTime) > StepUpWindow {
		return errStepUp("auth_time exceeds 5-minute step-up window")
	}
	return nil
}

// errStepUp wraps the sentinel ErrStepUpRequired with a detail message
// preserved through errors.Is. Callers compare with errors.Is to detect
// the class, and call .Error() for the user-visible string.
func errStepUp(detail string) error {
	return stepUpErr{detail: detail}
}

type stepUpErr struct{ detail string }

func (e stepUpErr) Error() string { return e.detail }
func (e stepUpErr) Is(target error) bool {
	return errors.Is(target, auth.ErrStepUpRequired)
}

// writeProblem emits an RFC 9457 problem response. `hint` becomes the
// problem's `detail` suffix when non-empty — the saasctl client reads
// it to decide whether to invoke the re-auth flow.
func writeProblem(w http.ResponseWriter, r *http.Request, status int, typeURI, detail, hint string) {
	p := problem.Problem{
		Type:     typeURI,
		Title:    http.StatusText(status),
		Status:   status,
		Detail:   detail,
		Instance: r.URL.Path,
	}
	if hint != "" {
		// Embed the hint in a structured way without breaking the
		// existing Problem shape — RFC 9457 allows arbitrary extension
		// members, but our generator pins the schema; piggy-back on the
		// detail field instead so contract tests don't fail.
		p.Detail = detail + " (hint: " + hint + ")"
	}
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(p)
}
