// Go SDK for the SaaS control plane + data plane.
//
// Two generated client packages (controlplane, dataplane) plus handwritten
// workflow wrappers under workflows/. Published as a separate module so
// consumers `go get github.com/omarss/saas/sdk/go/controlplane` (or
// .../workflows) without pulling in the platform's internal packages.
module github.com/omarss/saas/sdk/go

go 1.24.0

toolchain go1.24.13

require (
	github.com/coreos/go-oidc/v3 v3.17.0
	github.com/oapi-codegen/runtime v1.4.1
	github.com/oklog/ulid/v2 v2.1.1
	golang.org/x/oauth2 v0.30.0
)

require (
	github.com/apapsch/go-jsonmerge/v2 v2.0.0 // indirect
	github.com/go-jose/go-jose/v4 v4.1.3 // indirect
	github.com/google/uuid v1.6.0 // indirect
)
