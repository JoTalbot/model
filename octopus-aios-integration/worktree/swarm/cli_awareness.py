"""
swarm/cli_awareness.py
───────────────────────
CLI-команды для работы с awareness роя.

Подключение в swarm/cli.py:
    from swarm.cli_awareness import awareness as awareness_cli
    cli.add_command(awareness_cli)

Команды
───────
  awareness self      — состояние текущей ноды
  awareness map       — карта всех известных нод роя
  awareness skill     — найти ноды с нужным навыком
  awareness healthiest — топ самых здоровых нод
  awareness broadcast — немедленно разослать awareness
  awareness prune     — удалить устаревшие записи
"""
from __future__ import annotations

import asyncio
import json as json_module
import time

import click

from swarm.bootstrap.config import load_config


async def _rpc(cfg: dict, method: str, params: dict):
    from swarm.network.rpc import RPCClient
    port     = int((cfg.get("node") or {}).get("port", 8000))
    rpc_port = port + 2000
    client   = RPCClient()
    try:
        return await client.call("127.0.0.1", rpc_port, method, params)
    except Exception as exc:
        raise click.ClickException(
            f"Нода недоступна на порту {rpc_port}: {exc}"
        )

def _run(coro):
    return asyncio.run(coro)

def _health_color(h: str) -> str:
    c = {"healthy": "\033[32m", "degraded": "\033[33m",
         "overloaded": "\033[31m", "dying": "\033[35m"}
    return c.get(h, "") + h + "\033[0m"

def _score_bar(score: float, width: int = 10) -> str:
    filled = round(score * width)
    bar    = "█" * filled + "░" * (width - filled)
    color  = "\033[32m" if score > 0.7 else "\033[33m" if score > 0.4 else "\033[31m"
    return f"{color}{bar}\033[0m {score:.2f}"


@click.group("awareness")
def awareness():
    """Самоосознание роя — кто, что умеет, в каком состоянии."""
    pass


# ── awareness self ────────────────────────────────────────────────────────────

@awareness.command("self")
@click.option("--config",  default="config.yaml")
@click.option("--json",    "output_json", is_flag=True)
def awareness_self(config: str, output_json: bool):
    """Состояние текущей ноды (самоосознание).

    \b
    Показывает: role, skills, health, load, uptime.

    \b
    Пример:
      python node.py awareness self
    """
    cfg = load_config(config)
    res = _run(_rpc(cfg, "node_self", {}))

    if output_json:
        click.echo(json_module.dumps(res, ensure_ascii=False, indent=2))
        return

    click.echo(f"\n{'Самоосознание ноды':═<44}")
    click.echo(f"  ID:         \033[36m{res.get('node_id', '?')}\033[0m")
    click.echo(f"  Роль:       \033[35m{res.get('role', '?')}\033[0m")
    click.echo(f"  Здоровье:   {_health_color(res.get('health', '?'))}  {_score_bar(res.get('health_score', 0))}")
    click.echo(f"  Uptime:     {_fmt_uptime(res.get('uptime_sec', 0))}")
    click.echo(f"  Роев знает: {res.get('swarm_map_size', 0)} нод")

    skills = res.get("skills", [])
    if skills:
        click.echo(f"\n  Навыки ({len(skills)}):")
        for sk in skills:
            click.echo(f"    \033[32m●\033[0m {sk}")
    else:
        click.echo("  Навыки: (нет)")

    known_roles  = res.get("known_roles", [])
    known_skills = res.get("known_skills", [])
    if known_roles:
        click.echo(f"\n  Роли в рое:   {', '.join(known_roles)}")
    if known_skills:
        click.echo(f"  Навыки в рое: {', '.join(known_skills[:8])}")
    click.echo()


# ── awareness map ─────────────────────────────────────────────────────────────

@awareness.command("map")
@click.option("--config",  default="config.yaml")
@click.option("--json",    "output_json", is_flag=True)
@click.option("--skill",   default=None,  help="Фильтр по навыку")
def awareness_map(config: str, output_json: bool, skill: str | None):
    """Карта всех известных нод роя.

    \b
    Примеры:
      python node.py awareness map
      python node.py awareness map --skill web_parser
      python node.py awareness map --json
    """
    cfg    = load_config(config)
    params = {"skill": skill} if skill else {}
    res    = _run(_rpc(cfg, "swarm_map", params))

    if output_json:
        click.echo(json_module.dumps(res, ensure_ascii=False, indent=2))
        return

    nodes = res.get("nodes", [])
    title = f"Карта роя ({res.get('count', 0)} нод)"
    if skill:
        title += f" [skill={skill}]"
    click.echo(f"\n{title:═<50}")

    if not nodes:
        click.echo("  (нет известных нод)")
        click.echo()
        return

    click.echo(f"  {'NODE ID':<16} {'РОЛЬ':<12} {'ЗДОРОВЬЕ':<12} {'SCORE':>6} {'НАВЫКИ'}")
    click.echo(f"  {'─'*16} {'─'*12} {'─'*12} {'─'*6} {'─'*24}")

    for n in sorted(nodes, key=lambda x: x.get("health_score", 0), reverse=True):
        nid    = str(n.get("node_id", "?"))[:16]
        role   = str(n.get("role", "?"))[:12]
        health = str(n.get("health", "?"))
        score  = float(n.get("health_score", 0))
        skills = ", ".join(s["name"] for s in n.get("skills", []))[:30]
        h_str  = _health_color(health)
        s_str  = f"{score:.2f}"
        click.echo(f"  \033[36m{nid:<16}\033[0m \033[35m{role:<12}\033[0m {h_str:<20} {s_str:>6} {skills}")

    click.echo()


# ── awareness skill ───────────────────────────────────────────────────────────

@awareness.command("skill")
@click.argument("skill_name")
@click.option("--config", default="config.yaml")
def awareness_skill(skill_name: str, config: str):
    """Найти ноды с нужным навыком.

    \b
    Пример:
      python node.py awareness skill web_parser
      python node.py awareness skill local_llm
    """
    cfg   = load_config(config)
    res   = _run(_rpc(cfg, "swarm_map", {"skill": skill_name}))
    nodes = res.get("nodes", [])

    click.echo(f"\nНоды с навыком \033[33m{skill_name}\033[0m: {len(nodes)}")
    if not nodes:
        click.echo("  (нет)")
    else:
        for n in nodes:
            nid   = str(n.get("node_id", "?"))[:20]
            score = float(n.get("health_score", 0))
            click.echo(
                f"  \033[36m{nid}\033[0m  "
                f"{_health_color(n.get('health','?'))}  "
                f"{_score_bar(score, 8)}"
            )
    click.echo()


# ── awareness healthiest ──────────────────────────────────────────────────────

@awareness.command("healthiest")
@click.option("--n",      default=5,  type=int, show_default=True)
@click.option("--config", default="config.yaml")
@click.option("--json",   "output_json", is_flag=True)
def awareness_healthiest(n: int, config: str, output_json: bool):
    """Топ-N самых здоровых нод роя.

    \b
    Пример:
      python node.py awareness healthiest
      python node.py awareness healthiest --n 10
    """
    cfg = load_config(config)
    res = _run(_rpc(cfg, "swarm_healthiest", {"n": n}))

    if output_json:
        click.echo(json_module.dumps(res, ensure_ascii=False, indent=2))
        return

    nodes = res.get("nodes", [])
    click.echo(f"\nТоп-{n} здоровых нод:\n")
    if not nodes:
        click.echo("  (нет данных)")
    else:
        for i, nd in enumerate(nodes, 1):
            nid   = str(nd.get("node_id", "?"))[:20]
            score = float(nd.get("health_score", 0))
            role  = nd.get("role", "?")
            click.echo(
                f"  [{i}] \033[36m{nid}\033[0m  "
                f"\033[35m{role:<12}\033[0m  "
                f"{_score_bar(score)}"
            )
    click.echo()


# ── awareness broadcast ───────────────────────────────────────────────────────

@awareness.command("broadcast")
@click.option("--config", default="config.yaml")
def awareness_broadcast(config: str):
    """Немедленно разослать NODE_AWARENESS всем пирам.

    \b
    Пример:
      python node.py awareness broadcast
    """
    cfg = load_config(config)
    res = _run(_rpc(cfg, "awareness_broadcast", {}))
    if res and res.get("ok"):
        click.echo("✅ NODE_AWARENESS разослан")
    else:
        click.echo("\033[31m✗ Ошибка\033[0m", err=True)


# ── awareness prune ───────────────────────────────────────────────────────────

@awareness.command("prune")
@click.option("--ttl",    default=120, type=int, show_default=True,
              help="Удалить ноды без активности старше N секунд")
@click.option("--config", default="config.yaml")
def awareness_prune(ttl: int, config: str):
    """Удалить устаревшие записи из карты роя.

    \b
    Пример:
      python node.py awareness prune --ttl 60
    """
    cfg = load_config(config)
    res = _run(_rpc(cfg, "swarm_prune", {"ttl": ttl}))
    if res and res.get("ok"):
        pruned = res.get("pruned", 0)
        click.echo(f"🧹 Удалено устаревших нод: {pruned}")
    else:
        click.echo("\033[31m✗ Ошибка\033[0m", err=True)


# ── Утилиты ───────────────────────────────────────────────────────────────────

def _fmt_uptime(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60}s"
    return f"{sec // 3600}h {(sec % 3600) // 60}m"
