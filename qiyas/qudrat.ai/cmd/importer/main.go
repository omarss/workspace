// Command importer is a one-shot job that reads question JSON files from
// QUDRAT_QUESTIONS_DIR and inserts each item into the qudrat database.
//
// It is idempotent: items are keyed by their normalized_text_hash column,
// so re-running the importer skips already-imported questions and prints
// the per-file accepted/skipped/failed counts.
//
// JSON shape (matches what the sibling generation pipeline emits):
//
//	[
//	  {
//	    "exam_type": "qudurat",
//	    "section": "kammi" | "lafzhi",
//	    "subject": "...",
//	    "grade_level": "ثانوي",
//	    "unit_or_topic": "...",
//	    "skill": "...",
//	    "cognitive_level": "...",
//	    "difficulty": "easy|medium|hard",
//	    "question_archetype": "...",
//	    "question_text": "...",
//	    "choices": [{"key":"A","text":"..."}, ... 4 items],
//	    "correct_answer": "A|B|C|D",
//	    "explanation": "...",
//	    "distractor_rationales": {"A":"...","B":"...","C":"...","D":"..."},
//	    "estimated_time_seconds": 60,
//	    "concept_fingerprint": "...",
//	    "solution_fingerprint": "...",
//	    "surface_fingerprint": "...",
//	    "novelty_notes": "...",
//	    "tags": ["..."]
//	  },
//	  ...
//	]
//
// section, grade_level, and difficulty are mapped to the canonical strings
// used in the items table CHECK constraints.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/omarss/qudrat/internal/config"
	"github.com/omarss/qudrat/internal/items"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	if err := run(logger); err != nil {
		logger.Error("importer fatal", "err", err)
		os.Exit(1)
	}
}

func run(logger *slog.Logger) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	pool, err := pgxpool.New(ctx, cfg.DatabaseDSN)
	if err != nil {
		return fmt.Errorf("pgxpool: %w", err)
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		return fmt.Errorf("pg ping: %w", err)
	}

	files, err := discoverQuestionFiles(cfg.QuestionsDir)
	if err != nil {
		return fmt.Errorf("discover: %w", err)
	}
	if len(files) == 0 {
		return fmt.Errorf("no question files under %s", cfg.QuestionsDir)
	}
	sort.Strings(files)

	var totalAccepted, totalSkipped, totalFailed int
	for _, file := range files {
		accepted, skipped, failed, err := importFile(ctx, pool, file, logger)
		if err != nil {
			logger.Error("import file", "file", file, "err", err)
			return err
		}
		logger.Info("imported", "file", filepath.Base(file),
			"accepted", accepted, "skipped", skipped, "failed", failed)
		totalAccepted += accepted
		totalSkipped += skipped
		totalFailed += failed
	}
	logger.Info("import done", "files", len(files),
		"accepted", totalAccepted, "skipped", totalSkipped, "failed", totalFailed)
	return nil
}

type rawChoice struct {
	Key  string `json:"key"`
	Text string `json:"text"`
}

type rawQuestion struct {
	ExamType             string            `json:"exam_type"`
	Section              string            `json:"section"`
	Subject              string            `json:"subject"`
	GradeLevel           string            `json:"grade_level"`
	UnitOrTopic          string            `json:"unit_or_topic"`
	Skill                string            `json:"skill"`
	CognitiveLevel       string            `json:"cognitive_level"`
	Difficulty           string            `json:"difficulty"`
	QuestionArchetype    string            `json:"question_archetype"`
	QuestionText         string            `json:"question_text"`
	Choices              []rawChoice       `json:"choices"`
	CorrectAnswer        string            `json:"correct_answer"`
	Explanation          string            `json:"explanation"`
	DistractorRationales map[string]string `json:"distractor_rationales"`
	EstimatedTimeSeconds int               `json:"estimated_time_seconds"`
	ConceptFingerprint   string            `json:"concept_fingerprint"`
	SolutionFingerprint  string            `json:"solution_fingerprint"`
	SurfaceFingerprint   string            `json:"surface_fingerprint"`
	NoveltyNotes         string            `json:"novelty_notes"`
	Tags                 []string          `json:"tags"`
}

// discoverQuestionFiles walks root recursively and returns every *.json
// path that looks like a question batch — i.e. a JSON array whose first
// element has a "question_text" field. Internal pipeline files (state
// snapshots, dedup indexes, etc. living under `_state/` or any other
// underscore-prefixed directory) are skipped, as are non-array files.
//
// This keeps the importer robust against the question repo reshuffling its
// layout (waves, batches, sub-topics) — anything that quacks like a
// question array gets imported.
func discoverQuestionFiles(root string) ([]string, error) {
	var out []string
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if d.IsDir() {
			// Skip pipeline-internal dirs (e.g. `_state` holds the dedup index).
			// Underscore-prefixed names are conventionally "not user content"
			// in many repos — but we want `_waves/` (which IS content), so
			// only exclude `_state` explicitly. Add others as the pipeline grows.
			if filepath.Base(path) == "_state" {
				return fs.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(strings.ToLower(d.Name()), ".json") {
			return nil
		}
		if !looksLikeQuestionFile(path) {
			return nil
		}
		out = append(out, path)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return out, nil
}

// looksLikeQuestionFile peeks at the file: is it a JSON array whose first
// element has a "question_text" key? Cheap shape check to keep us from
// trying to insert dedup indexes or other pipeline metadata.
func looksLikeQuestionFile(path string) bool {
	raw, err := os.ReadFile(path) //nolint:gosec // operator-supplied path is trusted
	if err != nil {
		return false
	}
	var probe []map[string]json.RawMessage
	if err := json.Unmarshal(raw, &probe); err != nil {
		return false
	}
	if len(probe) == 0 {
		return false
	}
	_, ok := probe[0]["question_text"]
	return ok
}

// importFile loads a single .json file, normalizes each question, and runs
// every insert in one transaction so a partial failure leaves no orphaned
// rows. Already-imported items (matched on normalized_text_hash) are
// skipped, not failed — this keeps re-runs idempotent.
func importFile(ctx context.Context, pool *pgxpool.Pool, path string, logger *slog.Logger) (int, int, int, error) {
	raw, err := os.ReadFile(path) //nolint:gosec // operator-supplied path is trusted
	if err != nil {
		return 0, 0, 0, fmt.Errorf("read file: %w", err)
	}
	var batch []rawQuestion
	if err := json.Unmarshal(raw, &batch); err != nil {
		return 0, 0, 0, fmt.Errorf("unmarshal: %w", err)
	}

	tx, err := pool.Begin(ctx)
	if err != nil {
		return 0, 0, 0, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var accepted, skipped, failed int
	for i, q := range batch {
		// SAVEPOINT per row so a single bad row (constraint violation,
		// duplicate, malformed taxonomy) only loses itself instead of
		// poisoning the entire batch — Postgres aborts the whole tx on
		// any unhandled error otherwise.
		spName := fmt.Sprintf("sp_%d", i)
		if _, err := tx.Exec(ctx, "SAVEPOINT "+spName); err != nil {
			return 0, 0, 0, fmt.Errorf("savepoint: %w", err)
		}
		switch err := insertOne(ctx, tx, q); {
		case err == nil:
			accepted++
			if _, err := tx.Exec(ctx, "RELEASE SAVEPOINT "+spName); err != nil {
				return 0, 0, 0, fmt.Errorf("release savepoint: %w", err)
			}
		case errors.Is(err, errAlreadyImported):
			skipped++
			if _, err := tx.Exec(ctx, "RELEASE SAVEPOINT "+spName); err != nil {
				return 0, 0, 0, fmt.Errorf("release savepoint: %w", err)
			}
		default:
			failed++
			logger.Warn("question failed", "file", filepath.Base(path), "idx", i, "err", err)
			if _, rbErr := tx.Exec(ctx, "ROLLBACK TO SAVEPOINT "+spName); rbErr != nil {
				return 0, 0, 0, fmt.Errorf("rollback to savepoint: %w", rbErr)
			}
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, 0, 0, fmt.Errorf("commit tx: %w", err)
	}
	return accepted, skipped, failed, nil
}

var errAlreadyImported = errors.New("item already imported (normalized_text_hash collision)")

func insertOne(ctx context.Context, tx pgx.Tx, q rawQuestion) error {
	if len(q.Choices) != 4 {
		return fmt.Errorf("expected 4 choices, got %d", len(q.Choices))
	}

	section := mapSection(q.Section)
	difficulty := mapDifficulty(q.Difficulty)
	gradeLevel := mapGradeLevel(q.GradeLevel)
	cognitive := mapCognitive(q.CognitiveLevel)
	if section == "" || difficulty == "" || cognitive == "" {
		return fmt.Errorf("invalid taxonomy: section=%q diff=%q cog=%q", q.Section, q.Difficulty, q.CognitiveLevel)
	}
	if q.CorrectAnswer != "A" && q.CorrectAnswer != "B" && q.CorrectAnswer != "C" && q.CorrectAnswer != "D" {
		return fmt.Errorf("invalid correct_answer %q", q.CorrectAnswer)
	}

	choices := orderedChoices(q.Choices)
	stemHash := items.Hash(q.QuestionText)
	choicesHash := items.HashChoices(choices["A"], choices["B"], choices["C"], choices["D"])
	normalizedHash := items.Hash(q.QuestionText + "\x1f" + choices["A"] + "\x1f" + choices["B"] + "\x1f" + choices["C"] + "\x1f" + choices["D"])

	estimated := q.EstimatedTimeSeconds
	if estimated <= 0 {
		estimated = 60
	}

	const insertItem = `
INSERT INTO items (
    status, exam_type, section, subject, grade_level, unit, topic, skill,
    cognitive_level, difficulty_target, question_archetype,
    question_text, correct_answer, explanation, estimated_time_seconds,
    concept_fingerprint, solution_fingerprint, surface_fingerprint,
    normalized_text_hash, stem_hash, choices_hash,
    source, novelty_notes
)
VALUES (
    'accepted', $1, $2, $3, $4, $5, $5, $6,
    $7, $8, $9,
    $10, $11, $12, $13,
    $14, $15, $16,
    $17, $18, $19,
    'llm_generated', $20
)
ON CONFLICT (normalized_text_hash) DO NOTHING
RETURNING id
`
	var itemID string
	row := tx.QueryRow(ctx, insertItem,
		q.ExamType, section, q.Subject, gradeLevel, q.UnitOrTopic, q.Skill,
		cognitive, difficulty, q.QuestionArchetype,
		q.QuestionText, q.CorrectAnswer, q.Explanation, estimated,
		q.ConceptFingerprint, q.SolutionFingerprint, q.SurfaceFingerprint,
		normalizedHash, stemHash, choicesHash,
		q.NoveltyNotes,
	)
	if err := row.Scan(&itemID); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return errAlreadyImported
		}
		return fmt.Errorf("insert item: %w", err)
	}

	for _, key := range []string{"A", "B", "C", "D"} {
		if _, err := tx.Exec(ctx,
			`INSERT INTO item_choices (item_id, choice_key, choice_text, distractor_rationale) VALUES ($1, $2, $3, $4)`,
			itemID, key, choices[key], q.DistractorRationales[key],
		); err != nil {
			return fmt.Errorf("insert choice %s: %w", key, err)
		}
	}

	for _, tag := range q.Tags {
		if tag == "" {
			continue
		}
		if _, err := tx.Exec(ctx,
			`INSERT INTO item_tags (item_id, tag) VALUES ($1, $2) ON CONFLICT DO NOTHING`,
			itemID, tag,
		); err != nil {
			return fmt.Errorf("insert tag %q: %w", tag, err)
		}
	}
	return nil
}

// orderedChoices returns A→D text by key. Missing keys map to empty string,
// which the table's NOT NULL would reject — caller must validate the choice
// count first.
func orderedChoices(in []rawChoice) map[string]string {
	out := map[string]string{"A": "", "B": "", "C": "", "D": ""}
	for _, c := range in {
		if _, ok := out[c.Key]; ok {
			out[c.Key] = c.Text
		}
	}
	return out
}

// mapSection canonicalizes the section enum the JSON uses onto the strings
// stored in items.section. The JSON pipeline emits at least three styles:
//
//   - Qudurat: "kammi" / "lafzhi" (Arabic-Latinized).
//   - Tahsili: "scientific" (the Tahsili scientific track is one section).
//   - Already canonical: "quantitative" / "verbal" / "scientific".
//
// Anything else passes through verbatim — items.section is plain text and
// the table doesn't constrain values.
func mapSection(s string) string {
	switch s {
	case "kammi":
		return "quantitative"
	case "lafzhi":
		return "verbal"
	case "":
		return ""
	default:
		return s
	}
}

func mapDifficulty(d string) string {
	switch d {
	case "easy", "medium", "hard":
		return d
	default:
		return ""
	}
}

// mapCognitive canonicalizes the cognitive_level field onto the items
// table's CHECK enum. The pipeline emits a mix of English (canonical),
// English Bloom synonyms, and Arabic translations:
//
//   - canonical: recall / understanding / application / analysis / inference
//   - Bloom synonyms: knowledge → recall, comprehension → understanding,
//     synthesis / evaluation → analysis
//   - Arabic: استرجاع / فهم / تطبيق / تحليل / استنتاج
func mapCognitive(c string) string {
	switch c {
	case "recall", "understanding", "application", "analysis", "inference":
		return c
	case "knowledge", "استرجاع", "تذكر", "استدعاء":
		return "recall"
	case "comprehension", "فهم":
		return "understanding"
	case "تطبيق":
		return "application"
	case "synthesis", "evaluation", "تحليل":
		return "analysis"
	case "استنتاج", "استدلال":
		return "inference"
	default:
		return ""
	}
}

// mapGradeLevel collapses the various grade strings the JSON might carry
// onto the items table's expected canonical values.
func mapGradeLevel(g string) string {
	switch g {
	case "ثانوي", "secondary", "general", "":
		return "general"
	default:
		return g
	}
}
