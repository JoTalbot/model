"""
swarm/cli_additions.py
───────────────────────
Единая точка подключения всех новых CLI-групп к существующему cli.

Добавь ОДНУ строку в конец swarm/cli.py:

    from swarm.cli_additions import register_all; register_all(cli)

Или вставь вручную перед `if __name__ == "__main__":`:

    from swarm.cli_peer      import peer      as peer_cli
    from swarm.cli_recruit   import recruit   as recruit_cli
    from swarm.cli_awareness import awareness as awareness_cli
    cli.add_command(peer_cli)
    cli.add_command(recruit_cli)
    cli.add_command(awareness_cli)
"""
from __future__ import annotations


def register_all(cli) -> None:
    """Зарегистрировать все новые группы команд в главном CLI."""
    try:
        from swarm.cli_peer import peer as peer_cli
        cli.add_command(peer_cli)
    except ImportError as e:
        import logging; logging.getLogger(__name__).debug("cli_peer skip: %s", e)

    try:
        from swarm.cli_recruit import recruit as recruit_cli
        cli.add_command(recruit_cli)
    except ImportError as e:
        import logging; logging.getLogger(__name__).debug("cli_recruit skip: %s", e)

    try:
        from swarm.cli_awareness import awareness as awareness_cli
        cli.add_command(awareness_cli)
    except ImportError as e:
        import logging; logging.getLogger(__name__).debug("cli_awareness skip: %s", e)
