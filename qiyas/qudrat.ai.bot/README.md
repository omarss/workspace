# qudrat-bot

Telegram + WhatsApp bot for the qudrat practice platform.

See `CLAUDE.md` for stack, conventions, and deploy flow.

```sh
make builder   # build the local builder image (one-time)
make test      # unit tests inside the builder
make lint      # static analysis
make build     # build bot binary to bin/
make run       # run locally (needs env vars)
make redeploy  # rebuild + redeploy to k3s
```

## Required env vars

| Var | Purpose |
|---|---|
| `QUDRAT_API_URL` | base URL of qudrat-api, e.g. `http://qudrat-api.qudrat.svc.cluster.local:8080` |
| `QUDRAT_BOT_AUTH_TOKEN` | shared secret for `/api/auth/external` (must match qudrat-api's `QUDRAT_BOT_AUTH_TOKEN`) |
| `QUDRAT_BOT_TELEGRAM_TOKEN` | from @BotFather. Empty disables the Telegram transport |
| `QUDRAT_BOT_TWILIO_ACCOUNT_SID` | Twilio account SID for WhatsApp |
| `QUDRAT_BOT_TWILIO_AUTH_TOKEN` | Twilio auth token |
| `QUDRAT_BOT_TWILIO_FROM` | Twilio WhatsApp sender, e.g. `whatsapp:+14155238886` (sandbox) |
| `QUDRAT_BOT_HTTP_ADDR` | webhook listen addr, default `:8081` |
