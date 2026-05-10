-- 0004_events — append-only event log driving spec §19 + spec §24 metrics.
--
-- Every meaningful action (OTP verified, question served, answer submitted,
-- review state change, calibration sweep, etc.) writes a row. Reads are
-- batched analytics jobs and operator dashboards — no per-row hot path.
--
-- payload is jsonb to keep the schema flexible; the event_type is the
-- contract.

CREATE TABLE events (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type  text  NOT NULL,
    user_id     uuid  REFERENCES users (id) ON DELETE SET NULL,
    item_id     uuid  REFERENCES items (id) ON DELETE SET NULL,
    payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX events_type_recent_idx ON events (event_type, created_at DESC);
CREATE INDEX events_user_recent_idx ON events (user_id, created_at DESC) WHERE user_id IS NOT NULL;
CREATE INDEX events_item_idx        ON events (item_id) WHERE item_id IS NOT NULL;
