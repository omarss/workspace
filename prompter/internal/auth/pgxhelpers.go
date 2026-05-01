package auth

import (
	"time"

	"github.com/jackc/pgx/v5/pgtype"
)

// Helpers for converting time.Time / time.Duration values into the pgtype
// shapes sqlc emits for `timestamptz` and `interval` columns. Centralising
// them keeps the auth services free of pgtype boilerplate.

func pgxTimestamptz(t time.Time) pgtype.Timestamptz {
	return pgtype.Timestamptz{Time: t, Valid: true}
}

func pgxInterval(d time.Duration) pgtype.Interval {
	return pgtype.Interval{Microseconds: int64(d / time.Microsecond), Valid: true}
}
