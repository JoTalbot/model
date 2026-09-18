"""
swarm/cli_recruit.py
─────────────────────
CLI-команды для управления Gossip-рекрутингом.

Подключение в swarm/cli.py:
    from swarm.cli_recruit import recruit as recruit_cli
    cli.add_command(recruit_cli)

Команды
───────
  recruit status    — статистика рекрутинга
  recruit start     — включить рекрутинг (на лету)
  recruit stop      — выключить рекрутинг
  recruit broadcast — немедленно разослать RECRUIT
  recruit pack      — упаковать исходники в zip (проверка)
"""
from __future__ import annotations

import asyncio
import json as json_module
import sys
import time
from pathlib import Path

import click

from swarm.bootstrap.config import load_config


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _rpc(cfg: dict, method: str, params: dict):
    from swarm.network.rpc import RPCClient
    port     = int((cfg.get("node") or {}).get("port", 8000))
    rpc_port = port + 2000
    client   = RPCClient()
    try:
        return await client.call("127.0.0.1", rpc_port, method, params)
    except Exception as exc:
        raise click.ClickException(
            f"Нода недоступна на порту {rpc_port}: {exc}\n"
            "Запусти: python node.py start"
        )

def _run(coro):
    return asyncio.run(coro)


# ── Группа ────────────────────────────────────────────────────────────────────

@click.group("recruit")
def recruit():
    """Gossip-рекрутинг новых нод роя."""
    pass


# ── recruit status ────────────────────────────────────────────────────────────

@recruit.command("status")
@click.option("--config", default="config.yaml")
@click.option("--json", "output_json", is_flag=True)
def recruit_status(config: str, output_json: bool):
    """Статистика рекрутинга текущей ноды.

    \b
    Показывает:
      • сколько нод завербовано / максимум
      • размер архива исходников
      • активные дочерние процессы
      • включён ли RecruitHandler

    \b
    Пример:
      python node.py recruit status
    """
    cfg = load_config(config)
    res = _run(_rpc(cfg, "recruit_stats", {}))

    if output_json:
        click.echo(json_module.dumps(res, ensure_ascii=False, indent=2))
        return

    if not res or res.get("error"):
        raise click.ClickException("Нода не вернула статистику рекрутинга")

    r = res.get("recruiter")
    h = res.get("handler")

    click.echo(f"\n{'Рекрутинг':═<40}")

    if r:
        click.echo("\n  \033[36m● Вербовщик (Recruiter)\033[0m")
        click.echo(f"    Завербовано:  {r['recruited']} / {r['max_recruits']}")
        click.echo(f"    Архив:        {r['archive_size'] // 1024} KB  [{r['digest']}]")
        click.echo(f"    Интервал:     {r['interval']:.0f}s")
    else:
        click.echo("\n  Вербовщик: \033[33mотключён\033[0m")

    if h:
        enabled_str = "\033[32m✓ включён\033[0m" if h["enabled"] else "\033[31m✗ выключен\033[0m"
        click.echo(f"\n  \033[35m● Кандидат (Handler)\033[0m")
        click.echo(f"    Статус:       {enabled_str}")
        click.echo(f"    Дочерних:     {h['active_children']} / {h['max_children']}")
        click.echo(f"    Последний спавн: {_ts(h['last_spawn'])}")
        click.echo(f"    Известных вербовщиков: {h['seen_recruiters']}")
    else:
        click.echo("\n  Кандидат: \033[33mотключён\033[0m")

    click.echo()


# ── recruit start / stop ──────────────────────────────────────────────────────

@recruit.command("start")
@click.option("--config", default="config.yaml")
def recruit_start(config: str):
    """Включить RecruitHandler (принимать приглашения).

    \b
    Пример:
      python node.py recruit start
    """
    cfg = load_config(config)
    res = _run(_rpc(cfg, "recruit_enable", {"enabled": True}))
    if res and res.get("ok"):
        click.echo("\033[32m✓ RecruitHandler включён — нода будет принимать RECRUIT\033[0m")
    else:
        click.echo("\033[31m✗ Ошибка\033[0m", err=True)
        sys.exit(1)


@recruit.command("stop")
@click.option("--config", default="config.yaml")
def recruit_stop(config: str):
    """Выключить RecruitHandler (игнорировать приглашения).

    \b
    Пример:
      python node.py recruit stop
    """
    cfg = load_config(config)
    res = _run(_rpc(cfg, "recruit_enable", {"enabled": False}))
    if res and res.get("ok"):
        click.echo("\033[33m● RecruitHandler выключен\033[0m")
    else:
        click.echo("\033[31m✗ Ошибка\033[0m", err=True)
        sys.exit(1)


# ── recruit broadcast ─────────────────────────────────────────────────────────

@recruit.command("broadcast")
@click.option("--config", default="config.yaml")
def recruit_broadcast(config: str):
    """Немедленно разослать RECRUIT всем пирам.

    \b
    Используй для отладки или принудительного расширения роя.

    \b
    Пример:
      python node.py recruit broadcast
    """
    cfg = load_config(config)
    res = _run(_rpc(cfg, "recruit_broadcast_now", {}))
    if res and res.get("ok"):
        digest = res.get("digest", "?")
        click.echo(f"✅ RECRUIT разослан (digest={digest}...)")
    else:
        reason = (res or {}).get("reason", "неизвестная ошибка")
        click.echo(f"\033[31m✗ {reason}\033[0m", err=True)
        sys.exit(1)


# ── recruit pack ──────────────────────────────────────────────────────────────

@recruit.command("pack")
@click.option("--output", "-o", default=None, help="Сохранить zip в файл")
@click.option("--root",   "-r", default=None, help="Корень проекта (по умолчанию — автодетект)")
@click.option("--list",   "show_list", is_flag=True, help="Показать список файлов в архиве")
def recruit_pack(output: str | None, root: str | None, show_list: bool):
    """Упаковать исходники в zip-архив (проверка).

    \b
    Позволяет убедиться, что архив корректен перед включением рекрутинга.

    \b
    Примеры:
      python node.py recruit pack
      python node.py recruit pack --output swarm.zip
      python node.py recruit pack --list
    """
    from swarm.recruit.recruiter import SourcePacker
    import zipfile

    packer = SourcePacker(root)
    click.echo(f"📦 Упаковываем {packer.root} ...")

    data, digest = packer.pack()

    click.echo(f"   Размер:  {len(data) // 1024} KB ({len(data):,} байт)")
    click.echo(f"   SHA-256: {digest}")

    if show_list:
        import io
        click.echo(f"\n   Файлы в архиве:")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in sorted(zf.infolist(), key=lambda x: x.filename):
                kb = info.file_size // 1024
                click.echo(f"     {info.filename:<60} {kb:>5} KB")

    if output:
        Path(output).write_bytes(data)
        click.echo(f"\n✅ Сохранено в: {output}")
    else:
        click.echo("\n💡 Используй --output swarm.zip для сохранения")


# ── Утилиты ───────────────────────────────────────────────────────────────────

def _ts(t: float) -> str:
    if not t:
        return "никогда"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
