# ivr

Multi-tenant conversational IVR platform — Arabic + English, AI-driven, OSS-first, cloud-portable.

## Status

Phase 0 (skeleton). Not yet runnable end-to-end. See `docs/ARCHITECTURE.md`.

## Quickstart (development on local k3s)

Requires: `podman`, `kubectl`, `helm`, a running k3s cluster (single node is fine).

```sh
make help            # list targets
make tools           # pull builder image, install host tools (kubectl, helm verified)
make test            # run unit tests inside the builder container
make lint            # golangci-lint inside the builder container
make image-api       # build api service image into local k3s containerd
make deploy-deps     # PG (Percona), NATS, Valkey, SeaweedFS, Svix into ivr-dev namespace
make deploy-api      # deploy the api service to ivr-dev
make smoke           # curl /healthz against the in-cluster service
```

No Go is required on the host — all builds run inside `golang:1.26.2-alpine`.

## Layout

| Path | Purpose |
|---|---|
| `api/` | OpenAPI 3.1 source of truth + generated server stubs |
| `cmd/` | Service entrypoints |
| `internal/` | Product code: templates, calls, tenants, jambonz integration |
| `pkg/` | Cloud-portable adapters (blob, bus, jobs, kv, secrets, otel, webhook) |
| `inference/` | Python sidecars: STT (faster-whisper), TTS (Piper / F5-TTS) |
| `deploy/` | Kustomize bases + overlays, vendor Helm values |
| `db/migrations/` | golang-migrate SQL files |

See `CLAUDE.md` for the project-level orientation Claude reads on each session.
