# corrections.json — held-out ground-truth test set

`corrections.json` is the **evaluation test set** for the speed-limit
algorithm in `build_roads.py`. The build pipeline itself is blind to
this file — it resolves every segment's speed from OSM tags, KSA
implicit zones, class inference, and school-zone capping, without
peeking at the ground truth. `quality_check.py` then loads this file
and grades how well the algorithm and each data source agree with
the posted values you've verified.

Keeping it **held-out** is the whole point. If the build used it as
an override we'd only measure "did the override work", not "how good
is the inference". The latter is the interesting number.

## What the build actually uses (in priority order)

```
  100   osm:maxspeed                  explicit posted sign tagged on the way
   95   osm:maxspeed:conditional      first unconditional branch
   90   osm:maxspeed:forward|backward directional signs
   80   osm:zone:maxspeed             e.g. SA:30, SA:urban
   70   osm:source:maxspeed           implicit zone (SA:urban = 80, etc.)
   40   osm:maxspeed:advisory         advisory, non-binding
   10   inferred:highway_class        KSA default by class (+ service subtype)
  (cap) inferred:school_zone          40 km/h near schools, on residential/below
```

Within a tier, conflicts break by `timestamp` (newest wins) then by
majority vote (ties → lower speed, conservative). Lower-priority
signals only win when no higher-priority signal is present.

`corrections.json` **is not in this list.** It sits outside the
build and is only consumed by `quality_check.py`.

## File format

```jsonc
{
  "corrections": [
    {
      "label": "King Salman Rd (trunk)",          // shown in the grading table
      "name_contains": [                          // case-insensitive substring vs name / name:en
        "King Salman Road",
        "King Salman Rd",
        "طريق الملك سلمان",
        "الملك سلمان"
      ],
      "highway": [                                // restrict test to these classes
        "trunk", "trunk_link",
        "primary", "primary_link"
      ],
      "maxspeed_kmh": 110,                        // posted limit (ground truth)
      "tolerance_kmh": 15                         // optional, default 15
    }
  ]
}
```

- **`name_contains`** — substring match against `name` (Arabic) *and*
  `name:en`. Include every transliteration OSM editors might have
  picked (Uaroba / Uroubah / Urubah / Orouba for العروبة, Haer / Hair
  / Hayer for الحائر, etc). Loose matching is fine — if you pick up
  an unrelated residential side-street with the same name, the
  `highway` filter scopes it out.
- **`highway`** — restrict the rule to the main carriageway classes
  for this road. Omit the key entirely (or set to `null`) to match
  any class. Without this filter a King Salman rule would evaluate
  against every residential street named after the king.
- **`maxspeed_kmh`** — the posted limit in km/h. Verified, not guessed.
- **`tolerance_kmh`** — optional. How far the algorithm's answer can
  drift before the rule flags as DRIFT. Defaults to 15.

## Source of truth: Google Maps

**Every speed value in `corrections.json` must be verifiable against
Google Maps.** That's the tie-breaker when OSM tags, SA generic
inference, and local memory disagree. Workflow:

1. Open `https://www.google.com/maps`, navigate to the road.
2. Switch to Street View along a representative stretch (pan until you
   see a posted sign). Google also surfaces the speed limit in
   Driving mode — the small shield in the bottom-left when routing.
3. Use the value on the sign. If the road has different speeds on
   different sections (e.g. 80 urban → 100 outside), pick the value
   for the portion inside the Riyadh bbox this project covers, and
   note the exception in `label`.

Do **not** use OSM's `maxspeed` as the source of truth — this file
exists *because* OSM is frequently wrong. Don't guess from the class
either; the class defaults are the inference fallback you're trying
to evaluate.

## The grading output

```
  label                               n   len(km)  expected mode  w.mean  |Δ|  ±tol  n-acc  L-acc   verdict
  King Fahd Rd (urban trunk)        155    279.7       100  100     114    0    15    42%    36%   OK
  King Salman Rd (trunk)             25     89.0       110   80     105   30    15    60%    74%   DRIFT
  ...
  Overall count-weighted:  787/1201 (65.5%)
  Overall length-weighted: 53.2%
```

- **n** — segments matched by the rule.
- **len(km)** — approximate length of those segments (polygon area ÷
  ~12 m avg carriageway width).
- **expected** — your posted value.
- **mode** — most common assigned speed across matching segments.
- **w.mean** — length-weighted mean assigned speed.
- **|Δ|** — `abs(mode − expected)`.
- **n-acc** — % of matched *segments* whose speed is within tolerance.
- **L-acc** — % of matched *length* within tolerance. Usually more
  meaningful than n-acc because it weights main carriageway over
  slip-ramps.
- **verdict** — `OK` if `|Δ| ≤ tol`, else `DRIFT`.

The footer shows overall accuracy (both weightings) and a per-source
scorecard: how often each speed_source family agrees with ground
truth. This is the feedback loop for tuning the build — if
`inferred` suddenly drops, the class defaults drifted away from
reality; if `osm` drops, OSM editors changed tagging for the worse.

## The add / verify loop

1. **Pick a road.** Any well-known Riyadh arterial, ring road, or
   intercity highway is a good candidate.
2. **Look up the posted speed on Google Maps** (see above). Write
   down the exact value + the Arabic and English name variants you
   see.
3. **Add the rule** to `corrections.json`. Include every name
   variant, set the right `highway` filter.
4. **Grade it.**

   ```bash
   python quality_check.py
   ```

5. **Read the result.** If the rule shows `DRIFT`, that's useful
   signal — either OSM has the wrong tag, or the class inference is
   miscalibrated, or your `name_contains` is too loose. Iterate.
6. **Commit `corrections.json`.** The regenerated `roads.json` is a
   build artifact.

## Interpreting DRIFT

A `DRIFT` verdict is a *finding*, not a bug to fix. What it tells
you depends on the dominant `speed_source` for that rule:

- **Mostly `osm:*` and drifting.** OSM's crowdsourced tagging
  disagrees with the posted sign for this road. Probably the OSM
  tag is stale or wrong, OR the road has genuine speed variation
  and your single `maxspeed_kmh` in `corrections.json` can't
  represent it. Either fix the tag upstream (edit OSM), or live with
  the drift.
- **Mostly `inferred:*` and drifting.** The class-default speed for
  this road is wrong in `SPEED_DEFAULT_KMH`. Tune the default in
  `build_roads.py` if multiple rules disagree the same way. A
  single-road miscalibration is usually not worth it.
- **`L-acc` high, `n-acc` low.** Small slip-road pieces are noisy,
  the long main carriageway is correct. Ignore.
- **`n-acc` high, `L-acc` low.** Most *segments* are right but the
  long main stretch is wrong — the real problem.

## What NOT to put in corrections.json

- **Individual segment overrides.** Matching is by *name*, not by
  OSM id. If a 200-metre piece of Olaya is 40 while the rest is 70,
  it's captured in OSM or by the school-zone cap, not here.
- **Anything temporary.** Road-works / temporary reductions don't
  belong in a permanent test set.
- **Speeds you're not sure about.** Tolerance is usually 15–20 km/h;
  if you'd fail the tolerance yourself when asked, skip the rule.

## Name variants — get the match right

OSM tags are inconsistent. Grep the cached OSM data for what editors
actually picked before writing a rule:

```bash
zcat cache/tile_*.json.gz | jq -r '.elements[].tags | select(.) | [.name, ."name:en"] | @tsv' \
  | grep -iE 'olay|alaya|عليا' | sort -u
```

For every correction, include at least:

- **Arabic name** with and without `الـ` and with and without `طريق`.
  Example: `"الملك سلمان"` and `"طريق الملك سلمان"`.
- **English canonical**: `"King Salman Rd"` and `"King Salman Road"`.
- **Known transliterations**: `Uroubah / Urubah / Uaroba / Orouba`
  for العروبة, `Haer / Hair / Hayer` for الحائر, `Al Awal / Al Awwal`
  for الأول, etc.

If a rule shows `n=0` in the grading, its `name_contains` didn't
match any OSM names in the cached tiles — broaden the patterns and
re-run.

## Highway scope — avoid collateral

Without a `highway` filter, `"King Salman"` would also match
residential side-streets named after the king. Almost always scope
the rule:

| Road type                             | highway classes |
|---|---|
| Ring road / expressway                | `trunk`, `trunk_link`, optionally `motorway`, `motorway_link` |
| Major arterial (Olaya, Uroubah, …)    | `primary`, `primary_link` |
| Neighbourhood-scale                   | `secondary`, `tertiary` |
| Intercity (Riyadh-Dammam, Makkah, …)  | `motorway`, `motorway_link`, `trunk` |

## Why you might see `inferred` beat `osm` on accuracy

The per-source scorecard will sometimes show `inferred` with a
higher length-accuracy than `osm`. That's real: OSM tags on many
long arterials are short, patchy, and occasionally just wrong
(e.g. `maxspeed=25` on a 6-lane secondary when the editor meant
"25 mph"). The KSA class default applied uniformly across the road
can be closer to the posted truth than the granular OSM tags.

This is the feedback signal that `corrections.json` is designed to
produce. Use it to decide whether to trust a source more or less —
not to paper over it with overrides.
