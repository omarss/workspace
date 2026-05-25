// Package store persists the scraped feed in SQLite so the HTTP handler
// can serve responses synchronously without waiting on Twitter. The
// scraper writes new batches into the same table; the handler reads
// the N most recent rows per country.
//
// Pure-Go driver (modernc.org/sqlite) is used deliberately — the
// service is built once on the dev host and run on the homelab box as
// a static-ish binary without a CGo toolchain, which the mattn driver
// would require.
package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"time"

	_ "modernc.org/sqlite"

	"github.com/omarss/workspace/tweets/internal/server"
)

// DB wraps the sql.DB with the tweets-specific operations callers
// actually need. Keeping the surface narrow makes the SQLite choice
// easy to swap later if we outgrow it.
type DB struct {
	conn *sql.DB
}

// Open opens (or creates) the SQLite database at path and runs schema
// setup. Path can be `:memory:` for tests.
func Open(path string) (*DB, error) {
	conn, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, fmt.Errorf("sqlite open %q: %w", path, err)
	}
	// Single-writer assumption (the refresh loop is the only writer);
	// keep the connection pool small so SQLite's lock contention story
	// stays simple.
	conn.SetMaxOpenConns(1)
	if err := migrate(conn); err != nil {
		_ = conn.Close()
		return nil, err
	}
	return &DB{conn: conn}, nil
}

func (d *DB) Close() error { return d.conn.Close() }

// SaveBatch upserts a slice of tweets in one transaction. ID is the
// primary key so a re-scrape of the same tweet updates its mutable
// fields (like_count, spam_score) without duplicating.
func (d *DB) SaveBatch(ctx context.Context, tweets []server.Tweet) error {
	if len(tweets) == 0 {
		return nil
	}
	tx, err := d.conn.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	stmt, err := tx.PrepareContext(ctx, upsertSQL)
	if err != nil {
		return fmt.Errorf("prepare: %w", err)
	}
	defer stmt.Close()

	now := time.Now().UTC()
	for i := range tweets {
		t := &tweets[i]
		body, err := json.Marshal(t)
		if err != nil {
			return fmt.Errorf("marshal tweet %q: %w", t.ID, err)
		}
		if _, err := stmt.ExecContext(ctx,
			t.ID,
			string(t.Country),
			t.CreatedAt.UTC(),
			now,
			t.SpamScore,
			string(body),
		); err != nil {
			return fmt.Errorf("exec %q: %w", t.ID, err)
		}
	}
	return tx.Commit()
}

// Latest returns up to `limit` tweets for `country`, newest first.
// Empty list is a valid response when nothing's been ingested yet.
func (d *DB) Latest(ctx context.Context, country server.Country, limit int) ([]server.Tweet, error) {
	if limit <= 0 {
		limit = 50
	}
	rows, err := d.conn.QueryContext(ctx, latestSQL, string(country), limit)
	if err != nil {
		return nil, fmt.Errorf("query: %w", err)
	}
	defer rows.Close()

	out := make([]server.Tweet, 0, limit)
	for rows.Next() {
		var body string
		if err := rows.Scan(&body); err != nil {
			return nil, fmt.Errorf("scan: %w", err)
		}
		var tw server.Tweet
		if err := json.Unmarshal([]byte(body), &tw); err != nil {
			// Skip rows we can't decode rather than failing the whole
			// query — a partial feed beats no feed when the schema
			// drifts across deploys.
			continue
		}
		out = append(out, tw)
	}
	return out, rows.Err()
}

// PurgeOlderThan deletes rows ingested before `cutoff`. Called from
// the refresh loop so the SQLite file doesn't grow unbounded over the
// life of the service.
func (d *DB) PurgeOlderThan(ctx context.Context, cutoff time.Time) (int64, error) {
	res, err := d.conn.ExecContext(ctx, purgeSQL, cutoff.UTC())
	if err != nil {
		return 0, fmt.Errorf("purge: %w", err)
	}
	return res.RowsAffected()
}

func migrate(conn *sql.DB) error {
	_, err := conn.Exec(schema)
	if err != nil {
		return fmt.Errorf("migrate: %w", err)
	}
	return nil
}

const schema = `
CREATE TABLE IF NOT EXISTS tweets (
    id           TEXT PRIMARY KEY,
    country      TEXT NOT NULL,
    created_at   DATETIME NOT NULL,
    ingested_at  DATETIME NOT NULL,
    spam_score   REAL NOT NULL DEFAULT 0,
    body         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tweets_country_created
    ON tweets(country, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_ingested
    ON tweets(ingested_at);
`

const upsertSQL = `
INSERT INTO tweets (id, country, created_at, ingested_at, spam_score, body)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    country      = excluded.country,
    created_at   = excluded.created_at,
    ingested_at  = excluded.ingested_at,
    spam_score   = excluded.spam_score,
    body         = excluded.body
`

const latestSQL = `
SELECT body
FROM tweets
WHERE country = ?
ORDER BY created_at DESC
LIMIT ?
`

const purgeSQL = `DELETE FROM tweets WHERE ingested_at < ?`
