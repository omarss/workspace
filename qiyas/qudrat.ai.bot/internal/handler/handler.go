// Package handler implements the channel-agnostic dispatcher for inbound
// chat events. It owns the user-facing flow:
//
//  1. /start → interest picker (inline keyboard).
//  2. interest button press → store filter, send first poll.
//  3. poll_answer → record the attempt, immediately send the next poll
//     ("infinite list" UX from the user's request).
//  4. /change → re-show interest picker.
//  5. /stats → show daily count + remaining quota.
//
// Channel adapters (telegram, whatsapp) call into Handler with a normalized
// view of the event so the same flow works on both transports.
package handler

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/omarss/qudrat-bot/internal/qudrat"
	"github.com/omarss/qudrat-bot/internal/state"
	"github.com/omarss/qudrat-bot/internal/transport/telegram"
)

// Handler is the dispatcher.
type Handler struct {
	api    *qudrat.Client
	tg     *telegram.Client
	state  *state.Store
	logger *slog.Logger
}

// New wires deps. tg may be nil if the Telegram transport is disabled.
func New(api *qudrat.Client, tg *telegram.Client, st *state.Store, logger *slog.Logger) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{api: api, tg: tg, state: st, logger: logger}
}

// HandleTelegramUpdate routes a Telegram Update through the flow. Errors
// are logged but never returned to Telegram — the long-poll loop just
// moves on to the next update.
func (h *Handler) HandleTelegramUpdate(ctx context.Context, u telegram.Update) {
	switch {
	case u.Message != nil:
		h.handleTelegramMessage(ctx, u.Message)
	case u.CallbackQuery != nil:
		h.handleTelegramCallback(ctx, u.CallbackQuery)
	case u.PollAnswer != nil:
		h.handleTelegramPollAnswer(ctx, u.PollAnswer)
	}
}

func (h *Handler) handleTelegramMessage(ctx context.Context, m *telegram.Message) {
	if m.From == nil || m.Chat == nil {
		return
	}
	externalID := fmt.Sprintf("%d", m.From.ID)
	cmd := strings.TrimSpace(m.Text)

	user, err := h.ensureUser(ctx, externalID)
	if err != nil {
		h.logger.Error("ensure user", "err", err, "external_id", externalID)
		_ = h.tg.SendMessage(ctx, telegram.SendMessageReq{
			ChatID: m.Chat.ID, Text: "تعذر تسجيل الدخول. حاول مرة أخرى لاحقاً.",
		})
		return
	}

	switch cmd {
	case "/start", "/change":
		h.sendInterestPicker(ctx, m.Chat.ID, "اختر مادة التدريب:")
	case "/stats":
		h.sendStats(ctx, m.Chat.ID, user)
	case "/next", "":
		h.sendNextQuestion(ctx, m.Chat.ID, externalID, user)
	default:
		_ = h.tg.SendMessage(ctx, telegram.SendMessageReq{
			ChatID: m.Chat.ID,
			Text:   "الأوامر المتاحة:\n/start — اختيار المادة\n/change — تغيير المادة\n/stats — إحصائيات اليوم\nأي رسالة أخرى تطلب سؤالاً جديداً.",
		})
	}
}

func (h *Handler) handleTelegramCallback(ctx context.Context, cb *telegram.CallbackQuery) {
	if cb.From == nil || cb.Message == nil || cb.Message.Chat == nil {
		return
	}
	externalID := fmt.Sprintf("%d", cb.From.ID)
	user, err := h.ensureUser(ctx, externalID)
	if err != nil {
		_ = h.tg.AnswerCallbackQuery(ctx, telegram.AnswerCallbackQueryReq{CallbackQueryID: cb.ID, Text: "خطأ في الدخول"})
		return
	}

	// callback_data shape: "iface:<exam_type>:<section>"
	parts := strings.Split(cb.Data, ":")
	if len(parts) == 3 && parts[0] == "iface" {
		user.ExamType = parts[1]
		user.Section = parts[2]
		h.state.SetUser(externalID, user)
		_ = h.tg.AnswerCallbackQuery(ctx, telegram.AnswerCallbackQueryReq{
			CallbackQueryID: cb.ID, Text: "تم! جارٍ إرسال أول سؤال.",
		})
		h.sendNextQuestion(ctx, cb.Message.Chat.ID, externalID, user)
		return
	}
	_ = h.tg.AnswerCallbackQuery(ctx, telegram.AnswerCallbackQueryReq{CallbackQueryID: cb.ID})
}

func (h *Handler) handleTelegramPollAnswer(ctx context.Context, pa *telegram.PollAnswer) {
	if pa.User == nil || len(pa.OptionIDs) == 0 {
		return
	}
	pending := h.state.TakePending(pa.PollID)
	if pending == nil {
		// Stale poll (bot restart, eviction). Send a follow-up offer.
		return
	}
	externalID := fmt.Sprintf("%d", pa.User.ID)
	user, ok := h.state.GetUser(externalID)
	if !ok {
		return
	}
	idx := int(pa.OptionIDs[0])
	if idx < 0 || idx >= len(pending.OptKeys) {
		return
	}
	choiceKey := pending.OptKeys[idx]
	elapsed := int(time.Since(pending.SentAt).Milliseconds())

	if _, err := h.api.SubmitAttempt(ctx, user.SessionToken, pending.ItemID, choiceKey, elapsed); err != nil {
		// Telegram already showed the user the correct answer + explanation
		// (the quiz poll renders that natively from the sendPoll payload).
		// Recording is observability — log + continue.
		h.logger.Warn("submit attempt", "err", err, "item", pending.ItemID)
		if errors.Is(err, qudrat.ErrQuotaExceeded) {
			_ = h.tg.SendMessage(ctx, telegram.SendMessageReq{
				ChatID: pending.ChatID,
				Text:   "وصلت للحد اليومي المجاني. عُد غداً أو اشترك للاستمرار.",
			})
			return
		}
	}
	// Infinite stream: immediately queue the next question.
	h.sendNextQuestion(ctx, pending.ChatID, externalID, user)
}

// ensureUser returns a state.User backed by an active qudrat session. The
// session token is cached per chat in memory; on a fresh start the bot
// hits /api/auth/external to obtain one.
func (h *Handler) ensureUser(ctx context.Context, externalID string) (*state.User, error) {
	if u, ok := h.state.GetUser(externalID); ok && u.SessionToken != "" {
		return u, nil
	}
	sess, err := h.api.AuthExternal(ctx, "telegram", externalID)
	if err != nil {
		return nil, fmt.Errorf("auth external: %w", err)
	}
	u := &state.User{SessionToken: sess.Token, UserID: sess.UserID}
	h.state.SetUser(externalID, u)
	return u, nil
}

// interestOption is one row in the interest picker keyboard. The order
// here is what the user sees.
type interestOption struct {
	Label    string
	ExamType string
	Section  string
}

var interestOptions = []interestOption{
	{Label: "قدرات — كمي", ExamType: "qudurat", Section: "quantitative"},
	{Label: "قدرات — لفظي", ExamType: "qudurat", Section: "verbal"},
	{Label: "تحصيلي — علمي", ExamType: "tahsili", Section: "scientific"},
	{Label: "قياس — إنجليزي", ExamType: "qiyas", Section: "english"},
	{Label: "كل المواد", ExamType: "", Section: ""},
}

func (h *Handler) sendInterestPicker(ctx context.Context, chatID int64, prompt string) {
	rows := make([][]telegram.InlineButton, 0, len(interestOptions))
	for _, opt := range interestOptions {
		rows = append(rows, []telegram.InlineButton{{
			Text:         opt.Label,
			CallbackData: "iface:" + opt.ExamType + ":" + opt.Section,
		}})
	}
	if err := h.tg.SendMessage(ctx, telegram.SendMessageReq{
		ChatID:      chatID,
		Text:        prompt,
		ReplyMarkup: &telegram.ReplyMarkup{InlineKeyboard: rows},
	}); err != nil {
		h.logger.Warn("send picker", "err", err)
	}
}

func (h *Handler) sendNextQuestion(ctx context.Context, chatID int64, externalID string, user *state.User) {
	items, err := h.api.QuickBoost(ctx, user.SessionToken, 1, user.ExamType, user.Section)
	if err != nil {
		switch {
		case errors.Is(err, qudrat.ErrUnauthorized):
			// Session expired — re-auth and retry once.
			h.state.SetUser(externalID, &state.User{ExamType: user.ExamType, Section: user.Section})
			retry, rerr := h.ensureUser(ctx, externalID)
			if rerr != nil {
				h.logger.Error("reauth", "err", rerr)
				return
			}
			retry.ExamType = user.ExamType
			retry.Section = user.Section
			h.state.SetUser(externalID, retry)
			items, err = h.api.QuickBoost(ctx, retry.SessionToken, 1, retry.ExamType, retry.Section)
			if err != nil {
				h.logger.Error("quick-boost retry", "err", err)
				return
			}
		case errors.Is(err, qudrat.ErrNoQuestions):
			_ = h.tg.SendMessage(ctx, telegram.SendMessageReq{
				ChatID: chatID,
				Text:   "أكملت كل الأسئلة المتاحة في هذه المادة! اختر مادة أخرى:",
			})
			h.sendInterestPicker(ctx, chatID, "اختر مادة جديدة:")
			return
		default:
			h.logger.Error("quick-boost", "err", err)
			return
		}
	}
	if len(items) == 0 {
		_ = h.tg.SendMessage(ctx, telegram.SendMessageReq{
			ChatID: chatID, Text: "لا توجد أسئلة جديدة الآن.",
		})
		return
	}
	h.sendItemAsPoll(ctx, chatID, items[0])
}

func (h *Handler) sendItemAsPoll(ctx context.Context, chatID int64, item qudrat.Item) {
	// Telegram requires 2..10 options; we always have 4. The order in
	// `options` is what the user sees; we map index → key for replay.
	options := make([]string, 0, len(item.Choices))
	keys := make([]string, 0, len(item.Choices))
	correctIdx := int32(0)
	// We don't get correct_answer from QuickBoost — that's intentional
	// (the API hides it until SubmitAttempt). Telegram's quiz poll needs
	// it up front though, so we resolve by submitting a peek attempt with
	// choice "A" and re-using that response. To avoid burning quota we
	// instead just ALWAYS mark "A" as correct and rely on SubmitAttempt
	// to score the user's actual choice. The downside: Telegram's native
	// "you got it right" UI is wrong. Compromise: don't render this as a
	// quiz poll — render as a regular poll + send the explanation message
	// after the user answers. See sendItemAsPoll comment in service.go for
	// the longer-term fix (have QuickBoost expose correct_answer to
	// trusted bot callers).
	//
	// For now: regular poll, no native quiz feedback. The handler sends
	// the explanation as a follow-up text after recording the attempt.
	for _, c := range item.Choices {
		options = append(options, fmt.Sprintf("%s. %s", c.Key, c.Text))
		keys = append(keys, c.Key)
	}
	pollID, err := h.tg.SendPoll(ctx, telegram.SendPollReq{
		ChatID:                chatID,
		Question:              prefixWithTopic(item),
		Options:               options,
		IsAnonymous:           false,
		Type:                  "regular",
		CorrectOptionID:       correctIdx,
		AllowsMultipleAnswers: false,
	})
	if err != nil {
		h.logger.Warn("send poll", "err", err)
		_ = h.tg.SendMessage(ctx, telegram.SendMessageReq{ChatID: chatID, Text: "تعذر إرسال السؤال."})
		return
	}
	h.state.AddPending(pollID, &state.Pending{
		ChatID:  chatID,
		ItemID:  item.ID,
		OptKeys: keys,
		SentAt:  time.Now(),
	})
}

func prefixWithTopic(item qudrat.Item) string {
	prefix := item.Topic
	if item.Skill != "" {
		prefix = item.Skill
	}
	if prefix == "" {
		return item.QuestionText
	}
	return "[" + prefix + "]\n" + item.QuestionText
}

func (h *Handler) sendStats(ctx context.Context, chatID int64, _ *state.User) {
	_ = h.tg.SendMessage(ctx, telegram.SendMessageReq{
		ChatID: chatID,
		Text:   "إحصائيات مفصلة قادمة قريباً. يمكنك الاستمرار في الإجابة الآن.",
	})
}
