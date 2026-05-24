# Cleanup report

- rows in:      `25000`
- rows out:     `25000`
- rows dropped: `0` (0.0%)

| rule | dropped | flagged | description |
|---|---:|---:|---|
| `drop_missing_required` | 0 | 0 | NaN in any of ('observed_at', 'family', 'level', 'region', 'sector', 'ownership', 'base_monthly', 'is_saudi', 'source') |
| `drop_stale` | 0 | 0 | observed_at older than 5.0 years |
| `drop_below_minimum_wage` | 0 | 0 | base_monthly < 4000 for Saudis or < 1000 for non-Saudis |
| `drop_above_ceiling` | 0 | 0 | base_monthly > 500000 |
| `drop_duplicates` | 0 | 0 | duplicate composite key ('source', 'observed_at', 'family', 'level', 'region', 'sector', 'ownership', 'is_saudi', 'base_monthly') |
| `drop_low_confidence` | 0 | 0 | confidence (after recency decay) < 0.1 |
| `flag_segment_outliers` | 0 | 0 | |z| > 4.0 on log(base) flagged but kept |
