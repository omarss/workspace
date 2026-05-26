package workflows

import (
	"context"
	"net/http"

	cp "github.com/omarss/saas/sdk/go/controlplane"
	dp "github.com/omarss/saas/sdk/go/dataplane"
)

// BearerControlPlane returns a controlplane RequestEditorFn that injects
// Authorization: Bearer <token> on every request. Pass the result to
// controlplane.NewClientWithResponses via WithRequestEditorFn.
//
// The token is read by reference (closure over the supplied string), so
// the same editor cannot be retroactively swapped — pair this with a
// RefreshingClient when the token must be rotated mid-flight.
func BearerControlPlane(token string) cp.RequestEditorFn {
	return func(_ context.Context, req *http.Request) error {
		req.Header.Set("Authorization", "Bearer "+token)
		return nil
	}
}

// BearerDataPlane is the dataplane counterpart of BearerControlPlane.
// Same semantics; two helpers exist because the generated RequestEditorFn
// types live in different packages and Go does not allow a cross-package
// alias to satisfy both.
func BearerDataPlane(token string) dp.RequestEditorFn {
	return func(_ context.Context, req *http.Request) error {
		req.Header.Set("Authorization", "Bearer "+token)
		return nil
	}
}
