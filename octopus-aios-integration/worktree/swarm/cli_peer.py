"""
swarm/cli_peer.py
──────────────────
CLI-группа `peer` для управления пирами и handshake.

Подключение в swarm/cli.py (в конце файла):
    from swarm.cli_peer import peer as peer_cli
    cli.add_command(peer_cli)

Команды
───────
  peer list          — список известных пиров (Kademlia + handshake)
  peer handshake     — выполнить handshake с пиром
  peer keys          — показать публичные ключи пиров
  peer info          — подробная информация о конкретном пире
  peer ping          — проверить доступность пира через RPC
  peer auth-status   — статус авторизации текущей ноды

Все команды работают через RPC с локально запущенной нодой
(аналогично `swarm task-list` и другим командам).
"""
from __future__ import annotations

import asyncio
import json as json_module
import sys
import time

import click

from swarm.bootstrap.config import load_config


# ══════════════════════════════════════════════════════════════════════════════
# Helpers (аналогичны _call_local_rpc из cli.py)
# ══════════════════════════════════════════════════════════════════════════════

async def _rpc(cfg: dict, method: str, params: dict):
    from swarm.network.rpc import RPCClient
    node_port = int((cfg.get("node") or {}).get("port", 8000))
    rpc_port  = node_port + 2000
    client    = RPCClient()
    try:
        return await client.call("127.0.0.1", rpc_port, method, params)
    except Exception as exc:
        raise click.ClickException(
            f"Не удалось подключиться к ноде на порту {rpc_port}: {exc}\n"
            "Убедись, что нода запущена: python node.py start"
        )


def _run(coro):
    return asyncio.run(coro)


def _ts(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else "—"


# ══════════════════════════════════════════════════════════════════════════════
# Группа peer
# ══════════════════════════════════════════════════════════════════════════════

@click.group("peer")
def peer():
    """Управление пирами, handshake и авторизацией."""
    pass


# ── peer list ─────────────────────────────────────────────────────────────────

@peer.command("list")
@click.option("--config", default="config.yaml", help="Путь к конфигу")
@click.option("--json", "output_json", is_flag=True, help="Вывод в JSON")
@click.option("--kad",  is_flag=True, help="Только Kademlia DHT пиры")
@click.option("--hs",   is_flag=True, help="Только handshake-верифицированные пиры")
def peer_list(config: str, output_json: bool, kad: bool, hs: bool):
    """Список всех известных пиров ноды.

    \b
    По умолчанию — оба типа: Kademlia DHT и handshake-верифицированные.
    Флаги --kad / --hs ограничивают вывод.

    \b
    Примеры:
      python node.py peer list
      python node.py peer list --hs --json
    """
    cfg = load_config(config)

    async def _get():
        kad_res = {}
        hs_res  = {}
        if not hs:
            kad_res = await _rpc(cfg, "node_status", {})
        if not kad:
            hs_res  = await _rpc(cfg, "peer_list", {})
        return kad_res, hs_res

    kad_res, hs_res = _run(_get())

    kad_peers = []
    if not hs:
        # Kademlia peers — через node_status (или отдельный метод)
        try:
            peers_raw = _run(_rpc(cfg, "network_peers", {}))
            kad_peers = peers_raw.get("peers", []) if isinstance(peers_raw, dict) else []
        except Exception:
            kad_peers = []

    hs_peers = hs_res.get("peers", []) if isinstance(hs_res, dict) else []

    if output_json:
        click.echo(json_module.dumps({
            "kademlia": kad_peers,
            "handshake": hs_peers,
        }, ensure_ascii=False, indent=2))
        return

    # ── Kademlia ─────────────────────────────────────────────────────────────
    if not hs:
        click.echo(f"\n{'Kademlia DHT пиры':─<50}")
        if not kad_peers:
            click.echo("  (нет пиров в DHT)")
        else:
            for i, p in enumerate(kad_peers, 1):
                click.echo(f"  [{i:>2}] \033[35m{p}\033[0m")

    # ── Handshake ────────────────────────────────────────────────────────────
    if not kad:
        click.echo(f"\n{'Handshake-верифицированные пиры':─<50}")
        if not hs_peers:
            click.echo("  (нет верифицированных пиров — выполни: python node.py peer handshake)")
        else:
            click.echo(f"  {'NODE ID':<20} {'АДРЕС':<22} {'ВЕРИФИЦИРОВАН'}")
            click.echo(f"  {'─'*20} {'─'*22} {'─'*20}")
            for p in hs_peers:
                nid  = str(p.get("node_id", "?"))[:20]
                addr = str(p.get("address", "?"))[:22]
                vat  = _ts(p.get("verified_at", 0))
                click.echo(f"  \033[36m{nid:<20}\033[0m {addr:<22} {vat}")

    click.echo()


# ── peer handshake ────────────────────────────────────────────────────────────

@peer.command("handshake")
@click.argument("address", metavar="HOST:RPC_PORT")
@click.option("--config", default="config.yaml", help="Путь к конфигу")
@click.option("--timeout", default=10, type=int, show_default=True,
              help="Таймаут в секундах")
def peer_handshake(address: str, config: str, timeout: int):
    """Выполнить Ed25519 handshake с пиром.

    \b
    ADDRESS — адрес пира в формате HOST:RPC_PORT.
    RPC_PORT = Kademlia_PORT + 2000 (по умолчанию 10000 для ноды на 8000).

    \b
    Примеры:
      python node.py peer handshake 127.0.0.1:10001
      python node.py peer handshake 192.168.1.42:10000
    """
    cfg = load_config(config)

    if ":" not in address:
        raise click.ClickException("Формат адреса: HOST:RPC_PORT (напр. 127.0.0.1:10001)")

    host, port_s = address.rsplit(":", 1)
    try:
        port = int(port_s)
    except ValueError:
        raise click.ClickException(f"Неверный порт: {port_s!r}")

    click.echo(f"🤝 Handshake → {address} ...", nl=False)

    res = _run(_rpc(cfg, "handshake_request", {"host": host, "port": port}))

    if res and res.get("ok"):
        click.echo(" \033[32m✓ OK\033[0m")
        click.echo(f"   Пир добавлен в реестр. Проверь: python node.py peer list --hs")
    else:
        reason = (res or {}).get("reason", "неизвестная ошибка")
        click.echo(f" \033[31m✗ FAIL\033[0m")
        click.echo(f"   Причина: {reason}", err=True)
        sys.exit(1)


# ── peer keys ─────────────────────────────────────────────────────────────────

@peer.command("keys")
@click.option("--node-id", "node_id", default=None, help="ID конкретного пира")
@click.option("--config",  default="config.yaml", help="Путь к конфигу")
@click.option("--json",    "output_json", is_flag=True, help="Вывод в JSON")
def peer_keys(node_id: str | None, config: str, output_json: bool):
    """Показать публичные Ed25519-ключи пиров.

    \b
    Без --node-id — все известные ключи.
    С --node-id   — ключ конкретного пира.

    \b
    Примеры:
      python node.py peer keys
      python node.py peer keys --node-id a3f2b1c9d4e5
    """
    cfg = load_config(config)
    params = {"node_id": node_id} if node_id else {}
    res = _run(_rpc(cfg, "peer_keys", params))

    if not res or res.get("error"):
        raise click.ClickException(str((res or {}).get("error", "ошибка RPC")))

    if output_json:
        click.echo(json_module.dumps(res, ensure_ascii=False, indent=2))
        return

    if node_id:
        # Один пир
        if not res.get("ok"):
            click.echo(f"Пир не найден: {node_id}", err=True)
            sys.exit(1)
        click.echo(f"\nПир:   \033[36m{res['node_id']}\033[0m")
        click.echo(f"Ключ:  \033[35m{res['pubkey']}\033[0m\n")
    else:
        # Все пиры
        keys_map = res.get("keys", {})
        if not keys_map:
            click.echo("Нет известных ключей. Выполни handshake: python node.py peer handshake HOST:PORT")
            return
        click.echo(f"\n{'NODE ID':<20} {'PUBKEY (hex)'}")
        click.echo(f"{'─'*20} {'─'*64}")
        for nid, pubkey in keys_map.items():
            click.echo(f"\033[36m{nid[:20]:<20}\033[0m \033[35m{pubkey}\033[0m")
        click.echo()


# ── peer info ─────────────────────────────────────────────────────────────────

@peer.command("info")
@click.argument("node_id")
@click.option("--config", default="config.yaml", help="Путь к конфигу")
def peer_info(node_id: str, config: str):
    """Подробная информация о конкретном пире.

    \b
    Пример:
      python node.py peer info a3f2b1c9d4e5
    """
    cfg = load_config(config)

    res = _run(_rpc(cfg, "peer_keys", {"node_id": node_id}))
    peers_res = _run(_rpc(cfg, "peer_list", {}))

    # Найти в списке пиров
    peer_data = None
    for p in (peers_res or {}).get("peers", []):
        if p.get("node_id", "").startswith(node_id):
            peer_data = p
            break

    click.echo(f"\n{'Информация о пире':═<40}")
    if peer_data:
        click.echo(f"  Node ID:    \033[36m{peer_data['node_id']}\033[0m")
        click.echo(f"  Адрес:      {peer_data.get('address', '—')}")
        click.echo(f"  Верифицирован: {_ts(peer_data.get('verified_at', 0))}")
    else:
        click.echo(f"  Node ID:    \033[36m{node_id}\033[0m")
        click.echo(f"  (не найден в PeerKeyRegistry)")

    if res and res.get("ok"):
        pk = res.get("pubkey", "")
        click.echo(f"  Pubkey:     \033[35m{pk[:32]}...\033[0m")
        click.echo(f"  (полный):   {pk}")
    click.echo()


# ── peer ping ────────────────────────────────────────────────────────────────

@peer.command("ping")
@click.argument("address", metavar="HOST:RPC_PORT")
@click.option("--config",  default="config.yaml", help="Путь к конфигу")
@click.option("--count",   "-n", default=3, type=int, show_default=True, help="Число пингов")
def peer_ping(address: str, config: str, count: int):
    """Проверить доступность пира через RPC ping.

    \b
    Пример:
      python node.py peer ping 127.0.0.1:10001
      python node.py peer ping 127.0.0.1:10001 -n 5
    """
    from swarm.network.rpc import RPCClient

    if ":" not in address:
        raise click.ClickException("Формат: HOST:RPC_PORT")

    host, port_s = address.rsplit(":", 1)
    try:
        port = int(port_s)
    except ValueError:
        raise click.ClickException(f"Неверный порт: {port_s!r}")

    click.echo(f"PING {address} (RPC) × {count}\n")

    client = RPCClient()
    ok_count = 0

    for i in range(1, count + 1):
        t0 = time.perf_counter()
        try:
            res = _run(client.call(host, port, "node_status", {}))
            ms  = (time.perf_counter() - t0) * 1000
            nid = (res or {}).get("node_id", "?")
            click.echo(f"  [{i}] \033[32m✓\033[0m  {ms:6.1f}ms  node_id={nid[:16]}...")
            ok_count += 1
        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            click.echo(f"  [{i}] \033[31m✗\033[0m  {ms:6.1f}ms  {exc}")

    click.echo(f"\n{ok_count}/{count} успешно\n")
    if ok_count == 0:
        sys.exit(1)


# ── peer auth-status ──────────────────────────────────────────────────────────

@peer.command("auth-status")
@click.option("--config",  default="config.yaml", help="Путь к конфигу")
@click.option("--json",    "output_json", is_flag=True, help="Вывод в JSON")
def peer_auth_status(config: str, output_json: bool):
    """Статус авторизации текущей ноды.

    \b
    Показывает:
      - включён ли HMAC / Ed25519
      - публичный ключ ноды
      - количество верифицированных пиров
      - статистику handshake

    \b
    Пример:
      python node.py peer auth-status
    """
    cfg = load_config(config)
    res = _run(_rpc(cfg, "node_status", {}))

    if output_json:
        click.echo(json_module.dumps(res, ensure_ascii=False, indent=2))
        return

    if not res or res.get("error"):
        raise click.ClickException("Нода недоступна")

    auth = res.get("auth", {})
    hs   = res.get("handshake", {})

    def _bool_str(v):
        if v:
            return "\033[32m✓ Включён\033[0m"
        return "\033[33m✗ Выключен\033[0m"

    click.echo(f"\n{'Статус авторизации':═<42}")
    click.echo(f"  Node ID:           \033[36m{res.get('node_id', '?')}\033[0m")
    click.echo(f"  Порт:              {res.get('port', '?')}")
    click.echo()
    click.echo(f"  HMAC-SHA256:       {_bool_str(auth.get('hmac_enabled'))}")
    click.echo(f"  Ed25519:           {_bool_str(auth.get('ed25519'))}")
    click.echo()

    pubkey = auth.get("pubkey", "")
    if pubkey:
        click.echo(f"  Публичный ключ:    \033[35m{pubkey[:32]}...\033[0m")
        click.echo(f"  (полный hex):      {pubkey}")
    else:
        click.echo("  Публичный ключ:    \033[33m(нет — auth отключён)\033[0m")
    click.echo()

    vp = auth.get("verified_peers", 0)
    click.echo(f"  Верифицированных пиров: \033[36m{vp}\033[0m")

    if hs:
        click.echo(f"  Pending handshakes:    {hs.get('pending_shakes', 0)}")
        click.echo(f"  Ed25519 required:      {hs.get('require_ed25519', False)}")

    click.echo()

    # Подсказки
    if not auth.get("hmac_enabled") and not auth.get("ed25519"):
        click.echo("  \033[33m⚠ Авторизация отключена. Включи в config.yaml:\033[0m")
        click.echo("    auth:")
        click.echo("      enabled: true")
        click.echo("      shared_secret: \"my-secret\"")
    elif not auth.get("ed25519"):
        click.echo("  \033[33m💡 Совет: включи Ed25519 для максимальной защиты:\033[0m")
        click.echo("    auth:")
        click.echo("      require_ed25519: true")
    click.echo()
