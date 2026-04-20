# mcqs

MCQ generation API over [vrtx-ai/docs-bundle](/home/omar/workspace/vrtx-ai/docs-bundle).

Each top-level subject directory becomes a row in `subjects`, is chunked into
`doc_chunks`, and fed to Claude Sonnet 4.6 in batches to produce multiple-
choice questions in three styles: **knowledge** (recall), **analytical**
(trade-offs / why), and **problem-solving** (scenario → action). A round
targets ≥100 questions per (subject, type); later rounds layer on more.

The API surface lives at `api.omarss.net/v1/mcq/…` and shares the single-key
`X-Api-Key` pattern with [gplaces_parser](../gplaces_parser). See
`.env.example` for required variables and `make help` for the full command
list.
