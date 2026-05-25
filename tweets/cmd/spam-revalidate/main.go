// One-shot tool that re-scores every tweet currently in the SQLite store
// against the new spam.Score() logic and reports what would drop. Read-only;
// the live service overwrites stored scores on the next scrape anyway.
//
// Usage:
//   go run ./cmd/spam-revalidate    # reads /srv/tweets/tweets.sqlite
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"time"

	_ "modernc.org/sqlite"

	"github.com/omarss/workspace/tweets/internal/server"
	"github.com/omarss/workspace/tweets/internal/spam"
)

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
	dbPath := "/srv/tweets/tweets.sqlite"
	if v := os.Getenv("TWEETS_DB_PATH"); v != "" {
		dbPath = v
	}
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "open:", err)
		os.Exit(1)
	}
	defer db.Close()

	rows, err := db.QueryContext(context.Background(),
		"SELECT body FROM tweets ORDER BY created_at DESC")
	if err != nil {
		fmt.Fprintln(os.Stderr, "query:", err)
		os.Exit(1)
	}
	defer rows.Close()

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
	fmt.Printf("  would have dropped (old, no longer): %d\n", len(oldDrops))
	fmt.Printf("  still dropped on both:                %d\n\n", len(both))

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

	if len(oldDrops) > 0 {
		fmt.Printf("=== False positives removed by the new logic ===\n")
		for _, r := range oldDrops {
			fmt.Printf("@%-20s old=%.2f new=%.2f: %.120s\n", fallback(r.handle, "—"), r.oldScore, r.newScore, r.text)
		}
	}
}

func fallback(s, alt string) string {
	if s == "" {
		return alt
	}
	return s
}
