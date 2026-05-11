package handler

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/omarss/qudrat-bot/internal/qudrat"
	"github.com/omarss/qudrat-bot/internal/state"
	"github.com/omarss/qudrat-bot/internal/transport/whatsapp"
)

// HandleWhatsApp processes one inbound WhatsApp message from Twilio.
//
// Flow mirrors Telegram but uses plain text since WhatsApp Business has no
// native quiz polls:
//
//   - "ابدأ" / "start" → interest text-menu
//   - "1".."5"        → pick interest, send first question
//   - "A".."D"        → answer the previous question, then send next
//   - anything else   → next question
func (h *Handler) HandleWhatsApp(ctx context.Context, wa *whatsapp.Client, msg whatsapp.IncomingMessage) {
	externalID := msg.From
	body := strings.ToUpper(strings.TrimSpace(msg.Body))

	user, err := h.ensureUserChannel(ctx, "whatsapp", externalID)
	if err != nil {
		_ = wa.SendText(ctx, msg.From, "تعذر الدخول. حاول مرة أخرى.")
		return
	}

	switch {
	case body == "" || body == "ابدأ" || body == "START" || body == "/START":
		h.sendWAInterestMenu(ctx, wa, msg.From)
	case len(body) == 1 && body >= "1" && body <= "5":
		idx := int(body[0] - '1')
		if idx >= 0 && idx < len(interestOptions) {
			user.ExamType = interestOptions[idx].ExamType
			user.Section = interestOptions[idx].Section
			h.state.SetUser(externalID, user)
			h.sendWANextQuestion(ctx, wa, msg.From, externalID, user)
		}
	case len(body) == 1 && body >= "A" && body <= "D":
		h.handleWAAnswer(ctx, wa, msg.From, externalID, user, body)
	default:
		h.sendWANextQuestion(ctx, wa, msg.From, externalID, user)
	}
}

// ensureUserChannel is the channel-aware variant of ensureUser. The state
// store keys by externalID alone since the same user can't be active on
// two channels at once with the same ID — Telegram IDs are numeric, WA
// addresses contain ":+" — so they can never collide.
func (h *Handler) ensureUserChannel(ctx context.Context, channel, externalID string) (*state.User, error) {
	if u, ok := h.state.GetUser(externalID); ok && u.SessionToken != "" {
		return u, nil
	}
	sess, err := h.api.AuthExternal(ctx, channel, externalID)
	if err != nil {
		return nil, fmt.Errorf("auth external: %w", err)
	}
	u := &state.User{SessionToken: sess.Token, UserID: sess.UserID}
	h.state.SetUser(externalID, u)
	return u, nil
}

func (h *Handler) sendWAInterestMenu(ctx context.Context, wa *whatsapp.Client, to string) {
	var sb strings.Builder
	sb.WriteString("أهلاً بك في qudrat. اختر مادة (أرسل رقمها):\n\n")
	for i, opt := range interestOptions {
		fmt.Fprintf(&sb, "%d. %s\n", i+1, opt.Label)
	}
	_ = wa.SendText(ctx, to, sb.String())
}

func (h *Handler) sendWANextQuestion(ctx context.Context, wa *whatsapp.Client, to, externalID string, user *state.User) {
	items, err := h.api.QuickBoost(ctx, user.SessionToken, 1, user.ExamType, user.Section)
	if err != nil {
		switch {
		case errors.Is(err, qudrat.ErrUnauthorized):
			h.state.SetUser(externalID, &state.User{ExamType: user.ExamType, Section: user.Section})
			retry, rerr := h.ensureUserChannel(ctx, "whatsapp", externalID)
			if rerr != nil {
				return
			}
			retry.ExamType = user.ExamType
			retry.Section = user.Section
			h.state.SetUser(externalID, retry)
			items, err = h.api.QuickBoost(ctx, retry.SessionToken, 1, retry.ExamType, retry.Section)
			if err != nil {
				return
			}
		case errors.Is(err, qudrat.ErrNoQuestions):
			_ = wa.SendText(ctx, to, "أكملت كل الأسئلة المتاحة! أرسل ابدأ لاختيار مادة جديدة.")
			return
		default:
			h.logger.Error("whatsapp quick-boost", "err", err)
			return
		}
	}
	if len(items) == 0 {
		return
	}
	item := items[0]
	// Persist via the same Pending machinery so /poll_answer logic and
	// quota tracking work uniformly.
	h.state.AddPending("wa:"+externalID, &state.Pending{
		ChatID:  0,
		ItemID:  item.ID,
		OptKeys: keysOf(item),
		SentAt:  time.Now(),
	})
	var sb strings.Builder
	if item.Topic != "" {
		fmt.Fprintf(&sb, "[%s]\n", item.Topic)
	}
	sb.WriteString(item.QuestionText)
	sb.WriteString("\n\n")
	for _, c := range item.Choices {
		fmt.Fprintf(&sb, "%s. %s\n", c.Key, c.Text)
	}
	sb.WriteString("\n(أرسل A أو B أو C أو D)")
	_ = wa.SendText(ctx, to, sb.String())
}

func (h *Handler) handleWAAnswer(ctx context.Context, wa *whatsapp.Client, to, externalID string, user *state.User, choiceKey string) {
	pending := h.state.TakePending("wa:" + externalID)
	if pending == nil {
		_ = wa.SendText(ctx, to, "لا يوجد سؤال نشط. أرسل أي رسالة لطلب سؤال جديد.")
		return
	}
	elapsed := int(time.Since(pending.SentAt).Milliseconds())
	res, err := h.api.SubmitAttempt(ctx, user.SessionToken, pending.ItemID, choiceKey, elapsed)
	if err != nil {
		if errors.Is(err, qudrat.ErrQuotaExceeded) {
			_ = wa.SendText(ctx, to, "وصلت للحد اليومي المجاني. عُد غداً أو اشترك للاستمرار.")
			return
		}
		h.logger.Error("whatsapp submit attempt", "err", err)
		_ = wa.SendText(ctx, to, "تعذر تسجيل الإجابة. أرسل أي رسالة للسؤال التالي.")
		return
	}
	verdict := "إجابة خاطئة"
	if res.Correct {
		verdict = "إجابة صحيحة"
	}
	_ = wa.SendText(ctx, to, fmt.Sprintf("%s\nالصحيح: %s\n\n%s", verdict, res.CorrectAnswer, res.Explanation))
	// Infinite stream: send the next.
	h.sendWANextQuestion(ctx, wa, to, externalID, user)
}

func keysOf(item qudrat.Item) []string {
	out := make([]string, 0, len(item.Choices))
	for _, c := range item.Choices {
		out = append(out, c.Key)
	}
	return out
}
