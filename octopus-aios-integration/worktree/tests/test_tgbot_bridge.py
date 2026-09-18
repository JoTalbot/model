"""Wave 3: octopus TG-bot quant bridge is offline-safe and Markdown-clean.

- html_to_markdown covers every tag AIOS quant/trading output can emit
- commands work against an EMPTY OCTOPUS_DATA_DIR (no fixture data)
- commands never touch the network (no HTTP/socket monkeypatch failures)
"""

import pytest

from swarm.tgbot import bot_commands as bc


@pytest.mark.parametrize(
    "src, expected",
    [
        ("<b>жирно</b>", "*жирно*"),
        ("<i>курсив</i>", "_курсив_"),
        ("<u>подчёрк</u>", "_подчёрк_"),
        ("<code>print(1)</code>", "`print(1)`"),
        ("<pre>x=1</pre>", "```\nx=1\n```"),
        ('<a href="https://t.me/x">канал</a>', "[канал](https://t.me/x)"),
        ("<b>a</b> &amp; &lt;code&gt;", "*a* & <code>"),
        ("<tg-spoiler>скрыто</tg-spoiler>", "скрыто"),
        ("plain text без тегов", "plain text без тегов"),
    ],
)
def test_html_to_markdown(src, expected):
    assert bc.html_to_markdown(src) == expected


def test_enabled_flag(monkeypatch):
    monkeypatch.delenv("OCTOPUS_TGBOT_QUANT", raising=False)
    assert bc.enabled() is False
    monkeypatch.setenv("OCTOPUS_TGBOT_QUANT", "1")
    assert bc.enabled() is True


def _offline(monkeypatch):
    """Fail loudly on any network attempt."""
    import socket

    def _boom(*a, **k):
        raise AssertionError("network access in offline test")

    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(socket, "socket", _boom)


@pytest.mark.parametrize(
    "fn",
    [bc.cmd_quant_text, bc.cmd_ab_text, bc.cmd_basket_text, bc.cmd_scoreboard_text],
)
def test_quant_commands_offline_empty_data(monkeypatch, tmp_path, fn):
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OCTOPUS_TGBOT_QUANT", "1")
    _offline(monkeypatch)
    text = fn("")
    assert isinstance(text, str) and len(text) > 10
    assert "<" not in text and ">" not in text  # no HTML leaked


def test_digest_offline_empty_data(monkeypatch, tmp_path):
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OCTOPUS_TGBOT_QUANT", "1")
    _offline(monkeypatch)
    text = bc.cmd_digest_text("")
    assert isinstance(text, str) and len(text) > 10
    assert "<" not in text and ">" not in text
