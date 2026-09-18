"""Octopus TG-bot bridge to AIOS quant/digest commands (Wave 3, item 4).

Why this module exists:
- octopus-tg-bot.py speaks Markdown-only via tg_send(); AIOS quant/trading
  commands return Telegram-HTML. html_to_markdown() converts.
- AIOS LLM analytics requires network + keys; the sync /digest command path
  stays offline (snapshot only). Full LLM digest ships with Wave 5.

Enable with OCTOPUS_TGBOT_QUANT=1 (see octopus-tg-bot.py SYNC_MAP patch).
"""

from __future__ import annotations

import html as _html
import os
import re

from swarm.tgbot import quant_cmds, trading_report

FLAG = "OCTOPUS_TGBOT_QUANT"


def enabled() -> bool:
    """True when quant commands are switched on via env flag."""
    return os.environ.get(FLAG, "0") == "1"


_BOLD = re.compile(r"<b>(.*?)</b>", re.DOTALL)
_ITALIC = re.compile(r"<i>(.*?)</i>", re.DOTALL)
_UNDER = re.compile(r"<u>(.*?)</u>", re.DOTALL)
_CODE = re.compile(r"<code>(.*?)</code>", re.DOTALL)
_PRE = re.compile(r"<pre>(.*?)</pre>", re.DOTALL)
_LINK = re.compile(r'<a\s+href="([^"]*)">(.*?)</a>', re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def html_to_markdown(text: str) -> str:
    """Convert Telegram-HTML (AIOS quant/trading output) to Markdown.

    octopus-tg-bot.py tg_send() sends parse_mode Markdown, so <b>/<i>/<code>
    and links must be rewritten. Unknown tags are stripped.
    """
    text = _BOLD.sub(r"*\1*", text)
    text = _ITALIC.sub(r"_\1_", text)
    text = _UNDER.sub(r"_\1_", text)
    text = _CODE.sub(r"`\1`", text)
    text = _PRE.sub(r"```\n\1\n```", text)
    text = _LINK.sub(r"[\2](\1)", text)
    text = _TAG.sub("", text)
    return _html.unescape(text)


# --- SYNC_MAP-compatible wrappers (each takes the command's `rest` arg) ---


def cmd_quant_text(_arg: str = "") -> str:
    """Offline quant pipeline status (/quant)."""
    return html_to_markdown(quant_cmds.cmd_quant())


def cmd_ab_text(_arg: str = "") -> str:
    """DCA paper control A/B snapshot (/ab)."""
    return html_to_markdown(quant_cmds.cmd_ab())


def cmd_basket_text(_arg: str = "") -> str:
    """DCA VA basket snapshot (/basket)."""
    return html_to_markdown(quant_cmds.cmd_basket())


def cmd_scoreboard_text(_arg: str = "") -> str:
    """Quant metrics scoreboard (/scoreboard)."""
    return html_to_markdown(quant_cmds.cmd_scoreboard())


def cmd_digest_text(_arg: str = "") -> str:
    """Offline trading digest snapshot (/digest, no LLM analytics).

    Uses format_report() (pure snapshot text) rather than full_report()
    so the sync command path never touches the network.
    """
    snap = trading_report.build_snapshot()
    return html_to_markdown("\n\n".join(trading_report.format_report(snap)))
