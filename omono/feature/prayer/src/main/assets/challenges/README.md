# Fajr dismiss challenges

JSON pool consumed by the anti-snooze gate. On Fajr, when the user has
enabled "Hard wake", the athan keeps playing until they get 3
multiple-choice questions correct *in a row*.

## File format

Every `*.json` in this directory is loaded at startup and concatenated
into a single pool. Two accepted shapes:

    { "challenges": [ … ] }      # preferred — documents the schema
    [ { … }, { … }, … ]          # also accepted

Each entry:

    {
      "id":       "sat-math-001",         // unique string across all files
      "category": "Sat" | "Qiyas" | "Math",
      "stem":     "If 3x − 7 = 2x + 5, what is x?",
      "options":  ["-2", "5", "12", "-12"],
      "correct":  2,                      // zero-based index
      "explanation": "Subtract 2x: x = 12."   // optional but recommended
    }

Rules the loader enforces (see `ChallengeRepository.kt`):

* `id`, `category`, `stem` must be present and non-empty.
* `category` must be one of the exact strings `Sat`, `Qiyas`, `Math`.
* `options` must have 2–6 entries, each non-empty.
* `correct` must be in `options`' bounds.

Malformed entries are skipped with a warning; the rest of the file
still loads.

## Expanding to 1000+ per category

The 52-question starter pool is enough for the gate to feel non-
repetitive for a few weeks, but you'll want more eventually.

### Path A: LLM-generated batches (fastest)

1. Drop source material for the category into a prompt (e.g.
   `curl https://collegeboard.org/... | extract-text`, Khan Academy
   OpenStax AP-prep PDFs, Qiyas official sample sheets).
2. Run a small script against the Claude API that takes the material
   and returns `{ "challenges": [ … ] }` matching this schema.
   Recommended prompt shape:

       You are producing Qiyas-style multiple-choice questions.
       Source material: <paste>
       Return JSON matching this schema: <paste the schema above>.
       Generate 50 questions. Calibrate difficulty to medium-hard.
       Each question must have exactly one correct option.

3. Drop the resulting JSON file in this directory.

Budget: ~$3 per 100 questions on Claude Opus 4.7 at mid-2026 rates.
Budget for the full target (3000 questions) is roughly $90.

### Path B: Port open question banks

* OpenStax AP Calculus / Precalculus / Algebra exercise sets are
  CC-BY; their question banks convert cleanly to this schema.
* Khan Academy publishes exercise frames under CC-BY-NC-SA — usable
  for a personal sideload but avoid distributing derived JSON.
* Qiyas / GAT official sample PDFs are copyrighted by Etec; do not
  redistribute. Use them to seed the LLM prompt only.

### Path C: Hand-curation

A steady 20 questions / hour is sustainable; 3000 questions = 150
hours. Not recommended unless you enjoy question-writing as a hobby.

## Adding new categories

The `ChallengeCategory` enum in `feature/prayer/Challenge.kt` is the
source of truth. Add an entry, re-compile, update
`parseChallenge` is already tolerant of the new value.
