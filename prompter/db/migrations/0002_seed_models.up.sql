-- 0002_seed_models — initial tier ladder.
--
-- These slugs are the model identifiers Together.ai accepts in the `model`
-- field of /v1/chat/completions. Verify catalogue availability before each
-- launch — Together rotates models faster than this file is committed.
--
-- The multiplier is the score weight for difficulty; smaller models score
-- higher when they get the answer right. The ladder is intentionally
-- mixed-family (Qwen-Coder + Llama-3.2) only because Qwen-Coder ships in
-- 7B/32B sizes on Together; we'll move to a single-family ladder when
-- 0.5B/1.5B/3B Coder variants are hosted.
INSERT INTO models (slug, display_name, provider, param_count_b, multiplier, active) VALUES
    ('Qwen/Qwen2.5-Coder-32B-Instruct',     'Qwen2.5-Coder 32B',  'together', 32.0, 1.0, true),
    ('Qwen/Qwen2.5-Coder-7B-Instruct',      'Qwen2.5-Coder 7B',   'together',  7.0, 2.5, true),
    ('meta-llama/Llama-3.2-3B-Instruct',    'Llama-3.2 3B',       'together',  3.0, 4.5, true),
    ('meta-llama/Llama-3.2-1B-Instruct',    'Llama-3.2 1B',       'together',  1.0, 7.0, true)
ON CONFLICT (slug) DO NOTHING;
