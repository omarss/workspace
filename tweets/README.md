# tweets

Feed service for the omono Feed tab. Scrapes location-tagged tweets
from twitter.com / x.com via an authenticated session, applies a
heuristic spam filter, caches in SQLite, and exposes a small JSON API
the Android client polls.

```
background loop  →  twitter scraper  →  spam filter  →  SQLite store
                                                            ↓
                                                       HTTP /tweets
```

Scraping happens on the server so the phone never waits, X breakage
can be fixed in one place, and the APK doesn't need a release every
time the GraphQL schema shifts.

## Endpoints

```
GET /tweets?country=ksa|eg
200 application/json

{
  "country": "ksa",
  "generated_at": "2026-05-25T15:55:00Z",
  "tweets": [
    {
      "id": "1797123456789012345",
      "author": "وزارة الداخلية",
      "handle": "MOISaudiArabia",
      "text": "...",
      "created_at": "2026-05-25T15:35:00Z",
      "lang": "ar",
      "place": "Riyadh, SA",
      "country": "ksa",
      "reply_count": 142,
      "like_count": 2103,
      "retweet_count": 587,
      "spam_score": 0.04
    }
  ]
}

GET /healthz   →  {"status":"ok"}
```

`country` is optional; missing defaults to `ksa`. Anything other than
`ksa` or `eg` returns `400 unknown country`.

`spam_score` is in `[0, 1]`. The service drops anything above the
threshold (default `0.7`) before serving; what reaches the client is
already filtered. Values close to the threshold can be used by the UI
to de-emphasise borderline rows.

When the SQLite cache is empty (fresh deploy, missing cookies, scrape
failure with no prior batches), the handler falls back to a small
hand-crafted fixture set so the UI is never blank.

## Cookies — how authentication actually works

X's GraphQL endpoints reject guest tokens after a few minutes; the
scraper needs a real logged-in session. The user maintains two cookies
in `/srv/tweets/cookies.json` (mode 600, owned by the service user):

```json
{
  "auth_token": "<value of the auth_token cookie>",
  "ct0": "<value of the ct0 cookie>"
}
```

### Extracting cookies

1. Log into x.com in a desktop browser.
2. Open DevTools → Application → Storage → Cookies → `https://x.com`.
3. Copy the `auth_token` and `ct0` values.
4. Paste into `/srv/tweets/cookies.json` (the `apply-tweets-host`
   target seeds a placeholder file the first time).
5. `sudo systemctl restart tweets`.

X rotates `ct0` periodically; `auth_token` typically lives weeks to
months. When the service starts logging `twitter session not
authenticated`, re-do steps 1–5.

### Risk acknowledgement

Scraping any way you slice it violates X's ToS. The service is
designed to minimise behavioural signals — single-user load, slow
poll interval, no follow/like/post operations — but X account
suspension is not zero risk. The session cookies allow the scraper to
read the feed and nothing else: the service never calls any write
endpoint.

## Configuration

| Flag / env | Default | Notes |
|---|---|---|
| `-addr` / `TWEETS_ADDR` | `:8080` | Listen address. `127.0.0.1:8088` in production via systemd. |
| `-cookies` / `TWEETS_COOKIES_PATH` | `/srv/tweets/cookies.json` | Path to the two-field JSON above. |
| `-db` / `TWEETS_DB_PATH` | `/srv/tweets/tweets.sqlite` | SQLite cache file. Auto-created with WAL. |
| `-interval` / `TWEETS_REFRESH_INTERVAL` | `10m` | Background scrape cadence per country. |
| `-readonly` | `false` | Skip the scrape loop; serve cache + fixtures only. Useful for local dev without cookies. |

## Layout

```
cmd/tweetsd/             entrypoint + flag parsing + graceful shutdown
internal/server/         HTTP routes, wire types, fixture source,
                         cached source (store → fixture fallback)
internal/scrape/         cookie loader + imperatrona/twitter-scraper
                         wrapper. `place_country:SA` / `:EG` queries.
internal/spam/           heuristic scorer; see PR #16 for the feature
                         breakdown and thresholds.
internal/store/          SQLite (pure-Go modernc driver), upsert
                         batch + latest-by-country + retention purge.
internal/feed/           background refresh loop (per country, per
                         tick) with spam-on-ingestion gate.
```

## Make targets

| Target | What |
|---|---|
| `make build` | Compile `bin/tweetsd` |
| `make run`   | Run on `:8080` against `/srv/tweets/`. Add `READONLY=1` to skip scraping. |
| `make test`  | `go test ./...` |
| `make lint`  | `go vet ./...` |
| `make tidy`  | `go mod tidy` |
| `make clean` | Remove `bin/` |

For local dev without cookies:

```
make build
./bin/tweetsd -readonly -addr :18080 -db /tmp/dev-tweets.sqlite
curl 'http://127.0.0.1:18080/tweets?country=eg'
```

## Deployment

Lives on the same host as the rest of the homelab. Provisioned via:

```
sudo make -C homelab apply-tweets-host
sudo $EDITOR /srv/tweets/cookies.json   # paste auth_token + ct0
sudo systemctl restart tweets
sudo certbot --nginx -d tweets.omarss.net
```

The setup script is idempotent — re-run after `git pull` to rebuild
and restart with the new binary. See `homelab/scripts/setup-tweets-host.sh`
and `homelab/systemd/tweets.service`.

Service runs as user `omar` on `127.0.0.1:8088`; nginx vhost
(`homelab/nginx/tweets.omarss.net.conf`) reverse-proxies and adds the
strict-API security headers. Public surface is exactly `/healthz` and
`/tweets` — every other path 404s without ever reaching the backend.

Status, logs, restart:

```
make -C homelab tweets-status     # systemd status + healthz
make -C homelab tweets-restart    # restart + status
sudo journalctl -u tweets -f      # tail logs
```
