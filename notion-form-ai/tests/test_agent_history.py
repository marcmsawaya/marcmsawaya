"""Regression tests for NotionFormAgent history repair (the confirmed
max_tokens / refusal dangling-tool_use bug)."""

from types import SimpleNamespace

from notion_form_ai.agent import NotionFormAgent
from notion_form_ai.config import Settings


def _agent() -> NotionFormAgent:
    settings = Settings(anthropic_api_key="test-key", notion_token="test-token")
    # Avoid constructing a real Anthropic client / hitting the network.
    agent = NotionFormAgent.__new__(NotionFormAgent)
    agent.settings = settings
    agent.on_event = None
    agent.messages = []
    return agent


def test_finalize_answers_dangling_tool_use():
    agent = _agent()
    tool_use = SimpleNamespace(type="tool_use", id="toolu_1", name="x", input={})
    agent.messages = [
        {"role": "user", "content": "do a thing"},
        {"role": "assistant", "content": [tool_use]},  # cut off by max_tokens
    ]
    agent._finalize_history()

    assert len(agent.messages) == 3
    repair = agent.messages[-1]
    assert repair["role"] == "user"
    assert repair["content"][0]["type"] == "tool_result"
    assert repair["content"][0]["tool_use_id"] == "toolu_1"
    assert repair["content"][0]["is_error"] is True


def test_finalize_fills_empty_assistant_turn():
    agent = _agent()
    agent.messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": []},  # e.g. a refusal
    ]
    agent._finalize_history()

    assert len(agent.messages) == 2  # no extra turn appended
    assert agent.messages[-1]["content"] == [{"type": "text", "text": "(no response)"}]


def test_finalize_noop_on_plain_text_turn():
    agent = _agent()
    text = SimpleNamespace(type="text", text="all done")
    agent.messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [text]},
    ]
    agent._finalize_history()
    assert len(agent.messages) == 2
