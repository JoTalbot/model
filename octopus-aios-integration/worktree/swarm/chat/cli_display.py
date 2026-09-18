from __future__ import annotations

import io
import sys

from colorama import Fore, Style, init

from swarm.chat.room import ChatMessage, ChatResult

init(autoreset=True)

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

AGENT_COLORS = {
    "parser": Fore.GREEN,
    "analyst": Fore.CYAN,
    "manager": Fore.YELLOW,
}

AGENT_ICONS = {
    "parser": "[P]",
    "analyst": "[A]",
    "manager": "[M]",
}

DEFAULT_COLOR = Fore.WHITE
DEFAULT_ICON = "[?]"


class ChatDisplay:
    def show_goal(self, goal: str) -> None:
        print(f"\n{Fore.MAGENTA}>>> Задача: {goal}{Style.RESET_ALL}\n")

    def show_message(self, msg: ChatMessage) -> None:
        color = AGENT_COLORS.get(msg.agent_name, DEFAULT_COLOR)
        icon = AGENT_ICONS.get(msg.agent_name, DEFAULT_ICON)
        header = f"{color}[{msg.agent_name.capitalize()} {icon}]{Style.RESET_ALL}"
        print(f"{header} {msg.content}\n")

    def show_result(self, result: ChatResult) -> None:
        status = "=== Chat done ===" if result.finished_naturally else "=== Round limit ==="
        print(f"\n{Fore.WHITE}{Style.BRIGHT}{status} ({result.rounds_used} rounds){Style.RESET_ALL}")
        if result.end_reason:
            print(f"{Fore.YELLOW}{result.end_reason}{Style.RESET_ALL}")
        if result.epilogue:
            print(f"\n{Fore.CYAN}{Style.BRIGHT}Итог:{Style.RESET_ALL}\n{result.epilogue}\n")
