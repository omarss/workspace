# Recipe: link a social provider

## When to use

An existing user wants to add Google / GitHub / Apple sign-in to their
account so they can log in via the social IdP instead of (or in
addition to) email + password. ADR 014 promotes social login to MVP.

## Prerequisites

- User ID (`user_01HX…`)
- The provider's IdP already configured at the Deployment level
  (operator action; one-time per Deployment)
- A `redirect_uri` registered with the provider

## CLI

```text
$ saasctl user link-social \
    --user     user_01HX… \
    --provider google \
    --redirect https://app.example.test/callback
{"data":{"authorize_url":"https://accounts.google.com/o/oauth2/v2/auth?…"}}
```

The CLI prints the authorize URL — open it in a browser to complete the
OAuth dance. The IdP redirects back to the platform's callback, which
finalises the link and creates the audit event `user.social_linked`.

## curl

```bash
curl -X POST "https://dev.default.saas.omarss.net/v1/users/$USER_ID/social-providers" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: idem_$(uuidgen)" \
  -d '{
    "provider":     "google",
    "redirect_uri": "https://app.example.test/callback"
  }'
```

Response:

```json
{
  "data": {
    "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth?…"
  }
}
```

## TS SDK

```typescript
import { UsersApi } from "@omarss/saas-dataplane-sdk";

const users = new UsersApi(cfg);
const { data } = await users.linkSocialProvider({
  userId:         "user_01HX…",
  idempotencyKey: `idem_${crypto.randomUUID()}`,
  linkSocialProviderRequest: {
    provider:     "google",
    redirect_uri: "https://app.example.test/callback",
  },
});
window.location.href = data.authorize_url;
```

## Go SDK

```go
import "github.com/omarss/saas/sdk/go/workflows"

result, err := workflows.LinkSocialProvider(ctx, client, workflows.LinkSocialProviderInput{
    UserID:      "user_01HX…",
    Provider:    "google",
    RedirectURI: "https://app.example.test/callback",
})
fmt.Println("open in browser:", result.AuthorizeURL)
```

## Common pitfalls

- **Provider unsupported**: 422 — only `google`, `github`, `apple`, and
  `microsoft` are wired in MVP.
- **Account already linked at IdP**: 409 — unlink first via
  `DELETE /v1/users/{id}/social-providers/{provider}`.
- **PKCE mismatch on callback**: 400 — the callback's `state` must match
  the originating request; do not reuse `state` across attempts.
