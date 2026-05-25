// Re-scores every tweet currently in the SQLite store against the
// current spam.Score() logic. By default read-only — reports what
// would drop now vs. what was dropped under the stored scores. With
// `--purge`, updates the stored spam_score for matched rows AND
// deletes rows whose new score crosses the threshold, so existing
// stale spammers immediately disappear from /tweets without waiting
// for the 24h retention purge.
//
// Usage:
//   go run ./cmd/spam-revalidate                    # diagnostic only
//   go run ./cmd/spam-revalidate --purge            # apply, default db
//   go run ./cmd/spam-revalidate --purge --db=...   # custom db
//   TWEETS_DB_PATH=/srv/tweets/tweets.sqlite ...
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"sort"
	"time"

	_ "modernc.org/sqlite"

	"github.com/omarss/workspace/tweets/internal/server"
	"github.com/omarss/workspace/tweets/internal/spam"
)

// Mirrors the default threshold in internal/feed.Loop's NewLoop().
// Kept here as a constant so this tool doesn't import the loop just
// for one number.
const threshold = 0.5

type row struct {
	id       string
	handle   string
	text     string
	place    string
	oldScore float64
	newScore float64
	contrib  map[string]float64
}

func main() {
	dbPath := flag.String("db", envDefault("TWEETS_DB_PATH", "/srv/tweets/tweets.sqlite"), "SQLite store path")
	purge := flag.Bool("purge", false, "Apply: UPDATE spam_score and DELETE rows that now cross the threshold")
	flag.Parse()

	db, err := sql.Open("sqlite", *dbPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "open:", err)
		os.Exit(1)
	}
	defer db.Close()
	ctx := context.Background()

	rows, err := db.QueryContext(ctx, "SELECT body FROM tweets ORDER BY created_at DESC")
	if err != nil {
		fmt.Fprintln(os.Stderr, "query:", err)
		os.Exit(1)
	}
	var all []row
	for rows.Next() {
		var body string
		if err := rows.Scan(&body); err != nil {
			continue
		}
		var tw server.Tweet
		if err := json.Unmarshal([]byte(body), &tw); err != nil {
			continue
		}
		ns, contrib := spam.Score(spam.Compute(tw.Text, time.Time{}, 0, 0, false))
		all = append(all, row{
			id:       tw.ID,
			handle:   tw.Handle,
			text:     tw.Text,
			place:    tw.Place,
			oldScore: tw.SpamScore,
			newScore: ns,
			contrib:  contrib,
		})
	}
	_ = rows.Close()

	var newDrops, oldDrops, both []row
	for _, r := range all {
		oldOver := r.oldScore >= threshold
		newOver := r.newScore >= threshold
		switch {
		case newOver && !oldOver:
			newDrops = append(newDrops, r)
		case oldOver && !newOver:
			oldDrops = append(oldDrops, r)
		case oldOver && newOver:
			both = append(both, r)
		}
	}
	sort.Slice(newDrops, func(i, j int) bool { return newDrops[i].newScore > newDrops[j].newScore })

	fmt.Printf("Total tweets in store: %d\n", len(all))
	fmt.Printf("  would now drop (new ≥%.1f, old <%.1f): %d\n", threshold, threshold, len(newDrops))
	fmt.Printf("  would have dropped (old, no longer):  %d\n", len(oldDrops))
	fmt.Printf("  still dropped on both:                 %d\n\n", len(both))

	fmt.Printf("=== Newly caught spam (new score ≥ %.1f) ===\n", threshold)
	for i, r := range newDrops {
		fmt.Printf("[%d] @%-20s old=%.2f new=%.2f place=%q\n", i+1, fallback(r.handle, "—"), r.oldScore, r.newScore, fallback(r.place, "—"))
		fmt.Printf("    contrib: %v\n", r.contrib)
		t := r.text
		if len(t) > 180 {
			t = t[:180] + "…"
		}
		fmt.Printf("    text: %s\n\n", t)
	}

	if !*purge {
		fmt.Println("(diagnostic only — pass --purge to apply)")
		return
	}

	// Apply: delete rows whose new score crosses the threshold, and
	// update spam_score on the rest so /tweets serves accurate
	// borderline scores. Single transaction — partial apply is worse
	// than no apply.
	deleteIDs := make([]string, 0, len(newDrops))
	for _, r := range newDrops {
		deleteIDs = append(deleteIDs, r.id)
	}
	updates := make([]row, 0)
	for _, r := range all {
		// Skip the ones we're about to delete; only update survivors
		// whose new score differs from what's stored.
		if r.newScore >= threshold {
			continue
		}
		if approxEqual(r.oldScore, r.newScore) {
			continue
		}
		updates = append(updates, r)
	}

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		fmt.Fprintln(os.Stderr, "begin:", err)
		os.Exit(1)
	}
	defer func() { _ = tx.Rollback() }()

	for _, id := range deleteIDs {
		if _, err := tx.ExecContext(ctx, "DELETE FROM tweets WHERE id = ?", id); err != nil {
			fmt.Fprintln(os.Stderr, "delete:", err)
			os.Exit(1)
		}
	}
	// Score is stored both as its own column AND inside the body JSON.
	// Update both — the HTTP handler reads the body JSON to populate
	// the wire `spam_score` field. Use sqlite's json_patch via
	// json_set so we don't have to re-marshal in Go.
	for _, r := range updates {
		_, err := tx.ExecContext(ctx, `
			UPDATE tweets
			SET spam_score = ?,
			    body = json_set(body, '$.spam_score', ?)
			WHERE id = ?`,
			r.newScore, r.newScore, r.id,
		)
		if err != nil {
			fmt.Fprintln(os.Stderr, "update:", r.id, err)
			os.Exit(1)
		}
	}
	if err := tx.Commit(); err != nil {
		fmt.Fprintln(os.Stderr, "commit:", err)
		os.Exit(1)
	}
	fmt.Printf("\n=== Applied: deleted %d, updated %d ===\n", len(deleteIDs), len(updates))
}

func envDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func fallback(s, alt string) string {
	if s == "" {
		return alt
	}
	return s
}

func approxEqual(a, b float64) bool {
	if a > b {
		return a-b < 0.0001
	}
	return b-a < 0.0001
}
