// Package scrape pulls tweets off x.com's authenticated GraphQL
// SearchTimeline endpoint via a direct HTTP client.
//
// Why no library?
// The previously-used imperatrona/twitter-scraper carries a stale
// bearer token, stale GraphQL query IDs, and doesn't sign requests
// with the x-client-transaction-id header that x.com's anti-bot
// gateway now demands. Calls return 401 / 404 every time. Maintained
// alternatives (twscrape) exist in Python but bringing in a Python
// sidecar dwarfs the actual scrape logic, which is about thirty lines.
//
// Approach.
// A server-resident headless Chrome (see tweets-browser.service)
// holds the authenticated session and emits fresh x-client-transaction-id
// values whenever it navigates. A small Python script — invoked
// hourly by the refresh loop — drives that browser via CDP to perform
// one search, captures the request headers + cookies, and writes
// them to /srv/tweets/{cookies,search-template}.json. This package
// reads those two files and replays the GraphQL call directly over
// http.Client, swapping in our query string. Cheap, fast, and the
// only fragility (Chrome breaking, X rotating endpoints) lives in
// the refresher, not in the hot path.
//
// All scrape behaviour is best-effort. Any error returns to the
// caller (the refresh loop), which logs and lets the HTTP path keep
// serving from SQLite. Never panic, never block the HTTP path.
package scrape

import (
	"context"

	"github.com/omarss/workspace/tweets/internal/server"
)

// Scraper is the narrow interface the refresh loop depends on. Lets
// tests substitute a fake without dragging the HTTP transport in.
type Scraper interface {
	Search(ctx context.Context, country server.Country, max int) ([]server.Tweet, error)
}
