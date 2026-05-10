-- 0006_parent_links — parent ↔ child link with consent.
--
-- Spec §4 #11 + §23. Parents see consistency + improvement read-only;
-- never the questions themselves, never the failures in detail. The
-- consent flow is one-sided today (parent enters child's email/phone
-- and the child accepts via a separate confirm endpoint that lands
-- when the UI does — Phase 10.x).

CREATE TABLE parent_links (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id   uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    child_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    status      text NOT NULL CHECK (status IN ('pending','accepted','revoked')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    accepted_at timestamptz,
    revoked_at  timestamptz,
    CONSTRAINT parent_links_distinct CHECK (parent_id <> child_id),
    UNIQUE (parent_id, child_id)
);
CREATE INDEX parent_links_child_idx
    ON parent_links (child_id)
    WHERE status = 'accepted';
