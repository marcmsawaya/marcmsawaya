import pytest

from notion_form_ai.notion_api import (
    _MAX_RICH_TEXT,
    _property_payload,
    _text_to_blocks,
    replace_placeholders,
)


def test_title():
    assert _property_payload("title", "Dinner") == {
        "title": [{"type": "text", "text": {"content": "Dinner"}}]
    }


def test_rich_text():
    assert _property_payload("rich_text", 42)["rich_text"][0]["text"]["content"] == "42"


def test_title_and_rich_text_capped_at_2000():
    long = "x" * 5000
    assert len(_property_payload("title", long)["title"][0]["text"]["content"]) == _MAX_RICH_TEXT
    assert (
        len(_property_payload("rich_text", long)["rich_text"][0]["text"]["content"])
        == _MAX_RICH_TEXT
    )


def test_number_int_and_float():
    assert _property_payload("number", "40") == {"number": 40}
    assert _property_payload("number", 3.5) == {"number": 3.5}
    with pytest.raises(ValueError):
        _property_payload("number", "forty")


def test_select_and_status():
    assert _property_payload("select", "Food") == {"select": {"name": "Food"}}
    assert _property_payload("status", "Done") == {"status": {"name": "Done"}}


def test_multi_select_from_list_and_comma_string():
    assert _property_payload("multi_select", ["a", "b"]) == {
        "multi_select": [{"name": "a"}, {"name": "b"}]
    }
    assert _property_payload("multi_select", "a, b") == {
        "multi_select": [{"name": "a"}, {"name": "b"}]
    }
    assert _property_payload("multi_select", "solo") == {"multi_select": [{"name": "solo"}]}


def test_date_string_and_range():
    assert _property_payload("date", "2026-07-21") == {"date": {"start": "2026-07-21"}}
    rng = {"start": "2026-07-21", "end": "2026-07-25"}
    assert _property_payload("date", rng) == {"date": rng}


def test_checkbox_coercion():
    assert _property_payload("checkbox", True) == {"checkbox": True}
    assert _property_payload("checkbox", "yes") == {"checkbox": True}
    assert _property_payload("checkbox", "no") == {"checkbox": False}


def test_url_email_phone():
    assert _property_payload("url", "https://x.com") == {"url": "https://x.com"}
    assert _property_payload("email", "a@b.c") == {"email": "a@b.c"}
    assert _property_payload("phone_number", "123") == {"phone_number": "123"}


def test_relation_and_people():
    assert _property_payload("relation", "abc") == {"relation": [{"id": "abc"}]}
    assert _property_payload("people", ["u1", "u2"]) == {
        "people": [{"object": "user", "id": "u1"}, {"object": "user", "id": "u2"}]
    }


def test_none_clears_field():
    assert _property_payload("select", None) == {"select": None}
    assert _property_payload("rich_text", None) == {"rich_text": []}


def test_unsupported_type():
    with pytest.raises(ValueError):
        _property_payload("formula", "x")


def test_replace_placeholders_basic():
    out = replace_placeholders(
        "Hello {{name}}, due {{ Due Date }}!", {"name": "Marc", "due date": "Friday"}
    )
    assert out == "Hello Marc, due Friday!"


def test_replace_placeholders_unknown_left_alone():
    assert replace_placeholders("Keep {{mystery}}", {}) == "Keep {{mystery}}"


def test_text_to_blocks():
    blocks = _text_to_blocks("# Head\n- item\nplain text\n\n")
    assert [b["type"] for b in blocks] == ["heading_1", "bulleted_list_item", "paragraph"]
    assert blocks[0]["heading_1"]["rich_text"][0]["text"]["content"] == "Head"


def test_text_to_blocks_long_body_not_truncated():
    # Long bodies are appended in 100-block chunks by the client, not dropped.
    blocks = _text_to_blocks("\n".join(f"line {i}" for i in range(250)))
    assert len(blocks) == 250
