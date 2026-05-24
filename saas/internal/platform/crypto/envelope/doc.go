// Package envelope implements the OpenBao-backed envelope-encryption client
// used by every persistence-layer path that handles fields marked
// `pii:"true"` or `sensitive:"true"`. It is the Phase 4 concrete behind the
// Encryptor interface declared in internal/platform/crypto.
//
// Envelope shape:
//
//  1. App asks OpenBao for a 32-byte data encryption key (DEK) via the
//     transit/datakey/plaintext/:kid endpoint. The response carries the DEK
//     in cleartext plus the same DEK wrapped against the deployment's
//     transit key (the "vault:vN:<b64>" string).
//  2. App encrypts the payload with AES-256-GCM using the DEK and a fresh
//     12-byte nonce. The additional-authenticated-data (AAD) is the row
//     binding (deployment_id || resource_type || resource_id) — copying a
//     ciphertext to a different row fails the AEAD tag check.
//  3. App zeroes the DEK and persists the envelope: ciphertext, wrapped_dek,
//     nonce, algo, kid, key_version.
//
// Decrypt mirrors the flow in reverse, with one critical extra step: the
// caller's expected kid (sourced from the request context's deployment_id)
// is compared against the stored row's kid BEFORE the OpenBao API call. A
// mismatch returns ErrKidMismatch without ever asking OpenBao to decrypt —
// this defends against bugs that cross deployment boundaries even when the
// per-Deployment policy would otherwise refuse the API call.
//
// The package authenticates to OpenBao via one of two methods, selected at
// Client construction:
//
//   - AuthKubernetes — data-plane pods. SA JWT from the in-pod token file is
//     POSTed to auth/kubernetes/login; role name is the deployment_id.
//   - AuthAppRole   — control-plane host process. role_id + secret_id come
//     from a 0400 file under /etc/saas/approle/ (or env vars for local dev).
//
// In both cases the resulting client token is renewed by a background
// lifetime watcher so the process never sees a stale token mid-request.
//
// Anti-patterns (AGENTS.md §18.7):
//
//   - Decrypting under a kid different from the request context's
//     deployment_id. Use Decrypt; do not call the Logical client directly.
//   - Storing the DEK in any field, struct, or cache. The package zeroes the
//     DEK between Seal/Open calls; callers must do the same when they handle
//     raw DEK bytes for any reason.
//   - Logging the WrappedDEK, the AAD, the DEK plaintext, or any OpenBao
//     token. The platform slog redactor's static keyset includes these names
//     (internal/platform/log/redact.go).
package envelope
