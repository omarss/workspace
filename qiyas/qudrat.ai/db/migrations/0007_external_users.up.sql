-- 0007_external_users — link a chat-based identity (Telegram / WhatsApp)
-- to a qudrat user.
--
-- The bot calls POST /api/auth/external with (channel, external_id) and
-- gets back a session for the linked user. First call creates both the
-- user and the link row; subsequent calls just return the existing user.
--
-- channel is intentionally text (not enum) so adding "discord", "line",
-- etc. doesn't need a migration.

CREATE TABLE external_users (
    channel       text NOT NULL,
    external_id   text NOT NULL,
    user_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (channel, external_id)
);
CREATE INDEX external_users_user_idx ON external_users (user_id);
