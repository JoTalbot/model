"""
swarm/cli_peer_patch.py
────────────────────────
Минимальный патч для подключения `peer` команд к существующему CLI.

Добавь в конец swarm/cli.py:

    # ─── Peer Commands ──────────────────────────────────────────────────────
    from swarm.cli_peer import peer as peer_cli
    cli.add_command(peer_cli)

Больше ничего менять не нужно.
"""
