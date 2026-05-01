-- The four slugs seeded by the up migration. We don't TRUNCATE because
-- operators may have added rows by hand (testing variants, swapping in a
-- new tier) and DELETE-by-slug is what they meant.
DELETE FROM models WHERE slug IN (
    'Qwen/Qwen2.5-Coder-32B-Instruct',
    'Qwen/Qwen2.5-Coder-7B-Instruct',
    'meta-llama/Llama-3.2-3B-Instruct',
    'meta-llama/Llama-3.2-1B-Instruct'
);
