package workflows

import (
	"context"
	"fmt"
	"time"

	dp "github.com/omarss/saas/sdk/go/dataplane"
	"github.com/omarss/saas/sdk/go/internal/idem"
)

// SendNotificationInput targets POST /v1/notifications/send. The payload
// is forwarded verbatim to Novu; the platform validates the workflow name
// but not the shape of the payload bag.
type SendNotificationInput struct {
	WorkflowName string
	ToUserID     string
	Payload      map[string]interface{}

	// WaitForTerminal blocks until the notification reaches a terminal
	// state (sent, delivered, or failed). Polling stops on context
	// cancellation or when Timeout elapses.
	WaitForTerminal bool
	PollInterval    time.Duration
	Timeout         time.Duration
}

// terminalNotificationStatuses lists the Notification.Status values that
// stop a WaitForTerminal poll. Queued is explicitly NOT terminal.
var terminalNotificationStatuses = map[dp.NotificationStatus]struct{}{
	dp.Sent:      {},
	dp.Delivered: {},
	dp.Failed:    {},
}

// SendNotification wraps the trigger endpoint. The HTTP response is 202
// Accepted (queued for the outbox worker). When WaitForTerminal is true
// the workflow then polls GET /v1/notifications/{id} until the status
// reaches sent/delivered/failed; each poll uses the SAME GET endpoint and
// does NOT issue a new idempotency key.
func SendNotification(
	ctx context.Context,
	client *dp.ClientWithResponses,
	in SendNotificationInput,
	opts ...Option,
) (dp.Notification, error) {
	o := collect(opts)
	key := o.idemKey
	if key == "" {
		key = idem.New()
	}

	body := dp.SendNotificationRequest{
		WorkflowName: in.WorkflowName,
		To: struct {
			UserId string `json:"user_id"`
		}{UserId: in.ToUserID},
	}
	if in.Payload != nil {
		p := in.Payload
		body.Payload = &p
	}

	res, err := client.SendNotificationWithResponse(ctx,
		&dp.SendNotificationParams{IdempotencyKey: dp.IdempotencyKey(key)}, body)
	if err != nil {
		return dp.Notification{}, err
	}
	if res.StatusCode() != 202 || res.JSON202 == nil {
		return dp.Notification{}, parseProblem(res.StatusCode(), res.Body)
	}
	notif := res.JSON202.Data
	if !in.WaitForTerminal {
		return notif, nil
	}
	return pollNotificationStatus(ctx, client, notif, in.PollInterval, in.Timeout)
}

// pollNotificationStatus polls GET /v1/notifications/{id} until the
// status is terminal or the ctx / timeout expires. Defaults: 1s poll
// interval, 30s timeout.
func pollNotificationStatus(
	ctx context.Context,
	client *dp.ClientWithResponses,
	current dp.Notification,
	pollInterval, timeout time.Duration,
) (dp.Notification, error) {
	if _, done := terminalNotificationStatuses[current.Status]; done {
		return current, nil
	}
	if pollInterval <= 0 {
		pollInterval = time.Second
	}
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	deadline := time.Now().Add(timeout)
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return current, ctx.Err()
		case <-ticker.C:
			if time.Now().After(deadline) {
				return current, fmt.Errorf("notification %s did not reach terminal status within %s (last=%s)",
					current.Id, timeout, current.Status)
			}
			res, err := client.GetNotificationWithResponse(ctx, current.Id)
			if err != nil {
				return current, err
			}
			if res.StatusCode() != 200 || res.JSON200 == nil {
				return current, parseProblem(res.StatusCode(), res.Body)
			}
			current = res.JSON200.Data
			if _, done := terminalNotificationStatuses[current.Status]; done {
				return current, nil
			}
		}
	}
}
