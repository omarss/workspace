-- 0002_relax_exam_type — let the items table accept any exam_type string.
--
-- The original CHECK enum (qudurat / tahsili) reflected the Phase 1 spec
-- scope. The sibling question generation pipeline has grown beyond that
-- — it emits 'qiyas' for English questions, and more buckets are likely.
-- Future-phase filters (which exam_types a learner sees) belong in the
-- application layer, not in the schema.
ALTER TABLE items DROP CONSTRAINT items_exam_type_check;
