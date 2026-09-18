import time

from swarm.chat.history import truncate_messages_for_chars
from swarm.chat.room import ChatMessage


def _msg(name: str, content: str) -> ChatMessage:
    return ChatMessage(agent_name=name, role="r", content=content, round_num=1, timestamp=time.time())


def test_truncation_keeps_tail():
    # With chunk = len(content) + 1, tail "TAIL" costs 5; next message must exceed budget.
    msgs = [_msg("user", "A" * 100), _msg("parser", "B" * 146), _msg("analyst", "TAIL")]
    out = truncate_messages_for_chars(msgs, max_chars=150)
    assert len(out) == 1
    assert out[0].content == "TAIL"


def test_truncation_empty_safe():
    assert truncate_messages_for_chars([], 100) == []
