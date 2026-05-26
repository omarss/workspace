package server

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/omarss/workspace/tweets/internal/query"
)

// FeedSource produces the current feed for a request. The Android-facing
// handler is decoupled from how the tweets are actually fetched —
// scraper, fixtures, and the SQLite cache all implement the same
// interface so the handler stays trivial.
type FeedSource interface {
	Feed(ctx context.Context, req FeedRequest) (FeedResult, error)
}

// FeedResult is what a FeedSource returns. NextCursor (when non-zero)
// is the timestamp the handler echoes back so the client can paginate.
type FeedResult struct {
	Tweets     []Tweet
	NextCursor time.Time
}

// ErrUnknownCountry is returned when a caller asks for a feed the
// configured source doesn't recognise. Mapped to HTTP 400 at the edge.
var ErrUnknownCountry = errors.New("unknown country")

// Server wires the FeedSource into an HTTP mux.
type Server struct {
	source FeedSource
	log    *slog.Logger
}

func New(source FeedSource, log *slog.Logger) *Server {
	if log == nil {
		log = slog.Default()
	}
	return &Server{source: source, log: log}
}

func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.health)
	mux.HandleFunc("GET /tweets", s.tweets)
	return mux
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, HealthResponse{Status: "ok"})
}

// tweets handles GET /tweets with the following query parameters:
//
//   country   comma-separated country codes (default "ksa"). Each must
//             be a known Country; unknown → 400.
//   city      comma-separated case-insensitive substrings to match
//             against tweet.place. Empty → no city filter.
//   q         free-text keyword expression. Supports `AND`, `OR`,
//             parentheses, and "quoted phrases"; whitespace-adjacent
//             terms default to AND. Empty → no keyword filter.
//             Capped to 200 chars and stripped of unsafe wildcard
//             metachars. Invalid expressions → 400.
//   magic     `1` → swap the user's `q` (if any) for the server's
//             curated "interesting to me" preset. Currently surfaces
//             tech / AI / dev events + local concerts + festivals.
//   cursor    RFC3339 timestamp. Tweets older than this returned.
//             Empty → first page (event-first sort).
//   limit     int, default 60, capped at 200.
//
// Back-compat note: the old single-country `?country=ksa` form still
// works because the comma-split returns a single-element slice.
func (s *Server) tweets(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	req, err := parseFeedRequest(q)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	result, err := s.source.Feed(r.Context(), req)
	if err != nil {
		if errors.Is(err, ErrUnknownCountry) {
			http.Error(w, "unknown country", http.StatusBadRequest)
			return
		}
		s.log.Error("feed lookup failed", "req", req, "err", err)
		http.Error(w, "feed unavailable", http.StatusBadGateway)
		return
	}
	resp := FeedResponse{
		Countries:   req.Countries,
		Cities:      req.Cities,
		Query:       req.Query,
		Magic:       req.Magic,
		GeneratedAt: time.Now().UTC(),
		Tweets:      result.Tweets,
	}
	if !result.NextCursor.IsZero() {
		resp.NextCursor = result.NextCursor.UTC().Format(time.RFC3339Nano)
	}
	writeJSON(w, http.StatusOK, resp)
}

// magicNotClause is appended to every disjunct so a single match
// against an MLM / pyramid / "earn $X daily" pattern overrides the
// positive signal. Cheap defense-in-depth: the spam package's new
// mlm_money_spam blocklist also catches these at ingest (score 0.7),
// so by the time magic mode reads from the store most are gone — but
// the NOT keeps any that slipped through (e.g. from a future scrape
// where the spam keywords drifted) from leaking into the curated feed.
const magicNotClause = ` AND NOT (` +
	`"earn daily" OR "earning daily" OR "basic income" OR ` +
	`"passive income" OR "make money online" OR "join here" OR ` +
	`"win up to" OR "real impact i" OR ` +
	`"اربح يومي" OR "كسب يومي" OR "دخل سلبي"` +
	`)`

// magicQueryString is the canned "interesting to me" preset triggered
// by `?magic=1`. The whole expression is:
//
//	(disjunct1 OR disjunct2 OR ... OR disjunct6) AND NOT mlmClause
//
// Four disjuncts originally; now six after the user's incremental
// additions through 2026-05-27:
//
//  1. Tech / AI / dev content that's *also* event-flavoured.
//  2. Local concerts / festivals / tournaments — passes alone.
//  3. Tech / business / fintech news — passes alone, narrow phrases.
//  4. Career / opportunity surfaces — paired with apply/register
//     verbs so generic "فرصة" usage doesn't slip through.
//
// Word-boundary matching (in package query) handles the short
// English keywords ("ai") so they don't match inside unrelated words
// like "faith" or "ego". Arabic terms keep substring semantics (so
// "ال" definite-article prefixes still match the noun).
//
// Audit-driven exclusions (2026-05-27 store):
//   - `عرض` / `موعد` / `تطوير` (alone) / `ml` / `talk` — too
//     ambiguous; see the original PR for the case-by-case rationale.
const magicQueryString = `(` +
	// 1. Tech / AI / dev AND event
	`(` +
	`(` +
	// Tech keywords
	`ai OR llm OR gpt OR claude OR chatgpt OR openai OR ` +
	`hackathon OR developer OR programming OR coding OR engineer OR ` +
	`devops OR kubernetes OR python OR golang OR rust OR ` +
	`blockchain OR web3 OR fintech OR ` +
	`"machine learning" OR "deep learning" OR "data science" OR ` +
	`ذكاء OR برمجة OR هاكاثون OR مبرمج OR مطور OR ` +
	`"تطوير برمجيات" OR "هندسة برمجيات" OR "علوم الحاسب" OR ` +
	`"تعلم آلي" OR "الذكاء الاصطناعي" OR "تقنية مالية"` +
	`) AND (` +
	// Event keywords (intersected)
	`event OR conference OR workshop OR meetup OR webinar OR ` +
	`bootcamp OR summit OR expo OR talks OR registration OR enroll OR ` +
	`فعالية OR مؤتمر OR ورشة OR ندوة OR تسجيل OR حضور OR اكسبو OR ` +
	`ملتقى OR تجمع OR لقاء OR مناظرة` +
	`)` +
	`)` +
	// 2. Local events / concerts / sport — standalone
	` OR (` +
	`concert OR festival OR ticket OR tickets OR ` +
	`marathon OR tournament OR ` +
	`حفل OR مهرجان OR تذاكر OR بطولة OR افتتاح` +
	`)` +
	// 3. Tech / business / fintech news — narrow phrases that on
	// their own carry enough news signal to be worth surfacing.
	` OR (` +
	`"vision 2030" OR "saudi vision" OR ipo OR "venture capital" OR ` +
	`"series a" OR "series b" OR funding OR raised OR ` +
	`"رؤية 2030" OR "ريادة أعمال" OR "تمويل جولة" OR ` +
	`"الاقتصاد الرقمي" OR "تحول رقمي" OR "خدمات مالية رقمية"` +
	`)` +
	// 4. Career / opportunity — pair with apply-verb so generic
	// "فرصة" doesn't pass on its own.
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
	// 5. Gatherings / meetups / conferences / lectures — standalone
	// signal. Any conference / lecture / symposium / forum / expo
	// announcement passes even without tech keywords. Matches the
	// user's explicit "tech or business news … gatherings, meetups,
	// conferences, lectures" ask.
	` OR (` +
	`conference OR conferences OR symposium OR forum OR keynote OR ` +
	`summit OR meetup OR meetups OR ` +
	`lecture OR lectures OR seminar OR seminars OR masterclass OR ` +
	`مؤتمر OR منتدى OR قمة OR ملتقى OR ندوة OR اكسبو OR ` +
	`محاضرة OR محاضرات OR ورشة` +
	`)` +
	// 6. Article / news shares — narrow content nouns. We deliberately
	// don't include generic verbs like "read more" or "اقرأ" alone
	// because crypto/MLM pyramid spam ("earn daily ... read more:
	// https://...") rides them in. The content nouns below carry
	// enough signal on their own to be worth surfacing.
	` OR (` +
	`"blog post" OR "case study" OR newsletter OR ` +
	`مقال OR مقالات OR تدوينة OR مدونة` +
	`)` +
	// Close the positive disjunction; AND NOT exclusion applies to the
	// whole thing so an MLM keyword in any matched bucket overrides.
	`)` +
	magicNotClause

// parseFeedRequest reads + validates the query string into a FeedRequest.
// Trims whitespace around each comma-separated value so curl users with
// pretty URLs aren't punished.
func parseFeedRequest(q map[string][]string) (FeedRequest, error) {
	get := func(key string) string {
		if v, ok := q[key]; ok && len(v) > 0 {
			return v[0]
		}
		return ""
	}
	req := FeedRequest{}

	countriesRaw := get("country")
	if countriesRaw == "" {
		countriesRaw = string(CountryKSA)
	}
	for _, c := range strings.Split(countriesRaw, ",") {
		c = strings.TrimSpace(c)
		if c == "" {
			continue
		}
		cc := Country(strings.ToLower(c))
		if cc != CountryKSA && cc != CountryEgypt {
			return req, errors.New("unknown country: " + c)
		}
		req.Countries = append(req.Countries, cc)
	}
	if len(req.Countries) == 0 {
		req.Countries = []Country{CountryKSA}
	}

	if v := get("city"); v != "" {
		for _, c := range strings.Split(v, ",") {
			c = strings.TrimSpace(c)
			if c != "" {
				req.Cities = append(req.Cities, c)
			}
		}
	}

	if v := get("q"); v != "" {
		// Strip the LIKE wildcards so a caller can't smuggle them into
		// the store layer's substring match (vestigial from the
		// pre-parser path; keep the safety net). Also cap length to
		// keep the parser bounded.
		v = strings.ReplaceAll(v, "%", " ")
		v = strings.ReplaceAll(v, "_", " ")
		if len(v) > 200 {
			v = v[:200]
		}
		req.Query = strings.TrimSpace(v)
	}

	if v := get("magic"); v == "1" || strings.EqualFold(v, "true") {
		req.Magic = true
		// Magic overrides any user-supplied q so the response echo
		// matches what's actually being matched. The expression is
		// resolved below in resolveQueryExpr so the curated string
		// is in one place (magicQueryString).
		req.Query = magicQueryString
	}

	if req.Query != "" {
		expr, err := query.Parse(req.Query)
		if err != nil {
			return req, errors.New("invalid q expression: " + err.Error())
		}
		req.QueryExpr = expr
	}

	if v := get("cursor"); v != "" {
		t, err := time.Parse(time.RFC3339Nano, v)
		if err != nil {
			t, err = time.Parse(time.RFC3339, v)
		}
		if err != nil {
			return req, errors.New("invalid cursor (want RFC3339): " + v)
		}
		req.Cursor = t.UTC()
	}

	if v := get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 {
			return req, errors.New("invalid limit (want positive int): " + v)
		}
		if n > 200 {
			n = 200
		}
		req.Limit = n
	}
	return req, nil
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
