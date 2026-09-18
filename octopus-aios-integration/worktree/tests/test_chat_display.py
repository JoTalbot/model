import time

from swarm.chat.cli_display import ChatDisplay
from swarm.chat.room import ChatMessage, ChatResult


def test_display_formats_message(capsys):
    display = ChatDisplay()
    msg = ChatMessage(
        agent_name="parser",
        role="Парсер цен",
        content="Цена: 3000₽",
        round_num=1,
        timestamp=time.time(),
    )
    display.show_message(msg)
    captured = capsys.readouterr()
    assert "parser" in captured.out.lower() or "Парсер" in captured.out
    assert "3000₽" in captured.out


def test_display_formats_goal(capsys):
    display = ChatDisplay()
    display.show_goal("Найди цены")
    captured = capsys.readouterr()
    assert "Найди цены" in captured.out


def test_display_formats_result(capsys):
    msg = ChatMessage(agent_name="manager", role="Менеджер", content="Done", round_num=2, timestamp=time.time())
    result = ChatResult(messages=[msg], rounds_used=2, finished_naturally=True, summary="Done")
    display = ChatDisplay()
    display.show_result(result)
    captured = capsys.readouterr()
    assert "2" in captured.out


def test_display_shows_end_reason_and_epilogue(capsys):
    msg = ChatMessage(agent_name="a", role="r", content="x", round_num=1, timestamp=time.time())
    result = ChatResult(
        messages=[msg],
        rounds_used=1,
        finished_naturally=True,
        summary="x",
        end_reason="LLM call budget exhausted",
        epilogue="Closing notes",
    )
    ChatDisplay().show_result(result)
    out = capsys.readouterr().out
    assert "LLM call budget exhausted" in out
    assert "Closing notes" in out
    assert "Итог:" in out
