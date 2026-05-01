package submissions

import (
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/omarss/prompter/internal/store"
)

func submissionFromRow(r store.Submission) Submission {
	out := Submission{
		ID:           r.ID,
		Status:       r.Status,
		ChallengeID:  r.ChallengeID,
		ModelSlug:    r.ModelSlug,
		Prompt:       r.Prompt,
		PromptTokens: int(r.PromptTokens),
		CreatedAt:    r.CreatedAt.Time,
	}
	if r.OutputCode != nil {
		out.Output = *r.OutputCode
	}
	if r.Similarity.Valid {
		out.Similarity = numericToFloat(r.Similarity)
	}
	if r.TestsPassed != nil {
		out.TestsPassed = int(*r.TestsPassed)
	}
	if r.TestsTotal != nil {
		out.TestsTotal = int(*r.TestsTotal)
	}
	if r.Multiplier.Valid {
		out.Multiplier = numericToFloat(r.Multiplier)
	}
	if r.Brevity.Valid {
		out.Brevity = numericToFloat(r.Brevity)
	}
	if r.Score.Valid {
		out.Score = numericToFloat(r.Score)
	}
	if r.RejectReason != nil {
		out.RejectReason = *r.RejectReason
	}
	if r.GradedAt.Valid {
		t := r.GradedAt.Time
		out.GradedAt = &t
	}
	return out
}

func numericToFloat(n pgtype.Numeric) float64 {
	v, err := n.Float64Value()
	if err != nil || !v.Valid {
		return 0
	}
	return v.Float64
}
