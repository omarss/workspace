# tweets

Feed service for the omono Twitter tab. Serves a small JSON surface the
Android app polls; keeps all scraping + spam filtering on the server so
APK doesn't need a release every time Twitter changes its HTML.

## Phase 1 — what's shipping today

- HTTP/JSON service (`cmd/tweetsd`) bound to `:8080` by default
- `/healthz` → liveness probe (`{"status":"ok"}`)
- `/tweets?country=ksa|eg` → fixture data, stable shape, real
  spam-scoring code path
- Heuristic spam scorer (`internal/spam`) used by the contract today
  with score `0` on hand-crafted fixtures; ready to ingest real tweets
  in Phase 2 without API breaks

The Android client (omono v0.55+) talks to this service via
`net.omarss.omono.ui.twitter`. With the service not deployed, the
client renders an empty/error state and the rest of the app is
unaffected.

## Phase 2 — what's next (separate PR)

- `internal/scrape` package — twitter.com/x.com GraphQL client with
  rotating logged-in-cookie pool
- Periodic background fetch loop (every ~10 min) populating a SQLite
  cache; `/tweets` reads from cache so the phone never waits on a
  scrape
- `internal/store` for the cache + duplicate-recent detection used by
  the spam scorer

## Wire contract

```
GET /tweets?country=ksa
200 application/json

{
  "country": "ksa",
  "generated_at": "2026-05-25T13:55:00Z",
  "tweets": [
    {
      "id": "ksa-1",
      "author": "وزارة الداخلية",
      "handle": "MOISaudiArabia",
      "text": "تم تشغيل خدمة جديدة ...",
      "created_at": "2026-05-25T13:35:00Z",
      "lang": "ar",
      "place": "Riyadh, SA",
      "country": "ksa",
      "reply_count": 142,
      "like_count": 2103,
      "retweet_count": 587,
      "spam_score": 0
    }
  ]
}
```

`country` query is optional; missing defaults to `ksa`. Anything other
than `ksa` or `eg` returns `400 unknown country`.

`spam_score` is in `[0, 1]`. The service drops anything above its
threshold before serving; values you see are passed-but-borderline.

## Make targets

| Target | What |
|---|---|
| `make build` | Compile to `bin/tweetsd` |
| `make run`   | Run on `:8080` (override with `ADDR=:9090 make run`) |
| `make test`  | `go test ./...` |
| `make lint`  | `go vet ./...` |
| `make tidy`  | `go mod tidy` |

## Deployment (Phase 2 will land this)

A systemd unit + nginx vhost (`tweets.omarss.net`) get installed by
`sudo make -C homelab apply-tweets-host`. The unit runs `tweetsd` as
the `omar` user on `127.0.0.1:8080`; nginx terminates TLS via certbot
and reverse-proxies.
