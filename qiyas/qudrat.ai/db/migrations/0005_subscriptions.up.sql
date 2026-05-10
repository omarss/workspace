-- 0005_subscriptions — billing state per user (spec §19.3 + §27).
--
-- One row per user-subscription cycle. Status transitions: trial → active
-- (on first paid renewal) → cancelled or expired. The 'trial' row is
-- inserted lazily on first quota check — no need for a signup hook.
--
-- provider + provider_ref let us point at Stripe Subscription IDs or
-- Moyasar invoice IDs without locking the schema to one PSP. plan is a
-- short slug ("free", "monthly", "annual") interpreted by the billing
-- service.

CREATE TABLE subscriptions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    plan          text NOT NULL,
    status        text NOT NULL CHECK (status IN ('trial','active','cancelled','expired','past_due')),
    provider      text,
    provider_ref  text,
    started_at    timestamptz NOT NULL DEFAULT now(),
    renewed_at    timestamptz,
    expires_at    timestamptz,
    cancelled_at  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
-- Lookups: get-current-for-user is the hot read; the partial index keeps
-- it index-only against the active slice.
CREATE INDEX subscriptions_user_active_idx
    ON subscriptions (user_id, started_at DESC)
    WHERE status IN ('trial','active','past_due');
