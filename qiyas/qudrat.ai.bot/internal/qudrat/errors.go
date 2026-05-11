package qudrat

import "errors"

// Domain errors the bot dispatcher inspects to render the right message.
var (
	ErrUnauthorized  = errors.New("qudrat: unauthorized (session expired)")
	ErrNoQuestions   = errors.New("qudrat: no unanswered questions match the filter")
	ErrQuotaExceeded = errors.New("qudrat: trial daily quota exceeded")
)
