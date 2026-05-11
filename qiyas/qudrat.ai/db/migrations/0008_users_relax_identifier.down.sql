-- Re-add the constraint. Will fail if any user row currently has neither
-- email nor phone — bot-created users lack both, so this rollback only
-- works if you delete those rows first.
ALTER TABLE users
    ADD CONSTRAINT users_identifier_present
    CHECK (email IS NOT NULL OR phone IS NOT NULL);
