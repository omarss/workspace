"""Tests for Telegram inline keyboard builders."""

import os

# Set env vars before imports
os.environ.setdefault("SWET_TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from swet_telegram.keyboards import (  # noqa: E402
    bookmark_keyboard,
    confirm_keyboard,
    formats_keyboard,
    frameworks_keyboard,
    languages_keyboard,
    length_keyboard,
    mcq_keyboard,
    post_answer_keyboard,
    roles_keyboard,
    session_count_keyboard,
)


def test_mcq_keyboard():
    options = {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"}
    q_id = "abc123def456ghij"
    kb = mcq_keyboard(options, q_id)

    # Should have 4 rows (one per option)
    assert len(kb.inline_keyboard) == 4

    # First button should be option A
    btn = kb.inline_keyboard[0][0]
    assert btn.text.startswith("A.")
    assert btn.callback_data == f"mcq:{q_id[:12]}:A"


def test_mcq_keyboard_callback_data_fits():
    """Callback data must fit within 64 bytes."""
    options = {"A": "x" * 100}
    q_id = "a" * 50
    kb = mcq_keyboard(options, q_id)
    data = kb.inline_keyboard[0][0].callback_data
    assert len(data.encode("utf-8")) <= 64


def test_roles_keyboard():
    roles = ["backend_engineer", "frontend_engineer"]
    selected = {"backend_engineer"}
    kb = roles_keyboard(roles, selected)

    # 2 role buttons + 1 done button
    assert len(kb.inline_keyboard) == 3

    # First button should show checkmark (selected)
    assert "\u2713" in kb.inline_keyboard[0][0].text
    # Second should not
    assert "\u2713" not in kb.inline_keyboard[1][0].text

    # Last row should be "Done"
    assert "Done" in kb.inline_keyboard[-1][0].text


def test_languages_keyboard():
    available = ["Python", "Go", "TypeScript", "Rust", "Java"]
    selected = {"Python", "Go"}
    kb = languages_keyboard(available, selected)

    # Should have rows of 3 + last row with skip/done
    assert len(kb.inline_keyboard) >= 3  # 2 rows of 3 + 1 skip/done

    # Last row should have skip and done
    last_row = kb.inline_keyboard[-1]
    assert any("Skip" in btn.text for btn in last_row)
    assert any("Done" in btn.text for btn in last_row)


def test_frameworks_keyboard():
    available = ["Django", "FastAPI", "React", "Next.js"]
    selected = {"Django"}
    kb = frameworks_keyboard(available, selected)

    # Should have rows of 2 + last row with skip/done
    assert len(kb.inline_keyboard) >= 3


def test_formats_keyboard():
    selected = {"mcq", "debugging"}
    kb = formats_keyboard(selected)

    # 5 format buttons + 1 done
    assert len(kb.inline_keyboard) == 6

    # Check that selected formats have checkmark
    for row in kb.inline_keyboard[:-1]:
        btn = row[0]
        if "Multiple Choice" in btn.text or "Debugging" in btn.text:
            assert "\u2713" in btn.text


def test_length_keyboard():
    kb = length_keyboard("standard")
    assert len(kb.inline_keyboard) == 3

    # "Standard" should have checkmark
    for row in kb.inline_keyboard:
        if "Standard" in row[0].text:
            assert "\u2713" in row[0].text


def test_confirm_keyboard():
    kb = confirm_keyboard()
    assert len(kb.inline_keyboard) == 1
    assert len(kb.inline_keyboard[0]) == 2
    assert kb.inline_keyboard[0][0].text == "Yes"
    assert kb.inline_keyboard[0][1].text == "No"


def test_session_count_keyboard():
    kb = session_count_keyboard()
    assert len(kb.inline_keyboard) == 1
    assert len(kb.inline_keyboard[0]) == 3
    texts = {btn.text for btn in kb.inline_keyboard[0]}
    assert texts == {"3", "5", "10"}


def test_bookmark_keyboard():
    kb = bookmark_keyboard("abc123def456ghij")
    assert len(kb.inline_keyboard) == 1
    assert "Bookmark" in kb.inline_keyboard[0][0].text
    assert kb.inline_keyboard[0][0].callback_data.startswith("bookmark:")


def test_post_answer_keyboard():
    kb = post_answer_keyboard("abc123def456ghij")
    assert len(kb.inline_keyboard) == 1
    assert len(kb.inline_keyboard[0]) == 2
    texts = {btn.text for btn in kb.inline_keyboard[0]}
    assert "Bookmark" in texts
    assert "Next Question" in texts
