// magic-audit prints every tweet in the local store that the magic
// query would currently return, ranked by event_score then created_at.
// Used to eyeball the curated keyword set for spam / junk leaks
// before shipping. Read-only — never modifies the store.
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	_ "modernc.org/sqlite"

	"github.com/omarss/workspace/tweets/internal/query"
	"github.com/omarss/workspace/tweets/internal/server"
)

// Keep this in sync with internal/server.magicQueryString.
const magicQueryString = `(` +
	`(` +
	`(` +
	`ai OR llm OR gpt OR claude OR chatgpt OR openai OR ` +
	`hackathon OR developer OR programming OR coding OR engineer OR ` +
	`devops OR kubernetes OR python OR golang OR rust OR ` +
	`blockchain OR web3 OR fintech OR ` +
	`"machine learning" OR "deep learning" OR "data science" OR ` +
	`ذكاء OR برمجة OR هاكاثون OR مبرمج OR مطور OR ` +
	`"تطوير برمجيات" OR "هندسة برمجيات" OR "علوم الحاسب" OR ` +
	`"تعلم آلي" OR "الذكاء الاصطناعي" OR "تقنية مالية"` +
	`) AND (` +
	`event OR conference OR workshop OR meetup OR webinar OR ` +
	`bootcamp OR summit OR expo OR talks OR registration OR enroll OR ` +
	`فعالية OR مؤتمر OR ورشة OR ندوة OR تسجيل OR حضور OR اكسبو OR ` +
	`ملتقى OR تجمع OR لقاء OR مناظرة` +
	`)` +
	`)` +
	` OR (` +
	`concert OR festival OR ticket OR tickets OR ` +
	`marathon OR tournament OR ` +
	`حفل OR مهرجان OR تذاكر OR بطولة OR افتتاح` +
	`)` +
	` OR (` +
	`"vision 2030" OR "saudi vision" OR ipo OR "venture capital" OR ` +
	`"series a" OR "series b" OR funding OR raised OR ` +
	`"رؤية 2030" OR "ريادة أعمال" OR "تمويل جولة" OR ` +
	`"الاقتصاد الرقمي" OR "تحول رقمي" OR "خدمات مالية رقمية"` +
	`)` +
	` OR (` +
	`(` +
	`scholarship OR scholarships OR fellowship OR fellowships OR ` +
	`internship OR internships OR ` +
	`opportunity OR opportunities OR ` +
	`منحة OR منح OR فرصة OR فرص OR زمالة OR تدريب` +
	`) AND (` +
	`apply OR register OR deadline OR ` +
	`تقديم OR قدم OR تسجيل OR موعد` +
	`)` +
	`)` +
	` OR (` +
	`conference OR conferences OR symposium OR forum OR keynote OR ` +
	`summit OR meetup OR meetups OR ` +
	`lecture OR lectures OR seminar OR seminars OR masterclass OR ` +
	`مؤتمر OR منتدى OR قمة OR ملتقى OR ندوة OR اكسبو OR ` +
	`محاضرة OR محاضرات OR ورشة` +
	`)` +
	` OR (` +
	`"blog post" OR "case study" OR newsletter OR ` +
	`مقال OR مقالات OR تدوينة OR مدونة` +
	`)` +
	`)` +
	` AND NOT (` +
	`"earn daily" OR "earning daily" OR "basic income" OR ` +
	`"passive income" OR "make money online" OR "join here" OR ` +
	`"win up to" OR "real impact i" OR ` +
	`"اربح يومي" OR "كسب يومي" OR "دخل سلبي"` +
	`)`

type match struct {
	tw      server.Tweet
	matched string // shortened body for printing
}

func main() {
	dbPath := flag.String("db", "/srv/tweets/tweets.sqlite", "SQLite store path")
	maxOut := flag.Int("limit", 200, "max matches to print")
	flag.Parse()

	expr, err := query.Parse(magicQueryString)
	if err != nil {
		fmt.Fprintf(os.Stderr, "magic parse failed: %v\n", err)
		os.Exit(2)
	}
	conn, err := sql.Open("sqlite", *dbPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "open db: %v\n", err)
		os.Exit(2)
	}
	defer conn.Close()

	rows, err := conn.QueryContext(context.Background(), "SELECT body FROM tweets")
	if err != nil {
		fmt.Fprintf(os.Stderr, "query: %v\n", err)
		os.Exit(2)
	}
	defer rows.Close()

	var matches []match
	total := 0
	dupDrops := 0
	spamDrops := 0
	seen := make(map[string]bool)
	for rows.Next() {
		var body string
		if err := rows.Scan(&body); err != nil {
			continue
		}
		var tw server.Tweet
		if err := json.Unmarshal([]byte(body), &tw); err != nil {
			continue
		}
		total++
		if !expr.Matches(strings.ToLower(tw.Text)) {
			continue
		}
		if tw.SpamScore > 0.25 {
			spamDrops++
			continue
		}
		// Cross-tick dedup by (handle, normalized body).
		norm := strings.ToLower(strings.TrimSpace(tw.Text))
		norm = strings.ReplaceAll(norm, "\n", " ")
		// Strip URL-like substrings cheaply.
		for {
			i := strings.Index(norm, "http")
			if i < 0 {
				break
			}
			j := strings.IndexAny(norm[i:], " \t")
			if j < 0 {
				norm = norm[:i]
				break
			}
			norm = norm[:i] + norm[i+j:]
		}
		dupKey := tw.Handle + "|" + norm
		if tw.Handle != "" && seen[dupKey] {
			dupDrops++
			continue
		}
		seen[dupKey] = true
		matches = append(matches, match{
			tw:      tw,
			matched: strings.ReplaceAll(strings.TrimSpace(tw.Text), "\n", " "),
		})
	}
	sort.SliceStable(matches, func(i, j int) bool {
		if matches[i].tw.EventScore != matches[j].tw.EventScore {
			return matches[i].tw.EventScore > matches[j].tw.EventScore
		}
		return matches[i].tw.CreatedAt.After(matches[j].tw.CreatedAt)
	})
	fmt.Printf("=== Magic audit ===\n")
	fmt.Printf("store: %d\n", total)
	fmt.Printf("matches kept: %d (spam-dropped: %d, dup-dropped: %d)\n",
		len(matches), spamDrops, dupDrops)

	fmt.Println()
	for i, m := range matches {
		if i >= *maxOut {
			fmt.Printf("(showing first %d of %d)\n", *maxOut, len(matches))
			break
		}
		txt := m.matched
		if len([]rune(txt)) > 200 {
			txt = string([]rune(txt)[:200]) + "…"
		}
		age := time.Since(m.tw.CreatedAt).Round(time.Minute)
		fmt.Printf("[%d] ev=%.2f spam=%.2f age=%s place=%q\n     @%s — %s\n",
			i+1, m.tw.EventScore, m.tw.SpamScore, age,
			m.tw.Place, m.tw.Handle, txt)
	}
}
