// Package qudrat is a thin HTTP client for the qudrat-api endpoints the
// bot needs: external-user auth, session quick-boost, attempt submission.
//
// All methods take a per-call context and a per-user bearer token; the
// client itself is stateless and safe for concurrent use.
package qudrat

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Client targets one qudrat-api base URL with one shared bot bearer token.
// The bot bearer is only used for /api/auth/external; everything else uses
// a per-user session bearer returned by AuthExternal.
type Client struct {
	base       string
	botToken   string
	httpClient *http.Client
}

// New constructs a client. http=nil falls back to a 10s-timeout default.
func New(base, botToken string, h *http.Client) *Client {
	if h == nil {
		h = &http.Client{Timeout: 10 * time.Second}
	}
	return &Client{base: base, botToken: botToken, httpClient: h}
}

// Session is what AuthExternal returns: the per-user session token the bot
// must cache and pass on subsequent calls for that user.
type Session struct {
	UserID string `json:"user_id"`
	Token  string `json:"token"`
}

// AuthExternal creates or resolves a qudrat user from (channel, externalID)
// and returns a session bearer the bot uses for subsequent calls.
//
// Authenticated by the shared bot bearer token; this is the only call that
// uses it.
func (c *Client) AuthExternal(ctx context.Context, channel, externalID string) (Session, error) {
	body, _ := json.Marshal(map[string]string{
		"channel":     channel,
		"external_id": externalID,
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/api/auth/external", bytes.NewReader(body))
	if err != nil {
		return Session{}, fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.botToken)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return Session{}, fmt.Errorf("post: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<10))
	if resp.StatusCode != http.StatusOK {
		return Session{}, fmt.Errorf("auth/external %d: %s", resp.StatusCode, string(raw))
	}
	var s Session
	if err := json.Unmarshal(raw, &s); err != nil {
		return Session{}, fmt.Errorf("decode: %w", err)
	}
	return s, nil
}

// Choice is one of the four poll options.
type Choice struct {
	Key  string `json:"key"`
	Text string `json:"text"`
}

// Item is the question the bot will surface as a poll. correct_answer +
// explanation are NOT in this struct (the API hides them until POST attempt).
type Item struct {
	ID                   string   `json:"id"`
	ExamType             string   `json:"exam_type"`
	Section              string   `json:"section"`
	Subject              string   `json:"subject"`
	Topic                string   `json:"topic"`
	Skill                string   `json:"skill"`
	DifficultyTarget     string   `json:"difficulty_target"`
	QuestionText         string   `json:"question_text"`
	Choices              []Choice `json:"choices"`
	EstimatedTimeSeconds int      `json:"estimated_time_seconds"`
}

type quickBoostResp struct {
	SessionType string `json:"session_type"`
	Items       []Item `json:"items"`
}

// QuickBoost fetches up to count unserved items for the user. Empty
// session token returns ErrUnauthorized. examType + section are optional
// filters; pass "" to skip.
func (c *Client) QuickBoost(ctx context.Context, sessionToken string, count int, examType, section string) ([]Item, error) {
	q := fmt.Sprintf("/api/sessions/quick-boost?count=%d", count)
	if examType != "" {
		q += "&exam_type=" + examType
	}
	if section != "" {
		q += "&section=" + section
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.base+q, nil)
	if err != nil {
		return nil, fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+sessionToken)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("get: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 256<<10))
	if resp.StatusCode == http.StatusNotFound {
		return nil, ErrNoQuestions
	}
	if resp.StatusCode == http.StatusUnauthorized {
		return nil, ErrUnauthorized
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("quick-boost %d: %s", resp.StatusCode, string(raw))
	}
	var body quickBoostResp
	if err := json.Unmarshal(raw, &body); err != nil {
		return nil, fmt.Errorf("decode: %w", err)
	}
	return body.Items, nil
}

// AttemptResult is what SubmitAttempt returns: correctness + the teaching
// payload. Field tags match the API JSON exactly (capitalized — that's
// what cmd/api ships today).
type AttemptResult struct {
	AttemptID            string            `json:"AttemptID"`
	Correct              bool              `json:"Correct"`
	CorrectAnswer        string            `json:"CorrectAnswer"`
	Explanation          string            `json:"Explanation"`
	DistractorRationales map[string]string `json:"DistractorRationales"`
}

// SubmitAttempt records the answer and returns the explanation payload.
func (c *Client) SubmitAttempt(ctx context.Context, sessionToken, itemID, choiceKey string, timeTakenMS int) (AttemptResult, error) {
	body, _ := json.Marshal(map[string]any{
		"item_id":       itemID,
		"choice_key":    choiceKey,
		"time_taken_ms": timeTakenMS,
		"hint_used":     false,
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/api/attempts", bytes.NewReader(body))
	if err != nil {
		return AttemptResult{}, fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+sessionToken)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return AttemptResult{}, fmt.Errorf("post: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if resp.StatusCode == http.StatusPaymentRequired {
		return AttemptResult{}, ErrQuotaExceeded
	}
	if resp.StatusCode != http.StatusOK {
		return AttemptResult{}, fmt.Errorf("attempts %d: %s", resp.StatusCode, string(raw))
	}
	var r AttemptResult
	if err := json.Unmarshal(raw, &r); err != nil {
		return AttemptResult{}, fmt.Errorf("decode: %w", err)
	}
	return r, nil
}
