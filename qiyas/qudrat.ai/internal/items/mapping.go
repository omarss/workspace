package items

import (
	"time"

	"github.com/google/uuid"

	"github.com/omarss/qudrat/internal/store"
)

// ServedItem is the wire shape returned to the learner. NEVER includes
// correct_answer, explanation, or distractor_rationales — those land on the
// AttemptResult after the user commits an answer.
type ServedItem struct {
	ID                   uuid.UUID `json:"id"`
	ExamType             string    `json:"exam_type"`
	Section              string    `json:"section"`
	Subject              string    `json:"subject"`
	GradeLevel           string    `json:"grade_level"`
	Unit                 string    `json:"unit"`
	Topic                string    `json:"topic"`
	Skill                string    `json:"skill"`
	CognitiveLevel       string    `json:"cognitive_level"`
	DifficultyTarget     string    `json:"difficulty_target"`
	QuestionArchetype    string    `json:"question_archetype"`
	QuestionText         string    `json:"question_text"`
	Choices              []Choice  `json:"choices"`
	EstimatedTimeSeconds int       `json:"estimated_time_seconds"`
}

// Choice is the keyed alternative. distractor_rationale is intentionally
// hidden until the attempt lands.
type Choice struct {
	Key  string `json:"key"`
	Text string `json:"text"`
}

func toServedItem(r store.PickUnservedItemsForUserRow, choices []store.ItemChoice) ServedItem {
	out := ServedItem{
		ID:                   r.ID,
		ExamType:             r.ExamType,
		Section:              r.Section,
		Subject:              r.Subject,
		GradeLevel:           r.GradeLevel,
		Unit:                 r.Unit,
		Topic:                r.Topic,
		Skill:                r.Skill,
		CognitiveLevel:       r.CognitiveLevel,
		DifficultyTarget:     r.DifficultyTarget,
		QuestionArchetype:    r.QuestionArchetype,
		QuestionText:         r.QuestionText,
		EstimatedTimeSeconds: int(r.EstimatedTimeSeconds),
		Choices:              make([]Choice, 0, len(choices)),
	}
	for _, c := range choices {
		out.Choices = append(out.Choices, Choice{Key: c.ChoiceKey, Text: c.ChoiceText})
	}
	return out
}

// TopicMastery is one row in the weakness heatmap.
type TopicMastery struct {
	ExamType     string  `json:"exam_type"`
	Section      string  `json:"section"`
	Topic        string  `json:"topic"`
	Attempts     int     `json:"attempts"`
	CorrectCount int     `json:"correct_count"`
	Accuracy     float64 `json:"accuracy"`
}

func toTopicMastery(r store.SummarizeMasteryByTopicRow) TopicMastery {
	return TopicMastery{
		ExamType:     r.ExamType,
		Section:      r.Section,
		Topic:        r.Topic,
		Attempts:     int(r.Attempts),
		CorrectCount: int(r.CorrectCount),
		Accuracy:     r.Accuracy,
	}
}

// HistoryEntry is the user-visible attempt log entry.
type HistoryEntry struct {
	AttemptID        uuid.UUID  `json:"attempt_id"`
	ItemID           uuid.UUID  `json:"item_id"`
	ChoiceKey        *string    `json:"choice_key,omitempty"`
	Correct          *bool      `json:"correct,omitempty"`
	TimeTakenMS      *int       `json:"time_taken_ms,omitempty"`
	ExamType         string     `json:"exam_type"`
	Section          string     `json:"section"`
	Topic            string     `json:"topic"`
	Skill            string     `json:"skill"`
	DifficultyTarget string     `json:"difficulty_target"`
	ServedAt         time.Time  `json:"served_at"`
	AnsweredAt       *time.Time `json:"answered_at,omitempty"`
}

func toHistoryEntry(r store.ListRecentAttemptsForUserRow) HistoryEntry {
	out := HistoryEntry{
		AttemptID:        r.ID,
		ItemID:           r.ItemID,
		ChoiceKey:        r.ChoiceKey,
		Correct:          r.Correct,
		ExamType:         r.ExamType,
		Section:          r.Section,
		Topic:            r.Topic,
		Skill:            r.Skill,
		DifficultyTarget: r.DifficultyTarget,
		ServedAt:         r.ServedAt.Time,
	}
	if r.TimeTakenMs != nil {
		v := int(*r.TimeTakenMs)
		out.TimeTakenMS = &v
	}
	if r.AnsweredAt.Valid {
		t := r.AnsweredAt.Time
		out.AnsweredAt = &t
	}
	return out
}
