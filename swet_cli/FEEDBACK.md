# SWET Web UX, Product, Feature, and UI Feedback

Date: 2026-04-03

## Review Scope

This review is based on the current web app implementation in `web/`, the relevant API routes in `src/swet_api/`, and the repository guidance in `CONVENTIONS.md` and `CLAUDE.md`.

Validation completed:

- `pnpm --dir web check`
- `pnpm --dir web build`

Both passed.

## Executive Summary

SWET already has a stronger core engine than its current web experience suggests.

The backend and product primitives are solid:

- adaptive question generation
- Bayesian calibration assessment
- per-competency difficulty adjustment
- review queue
- session mode
- bookmarks
- progress and weak-area reporting

The main problem is not lack of raw capability. The main problem is that the web app does not yet convert those capabilities into a habit-forming, clearly guided, skill-improving training loop.

Right now the web app feels like a competent internal tool for practicing questions.

It does not yet feel like a serious, intentional "Lumosity for engineers" product.

To get there, the product needs to shift from:

- question delivery

to:

- deliberate daily training
- measurable skill gains
- recall and repetition
- calibration of confidence
- focused drill design
- clear next-best action

## What Is Already Good

- The domain model is strong. The competency matrix, role mapping, stack filtering, and adaptive difficulty give the app a real foundation.
- The web information architecture is simple enough to understand quickly.
- The assessment concept is strong. Adaptive calibration is more credible than a manual difficulty selector.
- The review queue is the right idea. Engineers do improve through repeated recall and error correction.
- The question format mix is promising. MCQ, debugging, code review, short answer, and design prompts give enough range to build real drill families.
- The product is already individualized by role, language, framework, and performance.

## Critical Current Gaps

These are not just "nice improvements." They materially limit the usefulness of the current web experience.

### 1. Targeted practice is mostly broken

The UI implies focused training by competency and difficulty, but the train flow does not actually honor those inputs in a meaningful way.

Current examples:

- Today links weak-area practice via `/train?competency=...`
- Progress links weak-area practice via `/train?competency=...`
- Review links "Review Now" via `/train?question_id=...`
- Grade reveal links "Easier Version", "Harder Version", and "Same Topic"

But the train page just starts a generic session based on count. The session API only accepts `count`. The selected competency, difficulty, and question ID are effectively discarded.

Impact:

- the product promises precision but behaves generically
- the user cannot trust follow-up actions
- weak-area practice is not actually weak-area practice

### 2. The review system is underused on web

The backend already has a real review completion model using spaced repetition quality scoring.

The web page does not expose the core loop. It mostly acts as a queue viewer with:

- snooze
- dismiss
- a broken "Review Now" handoff

What is missing:

- answer-from-memory flow
- reveal and compare flow
- quality grading: Again / Hard / Good / Easy
- visible next review date
- review streaks and retention metrics

Impact:

- one of the best learning mechanisms in the product is not actually surfaced as a learning experience

### 3. Confidence is captured in UI but not productized

The question UI lets the user mark confidence.

But this signal is not effectively used end to end:

- Today answer submission does not pass confidence
- Train answer submission does not pass confidence
- attempts are not saved with confidence despite schema support
- the product shows no calibration analytics

Impact:

- SWET is missing one of the highest-value signals for engineering growth: confident but wrong, or hesitant but correct

### 4. Session UX has a correctness problem

In the train flow, the grade view can become associated with the next question instead of the just-answered question because the page updates `currentQuestion` before grade reveal is displayed.

Impact:

- feedback can become contextually confusing
- this erodes trust in the training flow

### 5. Onboarding is too heavy and too dry

The first-run flow is:

- route redirect
- login/register
- setup wizard
- full assessment

This is too much friction before the user experiences a win.

What is missing:

- a proper landing page
- value framing
- proof of benefit
- a "start in 3 minutes" option
- a learn-as-you-go path

Impact:

- conversion risk is high
- assessment can feel like homework before value is established

### 6. Today is a hub, not a coach

The Today page shows stats and action cards, but it does not behave like a training coach.

It should answer:

- what should I do right now
- why this matters
- what skill this improves
- how long it will take
- what payoff I should expect

Today currently feels informational. It should feel directive.

### 7. Progress is descriptive, not instructional

The current progress page has:

- streak
- total attempts
- average score
- activity calendar
- weak areas
- competency levels
- format performance
- history

What it does not have:

- trend over time
- movement by competency
- benchmark interpretation
- confidence intervals
- overconfidence analysis
- recommended next drill
- weekly summary
- improvement narratives

Impact:

- the user sees data, but not insight

### 8. Bookmarks are not a first-class part of the product

Bookmarks exist as a control in the grade screen, but there is no dedicated "saved drills" or "library" experience in the web app.

Impact:

- saved content has low discoverability
- users cannot build their own practice bank

### 9. The current visual language is too generic

The UI is clean, but it reads like a standard dark productivity dashboard:

- near-black background
- cyan accent
- Inter + JetBrains Mono
- repetitive card layout

This is safe, but not memorable. It does not feel like a premium training product.

### 10. The product is still question-centric, not drill-centric

As long as the product is framed around "questions," it will feel like test prep.

To become meaningfully useful for engineers, the product should be framed around drills that improve real engineering judgment under constraints.

## Product Direction: "Lumosity for Engineers"

The best direction is:

- daily prescribed workouts
- short, focused drills
- adaptive difficulty
- memory reinforcement
- confidence calibration
- visible skill deltas
- long-term mastery map

The product should feel like cognitive training for engineers, not just interview practice.

## Core Product Principles

### 1. One dominant next action

Every visit should make the next action obvious.

Ideal behavior:

- open app
- see today's workout
- start immediately
- finish
- review misses
- see skill delta

### 2. Fast feedback loops

Most exercises should be solvable in 60 to 180 seconds.

Longer system design or architecture drills can exist, but the daily loop should optimize for momentum and repetition.

### 3. Visible improvement

The user should feel improvement in:

- debugging
- code review
- design tradeoffs
- communication precision
- incident reasoning
- testing judgment

Improvement needs to be named and shown explicitly.

### 4. Calibration matters as much as correctness

For engineers, being confidently wrong is a serious failure mode.

SWET should track:

- correct and confident
- correct and unsure
- incorrect and confident
- incorrect and unsure

This can become one of the most differentiated parts of the product.

### 5. Real-world task framing

Do not present everything as "answer this question."

Use engineering task frames:

- review this pull request
- debug this production issue
- choose the safer migration plan
- rank these tradeoffs
- identify the flawed assumption
- write a safer test strategy
- propose the minimal incident response plan

## Recommended Information Architecture

The current nav is serviceable, but not optimal for a training product.

Recommended primary web surfaces:

- Home or Landing
- Today
- Workout
- Review
- Progress
- Library
- Plans
- Settings

### Landing

Purpose:

- explain what the product does
- show credibility
- convert visitors

Must include:

- short clear value proposition
- example drills
- competency map preview
- sample progress outcomes
- "start in 3 minutes" CTA

### Today

Purpose:

- prescribe today’s best training path

Should include:

- one dominant CTA: start today’s workout
- estimated duration
- skills being trained today
- review items due
- current streak
- one sentence on why these drills were chosen

### Workout

Purpose:

- run focused sessions with zero ambiguity

Should support:

- default daily workout
- targeted weak-area workout
- format-specific workout
- difficulty-tuned rematch
- timed sprint mode
- resume interrupted session

### Review

Purpose:

- recall and reinforce weak memory traces

Should include:

- answer first, reveal later
- quality rating after reveal
- next due date
- retention stats
- saved drills and missed drills

### Progress

Purpose:

- explain whether the user is getting better

Should include:

- skill trendlines
- competency movement
- confidence calibration
- weekly summary
- strongest gains
- weakest drifts
- recommended next action

### Library

Purpose:

- user-controlled saved content and revisitable drills

Should include:

- bookmarks
- notable misses
- finished capstones
- tagged practice packs

### Plans

Purpose:

- goal-directed training

Should include:

- interview prep
- backend reliability
- debugging
- system design
- staff-level judgment
- AI engineering
- frontend performance

## High-Priority Product Recommendations

## P0: Fix Trust and Core Learning Loop

- Make targeted practice real. Extend the session and training contract so competency, difficulty, format, and specific question review actually work.
- Fix the train grade-context bug so feedback is always tied to the answered question.
- Wire confidence through the entire stack and store it with attempts.
- Expose true review completion on web using quality-based spaced repetition.
- Allow session resumption from the web using the existing current-session API.
- Add a dedicated saved/bookmarks surface.
- Improve Today so it recommends one best next action instead of presenting several equal cards.

## P1: Make It Feel Like Training

- Introduce a daily workout concept with a fixed duration, such as 10 to 12 minutes.
- Show skill delta after each drill and after each session.
- Add drill families instead of exposing raw formats as the dominant UX concept.
- Add a weekly training summary.
- Add a focus plan for a selected goal.
- Add streak protection or recovery mechanics so missing one day does not fully collapse motivation.

## P2: Differentiate the Product

- Add capstone simulations such as PR review inbox, outage triage, or architecture review board.
- Add benchmarks against role peers or anonymous percentile bands.
- Add a calibration score that measures judgment quality, not just correctness.
- Add team mode for managers or engineering organizations.
- Add coaching narratives generated from the user’s performance patterns.

## Recommended Drill Families

These should become the product’s primary content model.

- Bug Hunt
- Debug and Fix
- Pull Request Review
- Incident Triage
- Root Cause Analysis
- System Design Split
- Tradeoff Ranking
- Testing Strategy
- API Contract Review
- Performance Diagnosis
- Security Smell Detection
- Reliability Playbook
- Estimation and Planning
- Requirements Clarification
- Failure Mode Prediction

Each drill family should have:

- a clear time expectation
- a clear scoring model
- one primary competency
- one or two secondary competencies
- visible feedback tied to real engineering behavior

## Feature Ideas by Product Area

### Assessment and Calibration

- offer a short calibration path and a full calibration path
- show confidence intervals, not just estimated level
- let users recalibrate a specific competency
- explain how calibration affects future workouts

### Training and Sessions

- daily workout
- sprint mode: 5 minutes, high tempo
- deep work mode: 20 minutes, harder prompts
- weak-area pack
- role-specific pack
- format-specific pack
- timer pressure mode
- distraction-free mode
- session resume

### Review and Retention

- real spaced repetition quality controls
- memory-only first pass before showing prompt details
- explain why an item returned to review
- retention dashboard
- saved mistakes notebook
- "retry this in 24 hours" shortcut

### Progress and Analytics

- trendlines by competency
- trendlines by drill family
- confidence calibration chart
- strongest weekly gain
- most unstable skill
- overconfidence heatmap
- time-to-answer vs score
- level progression timeline
- progress by role emphasis

### Motivation and Habit

- daily target minutes
- weekly consistency score
- streak saver
- personal bests
- milestone unlocks
- "sharpness score" or "readiness score"
- post-session summary with improvement sentence

### Library and Personal Knowledge

- bookmarks surface
- saved mistakes
- saved explanations
- capstone archive
- personal notes on drills
- filter by competency, format, stack, and date

### Social and Benchmarking

- anonymous percentile by role
- compare current month vs last month
- study buddy mode
- manager dashboard for team training
- org-level weak-area heatmap

### General Engineering Expansion

If SWET will support non-software engineers, do not stretch the software matrix too far.

Recommended approach:

- keep the shared training shell
- create separate competency packs per discipline
- change drill types by discipline
- keep shared product mechanics: calibration, workouts, review, progress, plans

Potential domain packs:

- software engineering
- data engineering
- ML and AI engineering
- mechanical engineering
- electrical engineering
- civil engineering
- industrial engineering
- robotics engineering

## Concrete UX Improvements by Current Screen

### Login

- Add a proper product promise above the auth card.
- Show a 3-bullet explanation of how SWET helps engineers improve.
- Add "takes 3 minutes to get started" if short calibration exists.
- Show OTP resend and timing feedback.
- Reduce the feeling of entering a private admin tool.

### Settings and Onboarding

- Convert setup from a neutral wizard into a training setup with previews.
- Show "this changes your drills" examples when choosing roles and stack.
- Let the user skip advanced preferences and start fast.
- Offer "start light" vs "full calibration."

### Today

- Replace multiple same-weight cards with one main prescribed workout.
- Show why today’s workout was selected.
- Show expected duration.
- Show one visible outcome target, for example "focus on debugging and API design."
- Add a mini summary of yesterday or last session.

### Train

- Support specific modes for focus, review, and rematch.
- Make session identity explicit: "Weak Area Workout", "Debugging Sprint", "Saved Drill Review".
- Preserve answered-question context during grading.
- Show live momentum and remaining effort more clearly.

### Review

- Make review interactive, not list-based.
- Add reveal-then-rate flow.
- Show memory strength indicators.
- Distinguish saved items from failed items more clearly.

### Progress

- Add trends, deltas, and recommendations.
- Turn competency levels into a visual skill map.
- Show "improving", "flat", and "slipping" states.
- Surface calibration quality and confidence mismatch.

## Visual Design Recommendations

The current dark palette is functional but generic.

Recommended direction:

- light-first product with strong readability
- optional dark mode
- warmer, more credible training aesthetic
- less "developer dashboard", more "serious cognitive training product"

## Recommended Color System

### Primary Palette

- Canvas: `#F6F4EC`
- Surface: `#FFFFFF`
- Surface Alt: `#EEF2F5`
- Text Strong: `#0F172A`
- Text Muted: `#52606D`
- Border: `#D8E0E7`
- Primary: `#0F766E`
- Primary Soft: `#D6F0EC`
- Secondary: `#2563EB`
- Secondary Soft: `#DBEAFE`
- Warning: `#F59E0B`
- Warning Soft: `#FEF3C7`
- Success: `#1F8A4C`
- Success Soft: `#DCFCE7`
- Error: `#D64545`
- Error Soft: `#FEE2E2`

Why this works:

- easier for long reading and code scanning
- more premium and less commodity-dark-mode
- strong contrast without harshness
- teal gives a trustworthy training feel

### Alternate Palette: "Lab Notebook"

- Canvas: `#F7F7F2`
- Surface: `#FFFFFF`
- Text: `#111827`
- Muted: `#6B7280`
- Border: `#D1D5DB`
- Primary: `#1D4ED8`
- Accent: `#0F766E`
- Energy: `#EA580C`

This version is a little more technical and more energetic.

## Typography Recommendations

Current fonts are too standard for a distinctive product identity.

Recommended combinations:

- UI: `IBM Plex Sans`
- Code: `IBM Plex Mono`

or

- UI: `Sora`
- Code: `IBM Plex Mono`

Avoid:

- default Inter + generic dark cards as the entire brand identity

## Visual System Recommendations

- Use stronger page hierarchy. Today should feel like a mission control screen, not a list of similar cards.
- Give each drill family a recognizable visual treatment.
- Use color meaningfully for status, not as decoration.
- Replace some flat card repetition with sectional layouts and stronger contrast zones.
- Use motion sparingly but intentionally for workout start, score reveal, and mastery changes.
- Add visual identity to mastery and review states so they feel learnable and memorable.

## Recommended Naming Changes

Some current names are clear but not motivating enough.

Potential improvements:

- `Train` -> `Workout`
- `Review` -> `Recall`
- `Progress` -> `Mastery`
- `Quick Practice` -> `1-Question Drill`
- `Start Workout` -> `Start Today's Workout`
- `Calibrate Your Level` -> `Baseline Assessment`

These names better support the "training product" frame.

## Metrics the Product Should Optimize For

- daily active training sessions
- weekly retained users
- average workout completion rate
- review completion rate
- recall retention after 7 and 30 days
- confidence calibration error
- weak-area improvement over time
- percentage of users completing the first workout within first session
- number of meaningful drills completed per week

## Recommended Immediate Build Order

1. Fix targeted training so selected competency, difficulty, and review flows actually work.
2. Fix session grading context bug.
3. Wire and store confidence.
4. Build a real review-complete UX with spaced repetition quality.
5. Add session resume.
6. Rework Today into a prescribed daily workout screen.
7. Add a bookmarks or library page.
8. Expand Progress into trends plus recommendations.
9. Redesign visual system with a stronger light-first identity.
10. Add plans and drill-family framing.

## Final Product Positioning Recommendation

The right positioning is not:

- "adaptive question generator for engineers"

The right positioning is closer to:

- "daily deliberate practice for engineering judgment"
- "cognitive training for software engineers"
- "skill gym for engineering thinking"

That framing is materially stronger because it promises a habit and an outcome, not just content.

## Bottom Line

SWET already has the engine to become a serious training product.

What it lacks is:

- a tighter learning loop
- better conversion from data to action
- real use of its existing adaptive and review primitives
- a more differentiated product identity

The highest-leverage move is to turn the current web app from a question interface into a deliberate practice system.
