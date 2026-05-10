-- Re-add the original CHECK enum. Will fail if the table contains rows
-- with values outside ('qudurat','tahsili') — that's intentional, since
-- rolling back loses information and the operator should know.
ALTER TABLE items
    ADD CONSTRAINT items_exam_type_check
    CHECK (exam_type IN ('qudurat','tahsili'));
