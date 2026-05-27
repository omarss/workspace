# MVP scope audit — Surveys + Newsletters

Phase 16 §16.5 confirmation.

## Method

```bash
$ git grep -i "survey" -- . ':!docs/' ':!AGENTS.md' ':!docs/plans/'
$ git grep -i "newsletter" -- . ':!docs/' ':!AGENTS.md' ':!docs/plans/'
$ ls internal/dataplane/newsletters internal/dataplane/surveys
```

## Result

### Surveys

```
(no output)
```

No reference to "survey" or "Surveys" anywhere outside the docs/AGENTS layer.
The non-goal in AGENTS.md §28 (line 2219) is honoured.

### Newsletters

The only hit is in a guard test:

```
cmd/saasctl/recipe_test.go:84   // AGENTS.md §15 lists the explicit MVP scope cuts. Recipes must
cmd/saasctl/recipe_test.go:85   // not promise these — they are out of MVP scope and will mislead
cmd/saasctl/recipe_test.go:86   // callers if the recipe says "use newsletters/files/webhooks".
cmd/saasctl/recipe_test.go:87   deferred := []string{
cmd/saasctl/recipe_test.go:88       "newsletters",
```

This is an **enforcement** test: it asserts that no recipe document under
`docs/recipes/` mentions "newsletters" (or "upload a file", "register a
webhook endpoint", "feature flags", "usage metering"). The MVP recipe set
passes this guard.

### Module directories

```
$ ls internal/dataplane/newsletters internal/dataplane/surveys 2>&1
ls: cannot access 'internal/dataplane/newsletters': No such file or directory
ls: cannot access 'internal/dataplane/surveys': No such file or directory
```

Both absent. Confirmed.

## Verdict

**PASS** — no Surveys code present (non-goal per AGENTS.md §28). No
Newsletters code present (deferred to v1 per `docs/v1-roadmap.md` item #1).
The CI guard test in `cmd/saasctl/recipe_test.go` keeps the recipes set
honest as new recipes are added.
