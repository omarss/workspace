"""Tests for Slack Block Kit JSON structure builders."""

import os

# Set env vars before imports
os.environ.setdefault("SWET_SLACK_BOT_TOKEN", "test-token")
os.environ.setdefault("SWET_SLACK_APP_TOKEN", "test-app-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from swet_slack.blocks import (  # noqa: E402
    confirm_blocks,
    formats_blocks,
    frameworks_blocks,
    languages_blocks,
    length_blocks,
    mcq_blocks,
    post_answer_blocks,
    roles_blocks,
    session_count_blocks,
)


def test_mcq_blocks():
    options = {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"}
    q_id = "abc123def456ghij"
    blocks = mcq_blocks(options, q_id)

    # Should have 1 actions block
    assert len(blocks) == 1
    assert blocks[0]["type"] == "actions"

    # Should have 4 button elements (one per option)
    elements = blocks[0]["elements"]
    assert len(elements) == 4

    # First button should be option A
    btn = elements[0]
    assert btn["type"] == "button"
    assert btn["text"]["text"].startswith("A.")
    assert btn["action_id"] == f"mcq_{q_id[:12]}_A"
    assert btn["value"] == f"{q_id[:12]}:A"


def test_mcq_blocks_action_id_format():
    """Action IDs and values should follow the expected pattern."""
    options = {"A": "x" * 100}
    q_id = "a" * 50
    blocks = mcq_blocks(options, q_id)
    btn = blocks[0]["elements"][0]
    # action_id should use truncated question_id
    assert btn["action_id"] == f"mcq_{q_id[:12]}_A"
    assert btn["value"] == f"{q_id[:12]}:A"


def test_roles_blocks():
    roles = ["backend_engineer", "frontend_engineer"]
    selected = {"backend_engineer"}
    blocks = roles_blocks(roles, selected)

    # Should have action blocks for roles + 1 Done block
    assert len(blocks) >= 2

    # Find the role buttons (first block)
    role_elements = blocks[0]["elements"]
    # First button should show checkmark (selected)
    assert "\u2713" in role_elements[0]["text"]["text"]
    # Selected button should have "primary" style
    assert role_elements[0].get("style") == "primary"

    # Last block should be the Done button
    done_block = blocks[-1]
    assert done_block["type"] == "actions"
    done_btn = done_block["elements"][0]
    assert "Done" in done_btn["text"]["text"]
    assert done_btn["action_id"] == "role_done"


def test_languages_blocks():
    available = ["Python", "Go", "TypeScript", "Rust", "Java"]
    selected = {"Python", "Go"}
    blocks = languages_blocks(available, selected)

    # Should have at least 2 blocks (language rows + skip/done row)
    assert len(blocks) >= 2

    # Last block should have skip and done buttons
    last_block = blocks[-1]
    last_elements = last_block["elements"]
    action_ids = {el["action_id"] for el in last_elements}
    assert "lang_skip" in action_ids
    assert "lang_done" in action_ids


def test_frameworks_blocks():
    available = ["Django", "FastAPI", "React", "Next.js"]
    selected = {"Django"}
    blocks = frameworks_blocks(available, selected)

    # Should have at least 2 blocks (framework rows + skip/done row)
    assert len(blocks) >= 2

    # Last block should have skip and done buttons
    last_block = blocks[-1]
    last_elements = last_block["elements"]
    action_ids = {el["action_id"] for el in last_elements}
    assert "fw_skip" in action_ids
    assert "fw_done" in action_ids


def test_formats_blocks():
    selected = {"mcq", "debugging"}
    blocks = formats_blocks(selected)

    # Should have 2 blocks: format buttons + done button
    assert len(blocks) == 2

    # First block should have format buttons
    fmt_elements = blocks[0]["elements"]
    assert len(fmt_elements) == 5  # all 5 formats

    # Check that selected formats have checkmark and primary style
    for el in fmt_elements:
        text = el["text"]["text"]
        if "Multiple Choice" in text or "Debugging" in text:
            assert "\u2713" in text
            assert el.get("style") == "primary"

    # Last block should be the Done button
    done_btn = blocks[-1]["elements"][0]
    assert done_btn["action_id"] == "fmt_done"


def test_length_blocks():
    blocks = length_blocks("standard")
    assert len(blocks) == 1
    elements = blocks[0]["elements"]
    assert len(elements) == 3  # concise, standard, detailed

    # "Standard" should have checkmark and primary style
    for el in elements:
        if "Standard" in el["text"]["text"]:
            assert "\u2713" in el["text"]["text"]
            assert el.get("style") == "primary"


def test_confirm_blocks():
    blocks = confirm_blocks("confirm_yes", "confirm_no")
    assert len(blocks) == 1
    elements = blocks[0]["elements"]
    assert len(elements) == 2

    # Yes button
    assert elements[0]["text"]["text"] == "Yes"
    assert elements[0]["action_id"] == "confirm_yes"
    assert elements[0]["value"] == "yes"
    assert elements[0].get("style") == "primary"

    # No button
    assert elements[1]["text"]["text"] == "No"
    assert elements[1]["action_id"] == "confirm_no"
    assert elements[1]["value"] == "no"


def test_session_count_blocks():
    blocks = session_count_blocks()
    assert len(blocks) == 1
    elements = blocks[0]["elements"]
    assert len(elements) == 3

    texts = {el["text"]["text"] for el in elements}
    assert texts == {"3", "5", "10"}

    # Verify action_ids follow expected pattern
    action_ids = {el["action_id"] for el in elements}
    assert action_ids == {"session_3", "session_5", "session_10"}

    # Verify values match
    values = {el["value"] for el in elements}
    assert values == {"3", "5", "10"}


def test_post_answer_blocks():
    q_id = "abc123def456ghij"
    blocks = post_answer_blocks(q_id)
    assert len(blocks) == 1
    elements = blocks[0]["elements"]
    assert len(elements) == 2

    # Bookmark button
    texts = {el["text"]["text"] for el in elements}
    assert "Bookmark" in texts
    assert "Next Question" in texts

    # Verify bookmark action_id uses truncated question_id
    bookmark_btn = next(el for el in elements if el["text"]["text"] == "Bookmark")
    assert bookmark_btn["action_id"] == f"bookmark_{q_id[:12]}"
    assert bookmark_btn["value"] == q_id[:12]

    # Verify next question button
    next_btn = next(el for el in elements if el["text"]["text"] == "Next Question")
    assert next_btn["action_id"] == "next_q"
    assert next_btn["value"] == "next"
    assert next_btn.get("style") == "primary"
