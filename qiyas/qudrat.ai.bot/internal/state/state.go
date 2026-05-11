// Package state holds the bot's in-memory per-user state.
//
// Two maps:
//
//   - chat → user-state (qudrat session token + selected interest).
//   - poll-id → pending-poll record (item_id + chat_id + sent_at) so we
//     can resolve poll_answer updates back to an item and credit the
//     attempt.
//
// In-memory is fine for the MVP — restart loses the maps, the user just
// has to /start again. A future phase persists this in Postgres if churn
// is high.
package state

import (
	"sync"
	"time"
)

// User holds the per-chat session + filter selection.
type User struct {
	SessionToken string
	UserID       string
	ExamType     string // "qudurat" | "tahsili" | "qiyas" | ""
	Section      string // "quantitative" | "verbal" | "scientific" | "english" | ""
}

// Pending captures an in-flight quiz poll. The bot sends the poll, stores
// (poll_id → Pending), and waits for a poll_answer.
type Pending struct {
	ChatID   int64
	ItemID   string
	CorrectK string // "A" | "B" | "C" | "D" — for cross-check
	OptKeys  []string
	SentAt   time.Time
}

// Store is the singleton in-memory state.
type Store struct {
	mu       sync.Mutex
	users    map[string]*User    // key: external_id (Telegram user_id as string, or WhatsApp phone)
	pending  map[string]*Pending // key: poll_id
	maxPolls int
}

// NewStore returns an empty store with a default cap of 10k pending polls
// (anything older gets forgotten on next sweep).
func NewStore() *Store {
	return &Store{
		users:    make(map[string]*User),
		pending:  make(map[string]*Pending),
		maxPolls: 10000,
	}
}

// GetUser returns (user, true) if known. The caller mutates fields freely
// — the returned pointer is the live object.
func (s *Store) GetUser(externalID string) (*User, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	u, ok := s.users[externalID]
	return u, ok
}

// SetUser stores (or replaces) the user.
func (s *Store) SetUser(externalID string, u *User) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.users[externalID] = u
}

// AddPending records an in-flight poll. Best-effort eviction when over cap.
func (s *Store) AddPending(pollID string, p *Pending) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.pending) >= s.maxPolls {
		// Cheap eviction: drop one arbitrary entry. Ordering doesn't matter
		// because the bot is the only writer and stale rows are harmless.
		for k := range s.pending {
			delete(s.pending, k)
			break
		}
	}
	s.pending[pollID] = p
}

// TakePending returns + removes the pending poll. Returns nil if unknown.
func (s *Store) TakePending(pollID string) *Pending {
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.pending[pollID]
	if !ok {
		return nil
	}
	delete(s.pending, pollID)
	return p
}
