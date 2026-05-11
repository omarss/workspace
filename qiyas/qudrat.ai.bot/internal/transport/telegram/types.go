// Package telegram is a thin stdlib-only client for the Telegram Bot API
// surface the bot needs: getUpdates (long-poll), sendMessage, sendPoll
// (quiz mode), answerCallbackQuery.
//
// We avoid the official telegram-bot-api/v5 SDK to keep the dependency
// tree small and stay aligned with the workspace "no vendor SDK leaks"
// rule. The surface used here is small enough that hand-rolling pays off.
package telegram

// Update is one item from getUpdates.
type Update struct {
	UpdateID      int64          `json:"update_id"`
	Message       *Message       `json:"message,omitempty"`
	CallbackQuery *CallbackQuery `json:"callback_query,omitempty"`
	PollAnswer    *PollAnswer    `json:"poll_answer,omitempty"`
}

// Message is the inbound text message + chat metadata.
type Message struct {
	MessageID int64  `json:"message_id"`
	From      *User  `json:"from"`
	Chat      *Chat  `json:"chat"`
	Text      string `json:"text"`
}

// CallbackQuery is what an InlineKeyboard button press emits.
type CallbackQuery struct {
	ID      string   `json:"id"`
	From    *User    `json:"from"`
	Message *Message `json:"message"`
	Data    string   `json:"data"`
}

// PollAnswer is what a quiz-poll vote emits.
type PollAnswer struct {
	PollID    string  `json:"poll_id"`
	User      *User   `json:"user"`
	OptionIDs []int32 `json:"option_ids"`
}

// User identifies a Telegram account.
type User struct {
	ID           int64  `json:"id"`
	IsBot        bool   `json:"is_bot"`
	FirstName    string `json:"first_name"`
	LastName     string `json:"last_name"`
	Username     string `json:"username"`
	LanguageCode string `json:"language_code"`
}

// Chat is the conversation context.
type Chat struct {
	ID   int64  `json:"id"`
	Type string `json:"type"` // private | group | supergroup | channel
}

// SendMessageReq is the body of sendMessage.
type SendMessageReq struct {
	ChatID      int64        `json:"chat_id"`
	Text        string       `json:"text"`
	ReplyMarkup *ReplyMarkup `json:"reply_markup,omitempty"`
	ParseMode   string       `json:"parse_mode,omitempty"`
}

// ReplyMarkup carries either an inline keyboard or a "remove keyboard"
// flag. The bot uses inline keyboards for the interest picker.
type ReplyMarkup struct {
	InlineKeyboard [][]InlineButton `json:"inline_keyboard,omitempty"`
}

// InlineButton is one cell on an inline keyboard.
type InlineButton struct {
	Text         string `json:"text"`
	CallbackData string `json:"callback_data"`
}

// SendPollReq is the body of sendPoll. type=quiz lets Telegram render the
// correct/wrong feedback natively + show the explanation we attach.
type SendPollReq struct {
	ChatID                int64    `json:"chat_id"`
	Question              string   `json:"question"`
	Options               []string `json:"options"`
	IsAnonymous           bool     `json:"is_anonymous"`
	Type                  string   `json:"type"` // "quiz"
	CorrectOptionID       int32    `json:"correct_option_id"`
	Explanation           string   `json:"explanation,omitempty"`
	OpenPeriod            int32    `json:"open_period,omitempty"`
	AllowsMultipleAnswers bool     `json:"allows_multiple_answers"`
}

// SendPollResp is the subset we read back: the poll_id is what poll_answer
// callbacks reference.
type SendPollResp struct {
	OK     bool `json:"ok"`
	Result struct {
		MessageID int64 `json:"message_id"`
		Poll      struct {
			ID string `json:"id"`
		} `json:"poll"`
	} `json:"result"`
}

// AnswerCallbackQueryReq is the body of answerCallbackQuery — call it to
// stop the spinner on an inline-keyboard button press, optionally with a
// short toast message.
type AnswerCallbackQueryReq struct {
	CallbackQueryID string `json:"callback_query_id"`
	Text            string `json:"text,omitempty"`
}
