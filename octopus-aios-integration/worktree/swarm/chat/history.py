from __future__ import annotations

from swarm.chat.room import ChatMessage


def truncate_messages_for_chars(messages: list[ChatMessage], max_chars: int) -> list[ChatMessage]:
    if max_chars <= 0 or not messages:
        return list(messages)
    kept: list[ChatMessage] = []
    total = 0
    for m in reversed(messages):
        chunk = len(m.content) + 1
        if total + chunk > max_chars:
            break
        kept.append(m)
        total += chunk
    return list(reversed(kept))
