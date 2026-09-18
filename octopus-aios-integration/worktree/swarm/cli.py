from __future__ import annotations

import asyncio
import json as json_module
import logging
import time

import click

from swarm.bootstrap.config import load_config
from swarm.chat.cli_display import ChatDisplay
from swarm.chat.participant import AgentParticipant, ParserParticipant
from swarm.chat.room import ChatConfig, ChatRoom
from swarm.chat.selector import LLMSelector, RoundRobinSelector
from swarm.llm.key_pool import APIKey, KeyPool
from swarm.llm.router import LLMRouter
from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.repository import MemoryRepository
from swarm.runtime import AppContainer, AppRuntime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("swarm")


def _mdns_available() -> bool:
    try:
        import zeroconf  # noqa: F401
    except ImportError:
        return False
    return True


def _yaml_bootstrap_addr(cfg: dict) -> tuple[str, int] | None:
    node = cfg.get("node") or {}
    b = node.get("bootstrap", [])
    if isinstance(b, str) and b.strip():
        b = [b.strip()]
    if not b:
        return None
    first = b[0]
    if isinstance(first, str) and ":" in first:
        host, port_s = first.rsplit(":", 1)
        return host.strip(), int(port_s.strip())
    return None


async def _lan_peer_lines(cfg: dict) -> list[str]:
    chat_cfg = cfg.get("chat") or {}
    mdns_cfg = cfg.get("mdns") or {}
    if not chat_cfg.get("lan_hints") or not mdns_cfg.get("enabled") or not _mdns_available():
        return []
    from swarm.network.mdns import SwarmMDNS

    node_port = int((cfg.get("node") or {}).get("port", 8000))
    m = SwarmMDNS(
        mdns_cfg.get("service_type", "_immortal-swarm._tcp.local."),
        float(mdns_cfg.get("refresh_interval_seconds", 60)),
        float(mdns_cfg.get("initial_browse_seconds", 5)),
    )
    host = str((cfg.get("node") or {}).get("advertise_host", "127.0.0.1"))
    try:
        await m.start(
            host=host,
            ports={"kad": node_port},
            node_id="chat-hint",
            instance_suffix="chat-hint",
            register=False,
        )
        return [
            f"kad={p.get('kad')} host={p.get('host')} id={p.get('kid', '')}"
            for p in m.peers_snapshot()[:10]
        ]
    finally:
        await m.stop()


def _llm_local_router_kwargs(llm_cfg: dict) -> dict:
    """Optional OpenAI-compatible local server (e.g. llama.cpp). Empty if disabled."""
    loc = llm_cfg.get("local") or {}
    if not loc.get("enabled"):
        return {}
    base = (loc.get("base_url") or "").strip()
    models = loc.get("models") or []
    if not base or not models:
        return {}
    out: dict = {
        "local_base_url": base,
        "local_models": list(models),
        "prefer_local": bool(loc.get("prefer_local", False)),
    }
    ak = loc.get("api_key")
    if isinstance(ak, str) and ak.strip():
        out["local_api_key"] = ak.strip()
    aliases = loc.get("model_aliases") or {}
    if isinstance(aliases, dict) and aliases:
        out["model_aliases"] = dict(aliases)
    return out


def _llm_key_pool(llm_cfg: dict, local_kw: dict) -> KeyPool:
    keys = [APIKey(key=k) for k in llm_cfg.get("keys") or []]
    if keys:
        return KeyPool(keys=keys)
    if local_kw:
        return KeyPool(keys=[APIKey(key="local-placeholder")])
    raise click.ClickException(
        "Add OpenRouter keys to config.yaml (llm.keys), or enable llm.local "
        "with base_url and models for offline mode.",
    )


def _parse_repair_seeds(raw: object) -> list[tuple[str, int]]:
    """Parse ``memory.repair_seeds`` entries like ``host:kad_port``."""
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[tuple[str, int]] = []
    for item in raw:
        if not isinstance(item, str) or ":" not in item:
            continue
        host, _, sport = item.rpartition(":")
        try:
            out.append((host.strip(), int(sport.strip())))
        except ValueError:
            continue
    return out


def _build_local_memory_port(cfg: dict) -> CompositeMemoryPort:
    """Build memory facade for CLI: scratch, optional wiki, optional cloud/http.

    Does not require ``memory_facade.enabled`` or a running node. When
    ``memory_facade.cloud_paste`` enables backends, ``memory insert --store …``
    can write to anonymous online pastebins (same adapters as the full node).
    """
    from swarm.memory.adapters.obsidian import ObsidianVaultAdapter
    from swarm.memory.factory import extend_memory_facade_network_adapters
    from swarm.memory.types import MemoryAdapterError

    facade_cfg = cfg.get("memory_facade") or {}
    scratch_root = facade_cfg.get("scratch_root", ".swarm_scratch")
    adapters: dict[str, object] = {"file": LocalScratchAdapter(scratch_root)}
    obs_cfg = facade_cfg.get("obsidian") or {}
    if obs_cfg.get("enabled"):
        vault_root = obs_cfg.get("vault_root") or f"{scratch_root}/wiki"
        adapters["obsidian"] = ObsidianVaultAdapter(vault_root)
    try:
        extend_memory_facade_network_adapters(cfg, adapters)
    except MemoryAdapterError as exc:
        raise click.ClickException(str(exc)) from exc
    return CompositeMemoryPort(adapters)


def _build_local_memory_repository(cfg: dict) -> MemoryRepository:
    return MemoryRepository(_build_local_memory_port(cfg))


def build_chat_components(
    cfg: dict,
) -> tuple[list[AgentParticipant], object, ChatConfig, object | None]:
    from swarm.network.outbound_http import outbound_http_proxy_url

    try:
        llm_proxy = outbound_http_proxy_url(cfg)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    llm_cfg = cfg["llm"]
    local_kw = _llm_local_router_kwargs(llm_cfg)
    cloud_models = llm_cfg.get("models") or []
    if not cloud_models and not local_kw:
        raise click.ClickException(
            "Define llm.models and/or enable llm.local with base_url and models",
        )
    key_pool = _llm_key_pool(llm_cfg, local_kw)

    agents_cfg = cfg.get("agents", [])
    if not agents_cfg:
        raise click.ClickException("Define at least one agent in config.yaml (agents)")

    chat_cfg = cfg.get("chat", {})

    participants = []
    for agent_cfg in agents_cfg:
        llm = LLMRouter(
            key_pool=key_pool,
            models=[agent_cfg["model"]],
            base_url=llm_cfg["base_url"],
            timeout=llm_cfg["timeout"],
            max_retries=llm_cfg["max_retries"],
            proxy=llm_proxy,
            **local_kw,
        )
        if agent_cfg["name"] == "parser":
            from swarm.parser.pipeline import WebParserPipeline
            parser_cfg = cfg.get("parser") or {}
            pipeline = WebParserPipeline(
                llm,
                fetch_timeout=float(parser_cfg.get("fetch_timeout_seconds", 15)),
                max_response_bytes=int(parser_cfg.get("max_response_bytes", 524_288)),
                max_text_chars=int(parser_cfg.get("llm_text_max_chars", 4000)),
                polite_delay=float(parser_cfg.get("polite_delay_seconds", 1)),
                proxy=llm_proxy,
            )
            participants.append(ParserParticipant(
                name=agent_cfg["name"],
                role=agent_cfg["role"],
                system_prompt=agent_cfg["system_prompt"],
                llm=llm,
                model=agent_cfg["model"],
                pipeline=pipeline,
            ))
        else:
            participants.append(AgentParticipant(
                name=agent_cfg["name"],
                role=agent_cfg["role"],
                system_prompt=agent_cfg["system_prompt"],
                llm=llm,
                model=agent_cfg["model"],
            ))

    selector_type = chat_cfg.get("selector", "round_robin")
    if selector_type == "llm":
        selector_llm = LLMRouter(
            key_pool=key_pool,
            models=(llm_cfg.get("models") or [])[:1],
            base_url=llm_cfg["base_url"],
            timeout=llm_cfg["timeout"],
            max_retries=llm_cfg["max_retries"],
            proxy=llm_proxy,
            **local_kw,
        )
        selector = LLMSelector(llm=selector_llm)
    else:
        selector = RoundRobinSelector()

    summary_llm: LLMRouter | None = None
    if chat_cfg.get("summary_every_n_agent_messages", 0) > 0 or chat_cfg.get(
        "final_summary", False
    ):
        sm = chat_cfg.get("summary_model")
        cm = llm_cfg.get("models") or []
        models = [sm] if sm else ([cm[0]] if cm else [])
        summary_llm = LLMRouter(
            key_pool=key_pool,
            models=models,
            base_url=llm_cfg["base_url"],
            timeout=llm_cfg["timeout"],
            max_retries=llm_cfg["max_retries"],
            proxy=llm_proxy,
            **local_kw,
        )

    config = ChatConfig(
        max_rounds=chat_cfg.get("max_rounds", 15),
        done_keyword=chat_cfg.get("done_keyword", "[DONE]"),
        max_llm_calls_per_session=chat_cfg.get("max_llm_calls_per_session", 30),
        selector_max_llm_calls=chat_cfg.get("selector_max_llm_calls", 15),
        max_context_chars=chat_cfg.get("max_context_chars", 12000),
        retry_failed_round=chat_cfg.get("retry_failed_round", False),
        summary_every_n_agent_messages=chat_cfg.get("summary_every_n_agent_messages", 0),
        summary_model=chat_cfg.get("summary_model"),
        final_summary=chat_cfg.get("final_summary", False),
        lan_hints=chat_cfg.get("lan_hints", False),
    )

    return participants, selector, config, summary_llm


async def run_chat_interactive(cfg: dict) -> None:
    participants, selector, config, summary_llm = build_chat_components(cfg)
    display = ChatDisplay()
    lan_lines = await _lan_peer_lines(cfg)
    room = ChatRoom(
        participants=participants,
        selector=selector,
        config=config,
        summary_llm=summary_llm,
        lan_peers_lines=lan_lines,
    )

    agent_names = [p.name for p in participants]
    click.echo(f"Агенты: {', '.join(agent_names)}")
    click.echo("Введи задачу (или 'exit' для выхода):\n")

    try:
        while True:
            try:
                goal = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if goal.lower() in ("exit", "quit", "q"):
                break
            if not goal:
                continue

            display.show_goal(goal)
            room.start(goal)

            while True:
                msg = await room.step()
                if msg is None:
                    break
                display.show_message(msg)

            await room.finalize()
            result = room._build_result()
            display.show_result(result)
            click.echo("")
    finally:
        if summary_llm is not None:
            await summary_llm.close()


async def run_task_oneshot(cfg: dict, description: str, agents_filter: str | None, output_json: bool) -> None:
    participants, selector, config, summary_llm = build_chat_components(cfg)

    if agents_filter:
        names = [n.strip() for n in agents_filter.split(",")]
        participants = [p for p in participants if p.name in names]
        if not participants:
            raise click.ClickException(f"No matching agents for: {agents_filter}")

    lan_lines = await _lan_peer_lines(cfg)
    room = ChatRoom(
        participants=participants,
        selector=selector,
        config=config,
        summary_llm=summary_llm,
        lan_peers_lines=lan_lines,
    )
    display = ChatDisplay()

    try:
        if not output_json:
            display.show_goal(description)

        room.start(description)
        while True:
            msg = await room.step()
            if msg is None:
                break
            if not output_json:
                display.show_message(msg)

        await room.finalize()
        result = room._build_result()

        if output_json:
            data = {
                "rounds_used": result.rounds_used,
                "finished_naturally": result.finished_naturally,
                "summary": result.summary,
                "end_reason": result.end_reason or None,
                "epilogue": result.epilogue or None,
                "messages": [
                    {"agent": m.agent_name, "role": m.role, "content": m.content, "round": m.round_num}
                    for m in result.messages
                ],
            }
            click.echo(json_module.dumps(data, ensure_ascii=False, indent=2))
        else:
            display.show_result(result)
    finally:
        if summary_llm is not None:
            await summary_llm.close()


async def start_node(port: int, bootstrap: str | None, config_path: str) -> None:
    cfg = load_config(config_path)
    runtime = AppRuntime(AppContainer.from_config(cfg, port=port, bootstrap=bootstrap))
    await runtime.run()


@click.group()
def cli():
    """
    Gemaxi Personal Memory OS / Immortal Swarm
    ------------------------------------------
    Personal digital soul that never forgets.
    Distributed AI Agent Network.
    """
    pass


@cli.command()
@click.option("--port", default=8000, help="Kademlia port")
@click.option("--bootstrap", default=None, help="Bootstrap node (host:port)")
@click.option("--config", default="config.yaml", help="Config file path")
def start(port: int, bootstrap: str | None, config: str):
    """Start a swarm node."""
    asyncio.run(start_node(port, bootstrap, config))


cli.add_command(start, "start-node")


@cli.command()
@click.option("--config", default="config.yaml", help="Config file path")
def chat(config: str):
    """Interactive multi-agent group chat."""
    cfg = load_config(config)
    asyncio.run(run_chat_interactive(cfg))


@cli.command()
@click.argument("description")
@click.option("--agents", default=None, help="Comma-separated agent names to use")
@click.option("--json", "output_json", is_flag=True, help="Output result as JSON")
@click.option("--config", default="config.yaml", help="Config file path")
def task(description: str, agents: str | None, output_json: bool, config: str):
    """Submit a task to the agent swarm."""
    cfg = load_config(config)
    asyncio.run(run_task_oneshot(cfg, description, agents, output_json))


@cli.command()
@click.option("--config", default="config.yaml")
def status(config: str):
    """Show network status."""
    cfg = load_config(config)

    async def _run():
        return await _call_local_rpc(cfg, "node_status", {})

    try:
        res = asyncio.run(_run())
        click.echo(f"Node ID: {res.get('node_id')}")
        tor = res.get("tor")
        if tor and tor.get("enabled"):
            click.echo(f"Tor:     ENABLED")
            click.echo(f"Onion:   {tor.get('onion_address') or 'N/A'}")
            click.echo(f"Proxy:   {tor.get('proxy_url')}")
            click.echo(f"Running: {'Yes' if tor.get('is_running') else 'No'}")
        else:
            click.echo("Tor:     DISABLED")
    except Exception:
        click.echo("Status: not connected (run 'start' first)")


@cli.command()
def nodes():
    """List known nodes."""
    click.echo("Nodes: not connected (run 'start' first)")


# ─── Swarm Distributed Tasks ──────────────────────────────────────────────

@cli.group("swarm")
def swarm_cli():
    """Distributed task swarm commands."""
    pass


async def _call_local_rpc(cfg: dict, method: str, params: dict):
    from swarm.network.rpc import RPCClient
    node_port = int((cfg.get("node") or {}).get("port", 8000))
    rpc_port = node_port + 2000
    client = RPCClient()
    try:
        return await client.call("127.0.0.1", rpc_port, method, params)
    except Exception as exc:
        raise click.ClickException(f"Could not connect to local node on port {rpc_port}: {exc}")


@swarm_cli.command("task-add")
@click.argument("description")
@click.option("--config", default="config.yaml")
def swarm_task_add(description: str, config: str):
    """Submit a task to the swarm via the local node."""
    cfg = load_config(config)

    async def _run():
        return await _call_local_rpc(cfg, "task_submit", {"description": description})

    res = asyncio.run(_run())
    if res.get("success"):
        click.echo(f"Task submitted: {res['task_id']}")
    else:
        click.echo(f"Error: {res.get('reason')}")


@swarm_cli.command("task-list")
@click.option("--config", default="config.yaml")
def swarm_task_list(config: str):
    """List known swarm tasks."""
    cfg = load_config(config)

    async def _run():
        return await _call_local_rpc(cfg, "task_list", {})

    res = asyncio.run(_run())
    tasks = res.get("tasks", [])
    if not tasks:
        click.echo("No tasks known to the swarm.")
        return

    click.echo(f"{'ID':<38} {'STATUS':<10} {'ASSIGNED TO':<15} {'DESCRIPTION'}")
    click.echo("-" * 80)
    for t in tasks:
        tid = t['id']
        status = t['status']
        assigned = t.get('assigned_to') or "-"
        desc = t['description'][:40]
        click.echo(f"{tid:<38} {status:<10} {assigned:<15} {desc}")


@swarm_cli.command("task-claim")
@click.argument("task_id")
@click.option("--config", default="config.yaml")
def swarm_task_claim(task_id: str, config: str):
    """Force local node to claim a specific task."""
    cfg = load_config(config)

    async def _run():
        return await _call_local_rpc(cfg, "task_claim_local", {"task_id": task_id})

    res = asyncio.run(_run())
    if res.get("success"):
        click.echo(f"Task {task_id} claimed and added to queue.")
    else:
        click.echo(f"Error: {res.get('reason')}")


@swarm_cli.command("reputation")
@click.option("--config", default="config.yaml")
def swarm_reputation(config: str):
    """List reputation scores for all known nodes."""
    cfg = load_config(config)

    async def _run():
        return await _call_local_rpc(cfg, "reputation_list", {})

    res = asyncio.run(_run())
    reps = res.get("reputation", [])
    if not reps:
        click.echo("No reputation data yet.")
        return

    click.echo(f"{'NODE ID':<38} {'SCORE':>6} {'SUCCESS':>8} {'TOTAL':>8} {'LAST ACTIVE'}")
    click.echo("-" * 85)
    for r in reps:
        nid = r['node_id']
        score = f"{r['score']:.2f}"
        success = r['tasks_success']
        total = r['tasks_total']
        import time
        dt = time.strftime("%Y-%m-%d %H:%M", time.localtime(r['last_activity']))
        click.echo(f"{nid:<38} {score:>6} {success:>8} {total:>8} {dt}")


# ─── Parse Command ────────────────────────────────────────────────────────

@cli.command()
@click.argument("input_text")
@click.option("--search", is_flag=True, help="Treat input as a search query (not a URL)")
@click.option("--limit", default=3, type=int, show_default=True,
              help="Max URLs to process (search mode)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option("--save", is_flag=True,
              help="Persist results to local memory repository")
@click.option("--config", default="config.yaml", help="Config file path")
def parse(input_text: str, search: bool, limit: int, output_json: bool, save: bool, config: str):
    """Parse web page(s) for structured product/offer data.

    INPUT_TEXT is a URL or (with --search) a free-text query.

    Examples:

      python node.py parse https://example.com/parts

      python node.py parse "autoglass lada granta price" --search --limit 5

      python node.py parse https://shop.example/catalog --json --save
    """
    from swarm.parser.pipeline import WebParserPipeline

    cfg = load_config(config)

    # -- Build LLM for extractor (same logic as chat) --
    from swarm.network.outbound_http import outbound_http_proxy_url
    try:
        llm_proxy = outbound_http_proxy_url(cfg)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    llm_cfg = cfg["llm"]
    local_kw = _llm_local_router_kwargs(llm_cfg)
    key_pool = _llm_key_pool(llm_cfg, local_kw)

    llm = LLMRouter(
        key_pool=key_pool,
        models=llm_cfg.get("models") or [],
        base_url=llm_cfg["base_url"],
        timeout=llm_cfg["timeout"],
        max_retries=llm_cfg["max_retries"],
        proxy=llm_proxy,
        **local_kw,
    )

    # -- Parser config (optional section) --
    parser_cfg = cfg.get("parser") or {}
    fetch_timeout = float(parser_cfg.get("fetch_timeout_seconds", 15))
    max_response_bytes = int(parser_cfg.get("max_response_bytes", 524_288))
    max_text_chars = int(parser_cfg.get("llm_text_max_chars", 4000))
    polite_delay = float(parser_cfg.get("polite_delay_seconds", 1))

    limit = max(1, min(limit, int(parser_cfg.get("max_urls_per_query", 10))))

    pipeline = WebParserPipeline(
        llm,
        fetch_timeout=fetch_timeout,
        max_response_bytes=max_response_bytes,
        max_text_chars=max_text_chars,
        polite_delay=polite_delay,
        proxy=llm_proxy,
    )

    async def _run():
        return await pipeline.run(input_text, search=search, limit=limit)

    results = asyncio.run(_run())

    # -- Optional persistence --
    if save:
        try:
            _save_parse_results(cfg, results, input_text)
        except Exception as exc:
            click.echo(f"Warning: could not save results: {exc}", err=True)

    # -- Output --
    if output_json:
        import json as _json
        click.echo(_json.dumps(
            [r.to_dict() for r in results],
            ensure_ascii=False,
            indent=2,
        ))
    else:
        _print_parse_results(results)


def _print_parse_results(results):
    """Human-readable ASCII table output."""
    total_items = 0
    for r in results:
        click.echo(f"\n--- {r.source_url} ---")
        if r.errors:
            for e in r.errors:
                click.echo(f"  [ERROR] {e}")
        if not r.items:
            click.echo("  (no items extracted)")
            continue
        # header
        click.echo(f"  {'NAME':<40} {'PRICE':>12} {'CURRENCY':>8} {'SHOP':<20} {'STOCK':>6}")
        click.echo(f"  {'-'*40} {'-'*12} {'-'*8} {'-'*20} {'-'*6}")
        for item in r.items:
            name = (item.name or "")[:40]
            price = (item.price or "-")[:12]
            currency = (item.currency or "")[:8]
            shop = (item.shop or "")[:20]
            stock = "yes" if item.in_stock is True else ("no" if item.in_stock is False else "?")
            click.echo(f"  {name:<40} {price:>12} {currency:>8} {shop:<20} {stock:>6}")
        total_items += len(r.items)
    click.echo(f"\nTotal: {len(results)} page(s), {total_items} item(s)")


def _save_parse_results(cfg, results, input_text: str):
    """Persist parse results to the local memory repository."""
    import re

    repo = _build_local_memory_repository(cfg)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", input_text)[:40].strip("-").lower()

    async def _do_save():
        for r in results:
            if not r.items:
                continue
            await repo.save(
                data={
                    "source_url": r.source_url,
                    "items": [i.to_dict() for i in r.items],
                    "fetched_at": r.fetched_at,
                    "errors": r.errors,
                },
                table="parse_results",
                tags=["parse", slug],
            )

    asyncio.run(_do_save())


@click.group()
def memory():
    """Memory operations."""
    pass


@cli.group()
def note():
    """Quick personal notes: add, list, search, ask."""
    pass


def _format_note_row(row, idx: int | None = None, *, show_ref: bool = False) -> str:
    data = row.data or {}
    attrs = row.attrs or {}
    title = data.get("title") or ""
    text = str(data.get("text") or "")
    tags = [t for t in (row.tags or []) if not str(t).startswith("table:")]
    prefix = f"[{idx}] " if idx is not None else ""
    title_part = f"{title}: " if title else ""
    tag_part = f"  #{' #'.join(tags)}" if tags else ""
    ref_part = f"\n    ref: {row.ref}" if show_ref else ""
    ts = attrs.get("_ts")
    ts_part = f"  ts={ts:.0f}" if isinstance(ts, (int, float)) else ""
    return f"{prefix}{title_part}{text}{tag_part}{ts_part}{ref_part}"


@note.command("add")
@click.argument("text", nargs=-1, required=True)
@click.option("--title", default=None, help="Optional note title")
@click.option("--tag", "tag_opts", multiple=True, help="Repeatable tag, e.g. --tag client --tag glass")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--no-vector", is_flag=True, help="Do not add this note to semantic vector search")
@click.option("--config", default="config.yaml", help="Config file path")
def note_add(text: tuple[str, ...], title: str | None, tag_opts: tuple[str, ...], tags: str, no_vector: bool, config: str):
    """Save a plain-text note locally and index it for search.

    Example:
      python node.py note add Клиент Иван заказал стекло --tag orders
    """
    body = " ".join(text).strip()
    if not body:
        raise click.ClickException("empty note")
    cfg = load_config(config)
    port = _build_local_memory_port(cfg)
    repo = MemoryRepository(port)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] + [t.strip() for t in tag_opts if t.strip()]
    data = {"text": body}
    if title:
        data["title"] = title

    async def _run():
        ref = await repo.save(
            data=data,
            table="notes",
            tags=tag_list,
            attrs={"kind": "note", "source": "cli.note"},
        )
        vector_ref = None
        if not no_vector:
            from swarm.memory.vector_store import HashingEmbedder, PersistentVectorIndex, VectorStore

            store = VectorStore(HashingEmbedder(dims=256))
            idx = PersistentVectorIndex(store, repo)
            record = store.add(
                id=ref,
                text=body,
                metadata={"ref": ref, "table": "notes", "title": title, "tags": tag_list},
            )
            vector_ref = await idx.save(record, attrs={"source_ref": ref})
        return ref, vector_ref

    ref, vector_ref = asyncio.run(_run())
    click.echo(f"saved: {ref}")
    if vector_ref:
        click.echo(f"vector: {vector_ref}")


@note.command("list")
@click.option("--limit", default=20, type=int, show_default=True)
@click.option("--tag", "tags", multiple=True, help="Filter by tag")
@click.option("--refs", is_flag=True, help="Show internal refs")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option("--config", default="config.yaml", help="Config file path")
def note_list(limit: int, tags: tuple[str, ...], refs: bool, output_json: bool, config: str):
    """List saved notes, newest first."""
    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)

    async def _run():
        return await repo.query(table="notes", tags=list(tags), order_by="attrs._ts:desc", limit=limit)

    rows = asyncio.run(_run())
    if output_json:
        payload = [{"ref": r.ref, "data": r.data, "tags": r.tags, "attrs": r.attrs} for r in rows]
        click.echo(json_module.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not rows:
        click.echo("Заметок пока нет. Добавь: python node.py note add ...")
        return
    for i, row in enumerate(rows, start=1):
        click.echo(_format_note_row(row, i, show_ref=refs))


@note.command("search")
@click.argument("query")
@click.option("--top", default=5, type=int, show_default=True)
@click.option("--refs", is_flag=True, help="Show internal refs")
@click.option("--config", default="config.yaml")
def note_search(query: str, top: int, refs: bool, config: str):
    """Search notes by text and semantic vector similarity."""
    cfg = load_config(config)
    port = _build_local_memory_port(cfg)
    repo = MemoryRepository(port)

    async def _run():
        text_rows = await repo.query(table="notes", text=query, order_by="attrs._ts:desc", limit=top)
        from swarm.memory.vector_store import HashingEmbedder, PersistentVectorIndex, VectorStore

        store = VectorStore(HashingEmbedder(dims=256))
        idx = PersistentVectorIndex(store, repo)
        await idx.load_all()
        semantic = store.search(query, top_k=top)
        return text_rows, semantic

    text_rows, semantic = asyncio.run(_run())
    click.echo("Текстовые совпадения:")
    if text_rows:
        for i, row in enumerate(text_rows, start=1):
            click.echo("  " + _format_note_row(row, i, show_ref=refs))
    else:
        click.echo("  нет")

    click.echo("\nСемантические совпадения:")
    if semantic:
        for i, match in enumerate(semantic, start=1):
            meta = match.record.metadata or {}
            ref_part = f" ref={meta.get('ref') or match.record.id}" if refs else ""
            title = meta.get("title")
            title_part = f"{title}: " if title else ""
            click.echo(f"  [{i}] {match.score:.3f}  {title_part}{match.record.text}{ref_part}")
    else:
        click.echo("  нет")


@note.command("ask")
@click.argument("query")
@click.option("--top", default=4, type=int, show_default=True)
@click.option("--config", default="config.yaml", help="Config file path")
def note_ask(query: str, top: int, config: str):
    """Build an offline RAG prompt from saved notes. No external LLM call."""
    from swarm.memory.rag import RagPromptBuilder, Retriever
    from swarm.memory.vector_store import HashingEmbedder, PersistentVectorIndex, VectorStore

    cfg = load_config(config)
    port = _build_local_memory_port(cfg)
    repo = MemoryRepository(port)
    store = VectorStore(embedder=HashingEmbedder())
    idx = PersistentVectorIndex(store, repo)

    async def _run():
        await idx.load_all()
        retriever = Retriever(store, top_k=top)
        builder = RagPromptBuilder(
            retriever,
            system="Ответь на вопрос только по найденным заметкам. Если данных нет, так и скажи.",
            include_metadata=True,
        )
        return builder.render_sync(query)

    click.echo(asyncio.run(_run()))


@memory.command()
@click.argument("query")
def search(query: str):
    """Search distributed memory by tags."""
    click.echo(f"Searching for: {query}")
    click.echo("(Connect to a running node to search)")


@memory.command("insert")
@click.option("--table", required=True, help="Logical table/collection name")
@click.option("--data", "data_json", required=True, help="JSON object payload")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--attrs", "attrs_json", default="{}", help="JSON object attrs")
@click.option(
    "--store",
    default=None,
    help="Storage scheme: file (default), pasters, pasteee, catbox, …; "
    "`auto` tries cloud_paste.auto_fallback_order (or built-in order), then file",
)
@click.option("--config", default="config.yaml", help="Config file path")
def memory_insert(
    table: str,
    data_json: str,
    tags: str,
    attrs_json: str,
    store: str | None,
    config: str,
):
    """Insert JSON record into local memory repository."""
    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)

    try:
        data = json_module.loads(data_json)
        attrs = json_module.loads(attrs_json)
    except Exception as exc:
        raise click.ClickException(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise click.ClickException("--data must be a JSON object")
    if not isinstance(attrs, dict):
        raise click.ClickException("--attrs must be a JSON object")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    if store == "auto":
        from swarm.memory.cloud_fallback import (
            cloud_auto_fallback_schemes,
            repository_save_with_store_fallback,
        )

        schemes = cloud_auto_fallback_schemes(cfg)
        ref, used = asyncio.run(
            repository_save_with_store_fallback(
                repo,
                data=data,
                table=table,
                tags=tag_list,
                attrs_base=attrs,
                schemes=schemes,
            )
        )
        click.echo(ref)
        click.echo(f"# store_used={used}", err=True)
        return

    if store:
        attrs = {**attrs, "store": store}

    ref = asyncio.run(repo.save(data=data, table=table, tags=tag_list, attrs=attrs))
    click.echo(ref)


@memory.command("query")
@click.option("--table", default=None, help="Filter by table")
@click.option("--tag", "tags", multiple=True, help="Repeatable tag filter")
@click.option("--text", default=None, help="Substring search in JSON payload")
@click.option("--where", default=None, help="Simple filter, e.g. attrs.vendor == 'x' and data.price >= 100")
@click.option("--order-by", default=None, help="Sort by table|data.<key>|attrs.<key> with :asc|:desc")
@click.option("--offset", default=0, type=int, show_default=True)
@click.option("--attrs", "attrs_json", default="{}", help="JSON object attrs filter")
@click.option("--limit", default=100, type=int, show_default=True)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option("--config", default="config.yaml", help="Config file path")
def memory_query(
    table: str | None,
    tags: tuple[str, ...],
    text: str | None,
    where: str | None,
    order_by: str | None,
    offset: int,
    attrs_json: str,
    limit: int,
    output_json: bool,
    config: str,
):
    """Query records from local memory repository."""
    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    try:
        attrs = json_module.loads(attrs_json)
    except Exception as exc:
        raise click.ClickException(f"invalid JSON in --attrs: {exc}") from exc
    if not isinstance(attrs, dict):
        raise click.ClickException("--attrs must be a JSON object")

    try:
        rows = asyncio.run(
            repo.query(
                table=table,
                tags=list(tags),
                text=text,
                attrs=attrs,
                where=where,
                order_by=order_by,
                offset=offset,
                limit=limit,
            )
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    payload = [
        {
            "ref": r.ref,
            "table": r.table,
            "data": r.data,
            "tags": r.tags,
            "attrs": r.attrs,
        }
        for r in rows
    ]
    if output_json:
        click.echo(json_module.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"rows={len(payload)}")
        for idx, row in enumerate(payload, start=1):
            data = row.get("data") or {}
            attrs = row.get("attrs") or {}
            title = data.get("title")
            title_part = f" title={title}" if title is not None else ""
            author = attrs.get("author")
            author_part = f" author={author}" if author is not None else ""
            click.echo(
                f"[{idx}] ref={row['ref']} table={row['table']}{title_part}{author_part}"
            )


@memory.command("metrics")
@click.option("--config", default="config.yaml", help="Config file path")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def memory_metrics(config: str, output_json: bool):
    """Show per-scheme memory facade metrics (puts, gets, latency, bytes)."""
    cfg = load_config(config)
    port = _build_local_memory_port(cfg)
    snap = port.metrics.snapshot()
    if output_json:
        click.echo(json_module.dumps(snap, ensure_ascii=False, indent=2))
        return
    if not snap:
        click.echo("(no traffic recorded yet on this local port)")
        return
    click.echo(f"{'scheme':<12} {'puts':>5} {'ok':>5} {'err':>5} {'avail':>7} {'p95.put':>10} {'p95.get':>10} {'bytes.out':>10}")
    for scheme, row in snap.items():
        click.echo(
            f"{scheme:<12} "
            f"{row['puts']:>5} {row['gets_ok']:>5} {row['gets_err']:>5} "
            f"{row['availability']*100:>6.1f}% "
            f"{(row['latency_put_p95_ms'] or 0):>9.1f}ms "
            f"{(row['latency_get_p95_ms'] or 0):>9.1f}ms "
            f"{row['bytes_out']:>10}"
        )


@memory.command("snapshot")
@click.option("--out", required=True, help="Path to write JSONL bundle")
@click.option("--kind", type=click.Choice(["artifact", "repository"]), default="repository")
@click.option("--config", default="config.yaml")
def memory_snapshot(out: str, kind: str, config: str):
    """Dump every reachable record into a JSONL snapshot bundle."""
    from swarm.memory.recovery import SwarmSnapshot, snapshot_repository

    cfg = load_config(config)
    port = _build_local_memory_port(cfg)

    async def _run():
        if kind == "repository":
            body = await snapshot_repository(MemoryRepository(port))
        else:
            body = await SwarmSnapshot(port).dump()
        from pathlib import Path as _P
        p = _P(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        click.echo(f"wrote {p} ({len(body)} bytes, kind={kind})")

    asyncio.run(_run())


@memory.command("restore")
@click.argument("path")
@click.option("--kind", type=click.Choice(["artifact", "repository"]), default="repository")
@click.option("--target-scheme", default=None, help="Force every artifact into this scheme")
@click.option("--config", default="config.yaml")
def memory_restore(path: str, kind: str, target_scheme: str | None, config: str):
    """Restore a JSONL snapshot into the local memory facade."""
    from swarm.memory.recovery import SwarmSnapshot, restore_repository

    cfg = load_config(config)
    port = _build_local_memory_port(cfg)

    async def _run():
        from pathlib import Path as _P
        body = _P(path).read_text(encoding="utf-8")
        if kind == "repository":
            refs = await restore_repository(MemoryRepository(port), body)
        else:
            refs = await SwarmSnapshot(port).restore(body, target_scheme=target_scheme)
        click.echo(f"restored {len(refs)} records")
        for r in refs[:20]:
            click.echo(f"  {r}")

    asyncio.run(_run())


@memory.command("graph")
@click.option("--kind", type=click.Choice(["wiki", "metrics", "repository"]), required=True)
@click.option("--format", "fmt", type=click.Choice(["dot", "mermaid", "ascii", "json"]), default="ascii")
@click.option("--config", default="config.yaml")
def memory_graph(kind: str, fmt: str, config: str):
    """Render a graph of the swarm's memory layer in DOT/Mermaid/ASCII/JSON."""
    from swarm.memory.adapters.obsidian import ObsidianVaultAdapter
    from swarm.memory.graph import (
        build_metrics_graph,
        build_repository_graph,
        build_wiki_graph,
        to_ascii,
        to_dot,
        to_json,
        to_mermaid,
    )

    cfg = load_config(config)
    port = _build_local_memory_port(cfg)

    async def _run():
        if kind == "wiki":
            obs_cfg = (cfg.get("memory_facade") or {}).get("obsidian") or {}
            vault = obs_cfg.get("vault_root") or (
                (cfg.get("memory_facade") or {}).get("scratch_root", ".swarm_scratch") + "/wiki"
            )
            graph = build_wiki_graph(ObsidianVaultAdapter(vault))
        elif kind == "metrics":
            graph = build_metrics_graph(port.metrics)
        else:
            rows = await MemoryRepository(port).query(limit=10_000_000)
            graph = build_repository_graph(rows)
        if fmt == "dot":
            click.echo(to_dot(graph))
        elif fmt == "mermaid":
            click.echo(to_mermaid(graph))
        elif fmt == "json":
            click.echo(to_json(graph))
        else:
            click.echo(to_ascii(graph))

    asyncio.run(_run())


@memory.command("wiki")
@click.option("--title", required=True)
@click.option("--body", required=True, help="Markdown body (use @file to read from file)")
@click.option("--tag", "tags", multiple=True)
@click.option("--config", default="config.yaml")
def memory_wiki_write(title: str, body: str, tags: tuple[str, ...], config: str):
    """Write a Markdown wiki note into the Obsidian vault."""
    from swarm.memory.adapters.obsidian import ObsidianVaultAdapter
    from swarm.memory.types import Artifact as _Artifact

    cfg = load_config(config)
    obs_cfg = (cfg.get("memory_facade") or {}).get("obsidian") or {}
    if not obs_cfg.get("enabled"):
        raise click.ClickException(
            "memory_facade.obsidian.enabled is false in config.yaml"
        )
    vault = obs_cfg.get("vault_root") or (
        (cfg.get("memory_facade") or {}).get("scratch_root", ".swarm_scratch") + "/wiki"
    )
    if body.startswith("@"):
        from pathlib import Path as _P
        body = _P(body[1:]).read_text(encoding="utf-8")
    adapter = ObsidianVaultAdapter(vault)
    artifact = _Artifact(content=body, tags=list(tags), attrs={"title": title})
    ref = asyncio.run(adapter.put(artifact))
    click.echo(ref)


@memory.command("vector-search")
@click.argument("query")
@click.option("--top", default=5, type=int, show_default=True)
@click.option("--config", default="config.yaml")
def memory_vector_search(query: str, top: int, config: str):
    """Search the persisted vector index by cosine similarity."""
    from swarm.memory.vector_store import (
        HashingEmbedder,
        PersistentVectorIndex,
        VectorStore,
    )

    cfg = load_config(config)
    port = _build_local_memory_port(cfg)

    async def _run():
        store = VectorStore(HashingEmbedder(dims=256))
        idx = PersistentVectorIndex(store, MemoryRepository(port))
        n = await idx.load_all()
        click.echo(f"loaded {n} vectors")
        results = store.search(query, top_k=top)
        for r in results:
            click.echo(f"  {r.score:.3f}  {r.record.id}  {r.record.text[:80]!r}")

    asyncio.run(_run())


@memory.command("vector-add")
@click.option("--id", "vid", required=True)
@click.option("--text", required=True)
@click.option("--config", default="config.yaml")
def memory_vector_add(vid: str, text: str, config: str):
    """Embed a text and persist its vector through the memory repository."""
    from swarm.memory.vector_store import (
        HashingEmbedder,
        PersistentVectorIndex,
        VectorStore,
    )

    cfg = load_config(config)
    port = _build_local_memory_port(cfg)

    async def _run():
        store = VectorStore(HashingEmbedder(dims=256))
        idx = PersistentVectorIndex(store, MemoryRepository(port))
        record = store.add(id=vid, text=text)
        ref = await idx.save(record)
        click.echo(ref)

    asyncio.run(_run())


def _build_cloud_memory_port(cfg: dict) -> CompositeMemoryPort:
    """Alias for the CLI composite (file + optional obsidian + cloud/http)."""
    return _build_local_memory_port(cfg)


@memory.command("dropbox-upload")
@click.argument("path")
@click.option("--name", default=None, help="Override stored filename")
@click.option("--chunk-size", default=256 * 1024, type=int, show_default=True)
@click.option("--replication", default=3, type=int, show_default=True,
              help="Independent backends per chunk")
@click.option("--schemes", default=None, help="Comma-separated schemes to fan out to")
@click.option("--config", default="config.yaml")
def memory_dropbox_upload(
    path: str, name: str | None, chunk_size: int, replication: int,
    schemes: str | None, config: str,
):
    """Upload any file to the swarm dropbox; print one short ref."""
    from swarm.memory.dropbox import FileDropbox

    cfg = load_config(config)
    port = _build_cloud_memory_port(cfg)
    scheme_list = (
        [s.strip() for s in schemes.split(",") if s.strip()] if schemes else None
    )

    async def _run():
        drop = FileDropbox(
            port,
            chunk_size=chunk_size,
            replication=replication,
            upload_schemes=scheme_list,
            manifest_schemes=scheme_list,
        )

        def _progress(phase: str, done: int, total: int) -> None:
            click.echo(f"  [{phase}] {done}/{total}", err=True)

        report = await drop.upload(path, name=name, progress=_progress)
        primary = FileDropbox.dropbox_ref(report.manifest_ref)
        click.echo(primary)
        click.echo(
            f"  size={report.manifest.size} sha256={report.manifest.sha256}",
            err=True,
        )
        click.echo(
            f"  chunks={len(report.manifest.chunks)} "
            f"min_replicas={report.min_chunk_replicas} "
            f"manifest_mirrors={report.manifest_replicas}",
            err=True,
        )
        for r in report.manifest_refs[1:]:
            click.echo(f"  mirror: {FileDropbox.dropbox_ref(r)}", err=True)

    asyncio.run(_run())


@memory.command("dropbox-download")
@click.argument("ref")
@click.option("--out", required=True, help="Destination path")
@click.option("--mirror", "mirrors", multiple=True, help="Additional manifest mirror refs")
@click.option("--config", default="config.yaml")
def memory_dropbox_download(ref: str, out: str, mirrors: tuple[str, ...], config: str):
    """Reassemble a file referenced by a dropbox ref into --out."""
    from swarm.memory.dropbox import FileDropbox

    cfg = load_config(config)
    port = _build_cloud_memory_port(cfg)

    async def _run():
        candidates = [ref, *mirrors] if mirrors else ref
        drop = FileDropbox(port)
        p = await drop.download(
            candidates,
            out,
            progress=lambda phase, d, t: click.echo(f"  [{phase}] {d}/{t}", err=True),
        )
        click.echo(str(p))

    asyncio.run(_run())


@memory.command("dropbox-info")
@click.argument("ref")
@click.option("--mirror", "mirrors", multiple=True, help="Additional manifest mirror refs")
@click.option("--json", "output_json", is_flag=True)
@click.option("--config", default="config.yaml")
def memory_dropbox_info(ref: str, mirrors: tuple[str, ...], output_json: bool, config: str):
    """Inspect a dropbox ref without downloading the file body."""
    from swarm.memory.dropbox import FileDropbox

    cfg = load_config(config)
    port = _build_cloud_memory_port(cfg)

    async def _run():
        candidates = [ref, *mirrors] if mirrors else ref
        info = await FileDropbox(port).info(candidates)
        if output_json:
            click.echo(json_module.dumps(info, ensure_ascii=False, indent=2))
            return
        click.echo(f"name={info['name']}  size={info['size']}  sha256={info['sha256']}")
        click.echo(
            f"chunks={len(info['chunks'])}  min_replicas={info['min_replicas']}"
        )
        for c in info["chunks"]:
            click.echo(f"  [{c['idx']:>3}] size={c['size']:>7}  replicas={c['replicas']}")

    asyncio.run(_run())


@memory.command("dropbox-health")
@click.argument("ref")
@click.option("--mirror", "mirrors", multiple=True)
@click.option("--config", default="config.yaml")
def memory_dropbox_health(ref: str, mirrors: tuple[str, ...], config: str):
    """Ping every chunk replica and report whether the file is still recoverable."""
    from swarm.memory.dropbox import FileDropbox

    cfg = load_config(config)
    port = _build_cloud_memory_port(cfg)

    async def _run():
        candidates = [ref, *mirrors] if mirrors else ref
        h = await FileDropbox(port).health(candidates)
        status = "RECOVERABLE" if h["recoverable"] else "BROKEN"
        click.echo(f"{status}  name={h['name']}  size={h['size']}")
        for c in h["chunks"]:
            click.echo(
                f"  [{c['idx']:>3}] alive={len(c['alive'])}/{c['replicas']}"
            )

    asyncio.run(_run())


@memory.command("tg-bot")
@click.option("--token", envvar="TELEGRAM_BOT_TOKEN", required=True,
              help="Bot token (or env TELEGRAM_BOT_TOKEN)")
@click.option("--allow", "allow", multiple=True, type=int,
              help="Allowed Telegram chat id (repeatable). Required unless --open-access.")
@click.option(
    "--open-access",
    is_flag=True,
    help="INSECURE: respond in every chat. Only for throwaway bot tokens / local tests.",
)
@click.option("--audit-dir", default=None, help="Optional AuditLog dir for /status")
@click.option("--config", default="config.yaml")
def memory_tg_bot(
    token: str,
    allow: tuple[int, ...],
    open_access: bool,
    audit_dir: str | None,
    config: str,
):
    """Run a long-polling Telegram bot bound to swarm memory.

    Exposes /status /list /insert /rag /qr -- great as a phone-side
    remote control for the swarm.  No webhooks, no public endpoints,
    no extra deps (uses httpx that is already in requirements).
    """
    from swarm.memory.audit import AuditLog
    from swarm.memory.repository import MemoryRepository
    from swarm.memory.telegram import BotConfig, TelegramBot

    cfg = load_config(config)
    port = _build_cloud_memory_port(cfg)
    repo = MemoryRepository(port)
    metrics = port.metrics if hasattr(port, "metrics") else None

    audit_stats_fn = None
    if audit_dir:
        audit = AuditLog(audit_dir, rotate_daily=True)
        audit_stats_fn = audit.stats

    if not allow and not open_access:
        raise click.UsageError(
            "Refusing to start: set at least one --allow CHAT_ID "
            "(see @userinfobot in Telegram) or pass --open-access for insecure mode."
        )

    bot = TelegramBot(
        BotConfig(
            token=token,
            allowed_chat_ids=set(allow),
            open_access=open_access,
        ),
        repository=repo,
        metrics=metrics,
        audit_stats_fn=audit_stats_fn,
    )

    async def _run():
        mode = "OPEN_ACCESS" if open_access else f"allowlist={sorted(allow)}"
        click.echo(f"telegram bot started ({mode})", err=True)
        await bot.run()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        bot.stop()


@memory.command("zk-upload")
@click.argument("path")
@click.option("--name", default=None)
@click.option("--chunk-size", default=256 * 1024, type=int, show_default=True)
@click.option("--replication", default=3, type=int, show_default=True)
@click.option("--schemes", default=None, help="Comma-separated schemes to fan out to")
@click.option("--config", default="config.yaml")
def memory_zk_upload(
    path: str, name: str | None, chunk_size: int, replication: int,
    schemes: str | None, config: str,
):
    """Upload PATH end-to-end encrypted; print one zk:...#key=... share link.

    The 256-bit AES-GCM key never leaves the local process -- it ends
    up only in the URL fragment, which never crosses the wire to any
    pastebin.  Treat the printed link like a password.
    """
    from swarm.memory.dropbox import FileDropbox
    from swarm.memory.zk_dropbox import ZkDropbox

    cfg = load_config(config)
    port = _build_cloud_memory_port(cfg)
    scheme_list = (
        [s.strip() for s in schemes.split(",") if s.strip()] if schemes else None
    )

    async def _run():
        drop = FileDropbox(
            port, chunk_size=chunk_size, replication=replication,
            upload_schemes=scheme_list,
            manifest_schemes=scheme_list,
        )
        zk = ZkDropbox(drop)
        share = await zk.upload(path, name=name)
        click.echo(share)

    asyncio.run(_run())


@memory.command("zk-download")
@click.argument("share_link")
@click.option("--out", required=True)
@click.option("--mirror", "mirrors", multiple=True)
@click.option("--config", default="config.yaml")
def memory_zk_download(share_link: str, out: str, mirrors: tuple[str, ...], config: str):
    """Decrypt and reassemble a file referenced by a zk: share link."""
    from swarm.memory.dropbox import FileDropbox
    from swarm.memory.zk_dropbox import ZkDropbox

    cfg = load_config(config)
    port = _build_cloud_memory_port(cfg)
    mirror_list = list(mirrors) if mirrors else None

    async def _run():
        drop = FileDropbox(port)
        zk = ZkDropbox(drop)
        path = await zk.download(share_link, out, mirrors=mirror_list)
        click.echo(f"wrote {path}")

    asyncio.run(_run())


@memory.command("consolidate")
@click.option("--table", default=None, help="Restrict to a single table")
@click.option("--ttl", default=None, type=float,
              help="Delete rows older than TTL seconds (None = disable)")
@click.option("--near-threshold", default=0.85, type=float, show_default=True,
              help="Jaccard cutoff for near-duplicate detection")
@click.option("--apply", "do_apply", is_flag=True,
              help="Actually delete; default is plan-only (dry-run)")
@click.option("--delete-near", is_flag=True,
              help="Also delete near-duplicates (off by default -- false positives)")
@click.option("--json", "as_json", is_flag=True)
@click.option("--config", default="config.yaml")
def memory_consolidate(
    table: str | None, ttl: float | None, near_threshold: float,
    do_apply: bool, delete_near: bool, as_json: bool, config: str,
):
    """Plan or execute memory cleanup (stale TTL, exact + near duplicates).

    By default this is a dry-run: pass --apply to actually delete.  The
    planner keeps the newest row of every duplicate cluster.
    """
    import json as _json

    from swarm.memory.consolidate import Consolidator
    from swarm.memory.repository import MemoryRepository

    cfg = load_config(config)
    port = _build_cloud_memory_port(cfg)
    repo = MemoryRepository(port)
    consolidator = Consolidator(repo)

    async def _run():
        report = await consolidator.plan(
            table=table, ttl_seconds=ttl, near_threshold=near_threshold,
        )
        if do_apply:
            await consolidator.apply(report, delete_near_duplicates=delete_near)
        if as_json:
            click.echo(_json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
            return
        d = report.to_dict()
        click.echo(
            f"total={d['total']} stale={d['summary']['stale_count']} "
            f"dup_groups={d['summary']['duplicate_groups']} "
            f"near_dup_groups={d['summary']['near_duplicate_groups']} "
            f"would_delete={d['summary']['would_delete']}"
        )
        if do_apply:
            click.echo(
                f"  applied: deleted={len(d['deletions'])} "
                f"failed={len(d['deletion_failed'])}"
            )

    asyncio.run(_run())


@memory.command("rag")
@click.argument("query")
@click.option("--top", default=4, type=int, show_default=True)
@click.option("--system", default=None, help="Override the system instruction")
@click.option("--with-meta", is_flag=True, help="Include metadata in citations")
@click.option("--config", default="config.yaml")
def memory_rag(query: str, top: int, system: str | None, with_meta: bool, config: str):
    """Render a RAG-ready prompt for QUERY using the persistent vector index.

    Retrieval-only: this command never calls an LLM.  Pipe the output
    into 'node.py chat' (or any other LLM front-end) if you want a real
    answer; this stays a pure swarm-memory tool.
    """
    from swarm.memory.rag import RagPromptBuilder, Retriever
    from swarm.memory.repository import MemoryRepository
    from swarm.memory.vector_store import HashingEmbedder, PersistentVectorIndex, VectorStore

    cfg = load_config(config)
    port = _build_cloud_memory_port(cfg)
    repo = MemoryRepository(port)
    store = VectorStore(embedder=HashingEmbedder())
    idx = PersistentVectorIndex(store, repo)

    async def _run():
        try:
            await idx.load_all()
        except Exception as exc:
            click.echo(f"# warning: load_all failed: {exc}", err=True)
        retriever = Retriever(store, top_k=top)
        builder = RagPromptBuilder(retriever, system=system, include_metadata=with_meta)
        prompt = builder.render_sync(query)
        click.echo(prompt)

    asyncio.run(_run())


@memory.command("dashboard")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=9100, type=int, show_default=True)
@click.option("--audit-dir", default=None,
              help="Optional AuditLog root; enables /api/audit + audit metrics")
@click.option("--demo", is_flag=True,
              help="Pre-fill some demo metrics so the UI has something to render")
def memory_dashboard(host: str, port: int, audit_dir: str | None, demo: bool):
    """Run the full control-plane web dashboard for swarm memory metrics.

    Multi-page SPA with real-time events, network topology, LLM usage,
    task management, and more.  Falls back to the legacy MemoryDashboard
    if the control-plane module is not importable.

    GET /           SPA dashboard (8 pages)
    GET /metrics    Prometheus exposition (text/plain)
    GET /api/v1/*   JSON API (11 endpoints)
    GET /healthz    JSON health probe
    """
    import time as _time

    from swarm.memory.audit import AuditLog
    from swarm.memory.port import MemoryMetrics

    metrics = MemoryMetrics()
    if demo:
        for scheme in ("catbox", "nullpointer", "telegraph", "pasters", "file"):
            metrics.record_put(scheme)
            metrics.record_put(scheme)
            metrics.record_get(scheme, ok=True)
            metrics.record_bytes_in(scheme, 1024)
            metrics.record_bytes_out(scheme, 512)
            metrics.record_latency(scheme, "put", 0.012)
            metrics.record_latency(scheme, "get", 0.008)
        metrics.record_get("nullpointer", ok=False)
        metrics.record_error("nullpointer", "HTTP 503 from upstream")
        metrics.record_put("file")
        metrics.record_put("file")
        metrics.record_put("file")

    audit_provider = None
    if audit_dir:
        audit = AuditLog(audit_dir, rotate_daily=True)
        audit_provider = audit.stats

    try:
        from swarm.api.control_plane import ControlPlaneServer
        dash = ControlPlaneServer(
            metrics,
            audit_provider=audit_provider,
            host=host,
            port=port,
        )
    except ImportError:
        from swarm.memory.dashboard import MemoryDashboard
        dash = MemoryDashboard(metrics, audit_provider=audit_provider, host=host, port=port)

    dash.start()
    click.echo(f"dashboard listening on {dash.url} (Ctrl-C to stop)")
    try:
        while True:
            _time.sleep(3600)
    except KeyboardInterrupt:
        dash.stop()


@memory.command("sql-sync")
@click.option("--out", required=True, help="Path for the SQLite mirror file")
@click.option("--config", default="config.yaml")
def memory_sql_sync(out: str, config: str):
    """Drop & rebuild a SQLite mirror of every row in the memory repository.

    The mirror is a read-side projection -- caller can run arbitrary SQL
    against /tmp/mirror.db with the standard sqlite3 CLI, but writes
    against it WILL NOT propagate back to swarm memory.
    """
    from swarm.memory.repository import MemoryRepository
    from swarm.memory.sql_gateway import SqlMirror

    cfg = load_config(config)
    port = _build_cloud_memory_port(cfg)
    repo = MemoryRepository(port)

    async def _run():
        mirror = SqlMirror.open(out)
        try:
            n = await mirror.sync(repo)
            click.echo(f"wrote {n} rows -> {out}")
            click.echo(f"  tables: {mirror.tables()}")
            click.echo(f"  tags:   {len(mirror.distinct_tags())} distinct")
        finally:
            mirror.close()

    asyncio.run(_run())


@memory.command("sql-query")
@click.argument("sql")
@click.option("--db", required=True, help="Path to a SQLite mirror created via sql-sync")
@click.option("--json", "as_json", is_flag=True)
def memory_sql_query(sql: str, db: str, as_json: bool):
    """Run an ad-hoc SELECT against the SQLite mirror.

    For richer analysis just open the file with `sqlite3 <db>` directly --
    this command is a thin wrapper for quick checks from the CLI.
    """
    import json as _json

    from swarm.memory.sql_gateway import SqlMirror

    mirror = SqlMirror.open(db)
    try:
        rows = mirror.fetchall(sql)
    finally:
        mirror.close()
    if as_json:
        click.echo(_json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return
    if not rows:
        click.echo("(no rows)")
        return
    headers = list(rows[0].keys())
    click.echo("\t".join(headers))
    for r in rows:
        click.echo("\t".join("" if r[h] is None else str(r[h]) for h in headers))


@memory.command("bootstrap-qr")
@click.option(
    "--data",
    default=None,
    help="String to encode directly (typically a short ref / URL)",
)
@click.option(
    "--from-file",
    default=None,
    help="Read the payload from a file (use small payloads only!)",
)
@click.option(
    "--ec-level",
    default="M",
    type=click.Choice(["L", "M", "Q", "H"]),
    show_default=True,
    help="Reed-Solomon error correction level",
)
@click.option("--info", is_flag=True, help="Print version/module/byte info too")
def memory_bootstrap_qr(data: str | None, from_file: str | None, ec_level: str, info: bool):
    """Print a sneakernet QR code for a short bootstrap ref / URL.

    Typical workflow:

    \b
    1. Publish the manifest to a pastebin (`memory bootstrap-manifest` +
       `BootstrapManifest.publish`).
    2. Pipe / pass the short ref into this command.
    3. Photograph the terminal QR with any phone.
    4. On the recovery side, paste the decoded URL back into
       `memory bootstrap-restore`.

    For payloads bigger than ~1 KB the QR becomes hard to scan -- publish
    the body and pass the ref instead of inlining the manifest itself.
    """
    from swarm.memory.qr import qr_capacity_check, qr_terminal

    if data is None and from_file is None:
        raise click.UsageError("provide --data or --from-file")
    if data and from_file:
        raise click.UsageError("--data and --from-file are mutually exclusive")
    if from_file:
        with open(from_file, encoding="utf-8") as fh:
            payload = fh.read().strip()
    else:
        payload = data or ""
    if not payload:
        raise click.UsageError("payload is empty")
    if info:
        meta = qr_capacity_check(payload, ec_level=ec_level)
        click.echo(
            f"# qr v{meta['version']} ({meta['modules']}x{meta['modules']} modules) "
            f"ec={meta['ec_level']} bytes={meta['bytes']}",
            err=True,
        )
    click.echo(qr_terminal(payload, ec_level=ec_level))


@memory.command("doctor")
@click.option(
    "--ref",
    "refs",
    multiple=True,
    help="Ref to probe (repeatable). Use '-' to read refs from stdin.",
)
@click.option("--from-file", "from_file", default=None, help="File with one ref per line")
@click.option("--timeout", default=8.0, type=float, show_default=True)
@click.option("--concurrency", default=8, type=int, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of text")
@click.option("--config", default="config.yaml")
def memory_doctor(
    refs: tuple[str, ...],
    from_file: str | None,
    timeout: float,
    concurrency: int,
    as_json: bool,
    config: str,
):
    """Bulk health-check refs through the configured cloud memory port.

    Reads refs from --ref (repeatable), --from-file, or stdin (pass '-'
    as a --ref).  Calls port.exists() on each in parallel and reports
    healthy / broken counts plus per-scheme split and latency stats.
    """
    import json as _json
    import sys as _sys

    from swarm.memory.doctor import format_report, probe_many, summarize

    collected: list[str] = []
    for r in refs:
        if r == "-":
            collected.extend(
                line.strip() for line in _sys.stdin if line.strip()
            )
        else:
            collected.append(r)
    if from_file:
        with open(from_file, encoding="utf-8") as fh:
            collected.extend(line.strip() for line in fh if line.strip())

    cfg = load_config(config)
    port = _build_cloud_memory_port(cfg)

    async def _run():
        results = await probe_many(
            port, collected, timeout=timeout, concurrency=concurrency
        )
        summary = summarize(results)
        if as_json:
            click.echo(_json.dumps(
                {
                    "results": [r.to_dict() for r in results],
                    "summary": summary,
                },
                ensure_ascii=False,
                indent=2,
            ))
        else:
            click.echo(format_report(results, summary))
        return summary["broken"]

    broken = asyncio.run(_run())
    if broken > 0:
        _sys = None  # keep flake happy
        import sys as _sys2
        _sys2.exit(1)


@memory.command("bootstrap-manifest")
@click.option("--out", required=True, help="Path to write manifest JSON")
@click.option("--seed", "seeds", multiple=True, help="host:port[:kind] (repeatable)")
@click.option("--entry", "entries", multiple=True, help="ref[:purpose] (repeatable)")
@click.option("--notes", default="", help="Free-form notes embedded in the manifest")
def memory_bootstrap_manifest(out: str, seeds: tuple[str, ...], entries: tuple[str, ...], notes: str):
    """Write a self-describing bootstrap manifest for cold-start recovery."""
    from swarm.memory.recovery import BootstrapManifest

    m = BootstrapManifest(notes=notes)
    for s in seeds:
        parts = s.split(":")
        if len(parts) < 2:
            raise click.ClickException(f"bad --seed {s!r}; expected host:port[:kind]")
        host, port = parts[0], int(parts[1])
        kind = parts[2] if len(parts) > 2 else "kademlia"
        m.add_seed(host, port, kind=kind)
    for e in entries:
        ref, _, purpose = e.partition(":purpose=")
        m.add_entry(ref, purpose=purpose or "")
    p = m.save(out)
    click.echo(f"wrote {p} ({len(m.entries)} entries, {len(m.seeds)} seeds)")



# ─── VFS Commands ──────────────────────────────────────────────────────────

@cli.group()
def vfs():
    """Virtual File System commands (Memory OS)."""
    pass

@vfs.command("import")
@click.argument("path", type=click.Path(exists=True))
@click.option("--dest", default="/", help="Destination virtual path")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--config", default="config.yaml")
def vfs_import(path, dest, tags, config):
    """Import a local file into the Gemaxi VFS."""
    import os

    from swarm.memory.vector_store import HashingEmbedder, VectorStore
    from swarm.memory.vfs import VirtualFileSystem

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    # Note: CLI uses a fresh vector store, but PersistentVectorIndex loads from repo
    store = VectorStore(HashingEmbedder())
    from swarm.memory.vector_store import PersistentVectorIndex
    idx = PersistentVectorIndex(store, repo)

    async def _run():
        await idx.load_all()
        vfs_inst = VirtualFileSystem(repo, store)

        name = os.path.basename(path)
        with open(path, "rb") as f:
            content = f.read()
            # Try to decode if it looks like text for the preview
            try:
                content_str = content.decode("utf-8")
            except Exception:
                content_str = "[Binary Data]"

        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        vfile = await vfs_inst.store_file(name, content_str, path=dest, tags=tag_list)

        # Save the vector index update
        # Find the record we just added to the store
        record = store.get(vfile.ref)
        if record:
            await idx.save(record)

        click.echo(f"Imported: {vfile.id}")
        click.echo(f"Ref: {vfile.ref}")

    asyncio.run(_run())

@vfs.command("ls")
@click.argument("path", default="/")
@click.option("--config", default="config.yaml")
def vfs_ls(path, config):
    """List files in the virtual directory."""
    from swarm.memory.vector_store import VectorStore
    from swarm.memory.vfs import VirtualFileSystem

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    vfs_inst = VirtualFileSystem(repo, VectorStore())

    async def _run():
        files = await vfs_inst.list_dir(path)
        if not files:
            click.echo("No files found.")
            return

        click.echo(f"{'NAME':<20} {'SIZE':>10} {'REF':<15}")
        for f in files:
            click.echo(f"{f.name:<20} {f.size:>10} {f.ref:<15}")

    asyncio.run(_run())

@vfs.command("search")
@click.argument("query")
@click.option("--config", default="config.yaml")
def vfs_search(query, config):
    """Semantic search for files in the VFS."""
    from swarm.memory.vector_store import HashingEmbedder, PersistentVectorIndex, VectorStore
    from swarm.memory.vfs import VirtualFileSystem

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    store = VectorStore(HashingEmbedder())
    idx = PersistentVectorIndex(store, repo)

    async def _run():
        await idx.load_all()
        vfs_inst = VirtualFileSystem(repo, store)
        results = await vfs_inst.semantic_search(query)

        if not results:
            click.echo("No matches found.")
            return

        for f in results:
            click.echo(f"- {f.name} (path={f.path}, ref={f.ref})")

    asyncio.run(_run())

@vfs.command("viz")
@click.option("--format", type=click.Choice(["ascii", "mermaid"]), default="ascii")
@click.option("--config", default="config.yaml")
def vfs_viz(format, config):
    """Visualize the semantic links in the VFS."""

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)

    async def _run():
        rows = await repo.query(table="vfs_files", limit=100)
        if format == "ascii":
            click.echo("VFS Knowledge Graph (Semantic Links):")
            for row in rows:
                edges = row.attrs.get("semantic_edges", [])
                click.echo(f"[*] {row.data.get('name')} ({row.ref})")
                if not edges:
                    click.echo("    (no semantic links)")
                for edge in edges:
                    target = edge.get("target_ref", "?")
                    rtype = edge.get("relation_type", "RELATED")
                    expl = edge.get("explanation", "")
                    click.echo(f"  ──[{rtype}]--> {target}")
                    if expl:
                        click.echo(f"      Why: {expl}")
        else:
            click.echo("flowchart TD")
            for row in rows:
                name = row.data.get('name').replace(" ", "_")
                click.echo(f"    {row.ref[:8]}[{name}]")
                edges = row.attrs.get("semantic_edges", [])
                for edge in edges:
                    target = edge.get("target_ref", "?")
                    rtype = edge.get("relation_type", "RELATED")
                    click.echo(f"    {row.ref[:8]} -- {rtype} --> {target[:8]}")

    asyncio.run(_run())

# ─── Immortal & Time Machine Commands ──────────────────────────────────────

@cli.group()
def immortal():
    """Immortal storage and archiving commands."""
    pass

def _build_immortal_manager(cfg):
    """Собрать ImmortalMemoryManager из конфига."""
    from swarm.memory.immortal import ArweaveProvider, EncryptedStorage, ImmortalMemoryManager, IPFSProvider
    from swarm.memory.vector_store import VectorStore

    repo = _build_local_memory_repository(cfg)
    immortal_cfg = cfg.get("immortal") or {}
    cold_cfg = immortal_cfg.get("cold_storage") or {}
    enc_cfg = immortal_cfg.get("encryption") or {}

    provider_name = cold_cfg.get("provider", "ipfs")
    if provider_name == "arweave":
        provider = ArweaveProvider(
            key_file=cold_cfg.get("arweave_key"),
            simulate=not cold_cfg.get("arweave_key"),
        )
    else:
        provider = IPFSProvider(
            host=cold_cfg.get("ipfs_host", "http://localhost:5001"),
            simulate=cold_cfg.get("simulate", False),
        )

    encrypted = False
    if enc_cfg.get("enabled"):
        provider = EncryptedStorage(provider, enc_cfg.get("master_key", "CHANGE_ME"))
        encrypted = True

    return ImmortalMemoryManager(
        VectorStore(), repo, provider,
        provider_name=provider_name,
        encrypted=encrypted,
    )


@immortal.command("archive")
@click.argument("ref")
@click.option("--importance", default=1.0, type=float)
@click.option("--config", default="config.yaml")
def immortal_archive(ref, importance, config):
    """Архивировать артефакт в cold storage (IPFS/Arweave)."""
    cfg = load_config(config)
    mgr = _build_immortal_manager(cfg)

    async def _run():
        record = await mgr.archive(ref, importance=importance)
        if record:
            click.echo("Архивировано!")
            click.echo(f"  Cold ID:  {record.cold_id}")
            click.echo(f"  Provider: {record.provider}")
            click.echo(f"  Размер:   {record.size_bytes} байт")
        else:
            click.echo("Не удалось архивировать (importance слишком низкая или нет cold storage).")

    asyncio.run(_run())


@immortal.command("log")
@click.option("--limit", default=20, type=int, show_default=True)
@click.option("--json", "output_json", is_flag=True)
@click.option("--config", default="config.yaml")
def immortal_log(limit, output_json, config):
    """Показать журнал архивации."""
    import json as _json
    cfg = load_config(config)
    mgr = _build_immortal_manager(cfg)

    async def _run():
        log = await mgr.archive_log(limit=limit)
        if output_json:
            click.echo(_json.dumps([r.to_dict() for r in log], ensure_ascii=False, indent=2))
            return
        if not log:
            click.echo("Журнал архивации пуст.")
            return
        import time
        for r in log:
            dt = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.archived_at)) if r.archived_at else "?"
            enc = " [E2E]" if r.encrypted else ""
            click.echo(f"  [{dt}] {r.provider}:{r.cold_id[:20]}... ← {r.ref} ({r.size_bytes}B){enc}")

    asyncio.run(_run())


@immortal.command("restore")
@click.argument("cold_id")
@click.option("--out", default=None, help="Файл для записи восстановленных данных")
@click.option("--config", default="config.yaml")
def immortal_restore(cold_id, out, config):
    """Восстановить данные из cold storage по ID."""
    cfg = load_config(config)
    mgr = _build_immortal_manager(cfg)

    async def _run():
        data = await mgr.restore(cold_id)
        if data is None:
            click.echo("Не удалось восстановить (cold storage недоступен).")
            return
        if not data:
            click.echo("Пустой ответ от cold storage.")
            return
        if out:
            with open(out, "wb") as f:
                f.write(data)
            click.echo(f"Восстановлено {len(data)} байт → {out}")
        else:
            try:
                click.echo(data.decode("utf-8"))
            except UnicodeDecodeError:
                click.echo(f"[бинарные данные, {len(data)} байт — используй --out FILE]")

    asyncio.run(_run())


@immortal.command("check")
@click.argument("cold_id")
@click.option("--config", default="config.yaml")
def immortal_check(cold_id, config):
    """Проверить, жив ли артефакт в cold storage."""
    cfg = load_config(config)
    mgr = _build_immortal_manager(cfg)

    async def _run():
        alive = await mgr.check(cold_id)
        if alive:
            click.echo(f"✓ {cold_id} — жив")
        else:
            click.echo(f"✗ {cold_id} — не найден / недоступен")

    asyncio.run(_run())


@immortal.command("stats")
@click.option("--config", default="config.yaml")
def immortal_stats(config):
    """Статистика cold storage."""
    cfg = load_config(config)
    mgr = _build_immortal_manager(cfg)
    s = mgr.stats()
    click.echo("Cold Storage:")
    click.echo(f"  Provider:   {s['provider']}")
    click.echo(f"  Доступен:   {'да' if s['cold_available'] else 'нет'}")
    click.echo(f"  Шифрование: {'да' if s['encrypted'] else 'нет'}")

@cli.command()
@click.argument("ref", default=None, required=False)
@click.option("--at", "timestamp", default=None, type=float, help="Unix timestamp")
@click.option("--config", default="config.yaml")
def timemachine(ref, timestamp, config):
    """View memory state in the past."""
    import time

    from swarm.memory.time_machine import TimeMachine

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    tm = TimeMachine(repo)

    async def _run():
        if ref:
            history = await tm.list_history(ref)
            click.echo(f"History for {ref}:")
            for h in history:
                dt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(h['ts']))
                click.echo(f"  {dt} -> {h['ref']} tags={h['tags']}")
        else:
            ts = timestamp or time.time()
            dt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
            click.echo(f"Memory snapshot at {dt}:")
            snap = await tm.get_snapshot_at(ts)
            for item in snap.items:
                click.echo(f"  {item.ref} [{item.table}] tags={item.tags}")

    asyncio.run(_run())


# ─── Glass (Autoglass Business) ───────────────────────────────────────────

@cli.group()
def glass():
    """Автостёкла: каталог, VIN-поиск, прайсы."""
    pass


@glass.command("add")
@click.option("--name", required=True, help="Название стекла")
@click.option("--type", "glass_type", default="", help="Тип: лобовое, боковое, заднее")
@click.option("--make", "makes", multiple=True, help="Марка авто (повторяемый)")
@click.option("--model", "models", multiple=True, help="Модель авто (повторяемый)")
@click.option("--year", "years", multiple=True, type=int, help="Год выпуска (повторяемый)")
@click.option("--oem", default="", help="OEM-код стекла")
@click.option("--price", default=0.0, type=float, help="Цена")
@click.option("--currency", default="RUB", help="Валюта")
@click.option("--supplier", default="", help="Поставщик")
@click.option("--no-stock", is_flag=True, help="Нет в наличии")
@click.option("--notes", default="", help="Заметки")
@click.option("--config", default="config.yaml")
def glass_add(name, glass_type, makes, models, years, oem, price, currency, supplier, no_stock, notes, config):
    """Добавить стекло в каталог.

    Пример:

      python node.py glass add --name "Лобовое Lada Granta" --type лобовое \
          --make Lada --model Granta --year 2020 --year 2021 --price 5500 \
          --supplier "БОР" --oem "21190-5206010"
    """
    from swarm.business.autoglass import GlassCatalog, GlassItem

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    catalog = GlassCatalog(repo)

    item = GlassItem(
        name=name,
        glass_type=glass_type,
        makes=list(makes),
        models=list(models),
        years=list(years),
        oem_code=oem,
        price=price,
        currency=currency,
        supplier=supplier,
        in_stock=not no_stock,
        notes=notes,
    )

    async def _run():
        ref = await catalog.add(item)
        click.echo(f"Добавлено: {name}")
        click.echo(f"  ref: {ref}")
        click.echo(f"  цена: {price} {currency}")
        if makes:
            click.echo(f"  марки: {', '.join(makes)}")

    asyncio.run(_run())


@glass.command("list")
@click.option("--make", default=None, help="Фильтр по марке")
@click.option("--type", "glass_type", default=None, help="Фильтр по типу")
@click.option("--in-stock", is_flag=True, default=False, help="Только в наличии")
@click.option("--limit", default=50, type=int, show_default=True)
@click.option("--json", "output_json", is_flag=True)
@click.option("--config", default="config.yaml")
def glass_list(make, glass_type, in_stock, limit, output_json, config):
    """Список стёкол в каталоге."""
    from swarm.business.autoglass import GlassCatalog

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    catalog = GlassCatalog(repo)

    async def _run():
        stock_filter = True if in_stock else None
        items = await catalog.search(
            make=make,
            glass_type=glass_type,
            in_stock=stock_filter,
            limit=limit,
        )
        if output_json:
            import json as _json
            click.echo(_json.dumps(
                [i.to_dict() for i in items],
                ensure_ascii=False,
                indent=2,
            ))
            return
        if not items:
            click.echo("Каталог пуст. Добавь: python node.py glass add --name ...")
            return
        click.echo(f"{'НАЗВАНИЕ':<35} {'ТИП':<12} {'ЦЕНА':>10} {'НАЛИЧИЕ':>8} {'ПОСТАВЩИК':<15}")
        click.echo(f"{'-'*35} {'-'*12} {'-'*10} {'-'*8} {'-'*15}")
        for item in items:
            name = (item.name or "")[:35]
            gtype = (item.glass_type or "")[:12]
            price = f"{item.price:.0f} {item.currency}" if item.price else "-"
            stock = "да" if item.in_stock else "нет"
            supplier = (item.supplier or "")[:15]
            click.echo(f"{name:<35} {gtype:<12} {price:>10} {stock:>8} {supplier:<15}")
        click.echo(f"\nИтого: {len(items)} позиций")

    asyncio.run(_run())


@glass.command("vin")
@click.argument("vin")
@click.option("--json", "output_json", is_flag=True)
@click.option("--config", default="config.yaml")
def glass_vin(vin, output_json, config):
    """Найти стёкла по VIN-коду автомобиля.

    Пример:

      python node.py glass vin XTA219070R0000001
    """
    from swarm.business.autoglass import GlassCatalog

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    catalog = GlassCatalog(repo)

    async def _run():
        info, items = await catalog.search_by_vin(vin)
        if output_json:
            import json as _json
            click.echo(_json.dumps({
                "vin": info.to_dict(),
                "items": [i.to_dict() for i in items],
            }, ensure_ascii=False, indent=2))
            return
        if not info.valid:
            click.echo(f"Ошибка: {info.error}")
            return
        click.echo(f"VIN: {info.vin}")
        click.echo(f"  Марка: {info.make or '?'}")
        click.echo(f"  Страна: {info.country or '?'}")
        click.echo(f"  Год: {info.year or '?'}")
        if not items:
            click.echo("\n  Совместимых стёкол в каталоге не найдено.")
            return
        click.echo(f"\nНайдено {len(items)} совместимых стёкол:")
        for item in items:
            stock = "✓" if item.in_stock else "✗"
            click.echo(f"  {stock} {item.name} — {item.price:.0f} {item.currency} ({item.supplier})")

    asyncio.run(_run())


@glass.command("vin-decode")
@click.argument("vin")
@click.option("--json", "output_json", is_flag=True)
def glass_vin_decode(vin, output_json):
    """Декодировать VIN (без поиска по каталогу).

    Пример:

      python node.py glass vin-decode WBA5B31070GP12345
    """
    import json as _json

    from swarm.business.autoglass import decode_vin

    info = decode_vin(vin)
    if output_json:
        click.echo(_json.dumps(info.to_dict(), ensure_ascii=False, indent=2))
    else:
        click.echo(f"VIN:    {info.vin}")
        click.echo(f"Валид:  {'да' if info.valid else 'нет'}")
        if info.error:
            click.echo(f"Ошибка: {info.error}")
        else:
            click.echo(f"Марка:  {info.make or '?'}")
            click.echo(f"Страна: {info.country or '?'}")
            click.echo(f"Год:    {info.year or '?'}")


@glass.command("parse-prices")
@click.argument("query")
@click.option("--limit", default=3, type=int, show_default=True)
@click.option("--save", is_flag=True, help="Сохранить снимок цен в историю")
@click.option("--json", "output_json", is_flag=True)
@click.option("--config", default="config.yaml")
def glass_parse_prices(query, limit, save, output_json, config):
    """Парсить цены конкурентов и (опционально) сохранить.

    Использует Web Parser Pipeline для поиска и извлечения цен.

    Пример:

      python node.py glass parse-prices "лобовое стекло lada granta цена" --save
    """
    from swarm.network.outbound_http import outbound_http_proxy_url
    from swarm.parser.pipeline import WebParserPipeline

    cfg = load_config(config)

    try:
        llm_proxy = outbound_http_proxy_url(cfg)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    llm_cfg = cfg["llm"]
    local_kw = _llm_local_router_kwargs(llm_cfg)
    key_pool = _llm_key_pool(llm_cfg, local_kw)

    llm = LLMRouter(
        key_pool=key_pool,
        models=llm_cfg.get("models") or [],
        base_url=llm_cfg["base_url"],
        timeout=llm_cfg["timeout"],
        max_retries=llm_cfg["max_retries"],
        proxy=llm_proxy,
        **local_kw,
    )

    parser_cfg = cfg.get("parser") or {}
    pipeline = WebParserPipeline(
        llm,
        fetch_timeout=float(parser_cfg.get("fetch_timeout_seconds", 15)),
        max_response_bytes=int(parser_cfg.get("max_response_bytes", 524_288)),
        max_text_chars=int(parser_cfg.get("llm_text_max_chars", 4000)),
        polite_delay=float(parser_cfg.get("polite_delay_seconds", 1)),
        proxy=llm_proxy,
    )

    async def _run():
        results = await pipeline.run(query, search=True, limit=limit)

        if save:
            from swarm.business.autoglass import GlassCatalog
            repo = _build_local_memory_repository(cfg)
            catalog = GlassCatalog(repo)
            for r in results:
                if r.items:
                    await catalog.add_price_snapshot(
                        source_url=r.source_url,
                        items=[i.to_dict() for i in r.items],
                        query=query,
                    )
            click.echo(f"Сохранено {sum(1 for r in results if r.items)} снимков цен.")

        if output_json:
            import json as _json
            click.echo(_json.dumps(
                [r.to_dict() for r in results],
                ensure_ascii=False,
                indent=2,
            ))
        else:
            total = 0
            for r in results:
                click.echo(f"\n--- {r.source_url} ---")
                if r.errors:
                    for e in r.errors:
                        click.echo(f"  [ОШИБКА] {e}")
                if not r.items:
                    click.echo("  (товаров не найдено)")
                    continue
                for item in r.items:
                    price_str = f"{item.price} {item.currency or ''}" if item.price else "—"
                    stock = "наличие" if item.in_stock else ("нет" if item.in_stock is False else "?")
                    click.echo(f"  • {item.name} — {price_str} [{stock}]")
                total += len(r.items)
            click.echo(f"\nИтого: {total} товаров с {len(results)} страниц")

    asyncio.run(_run())


@glass.command("price-history")
@click.option("--limit", default=10, type=int, show_default=True)
@click.option("--json", "output_json", is_flag=True)
@click.option("--config", default="config.yaml")
def glass_price_history(limit, output_json, config):
    """Показать историю снимков цен конкурентов."""
    import json as _json

    from swarm.business.autoglass import GlassCatalog

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    catalog = GlassCatalog(repo)

    async def _run():
        history = await catalog.price_history(limit=limit)
        if output_json:
            click.echo(_json.dumps(history, ensure_ascii=False, indent=2))
            return
        if not history:
            click.echo("История пуста. Запусти: python node.py glass parse-prices \"запрос\" --save")
            return
        for i, snap in enumerate(history, 1):
            ts = snap.get("timestamp", 0)
            import time
            dt = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "?"
            n = len(snap.get("items", []))
            click.echo(f"  {i}. [{dt}] {snap.get('source_url', '?')} — {n} товаров")

    asyncio.run(_run())


@glass.command("import-ocr")
@click.argument("path", type=click.Path(exists=True))
@click.option("--config", default="config.yaml")
def glass_import_ocr(path, config):
    """Import glass items from an image of a receipt or invoice."""
    from swarm.business.autoglass import AutoglassOCRProcessor, GlassCatalog
    from swarm.media.processor import MediaStore
    from swarm.network.outbound_http import outbound_http_proxy_url

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    catalog = GlassCatalog(repo)
    media_store = MediaStore(repo)
    
    try:
        llm_proxy = outbound_http_proxy_url(cfg)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    llm_cfg = cfg["llm"]
    local_kw = _llm_local_router_kwargs(llm_cfg)
    key_pool = _llm_key_pool(llm_cfg, local_kw)

    llm = LLMRouter(
        key_pool=key_pool,
        models=llm_cfg.get("models") or [],
        base_url=llm_cfg["base_url"],
        timeout=llm_cfg["timeout"],
        max_retries=llm_cfg["max_retries"],
        proxy=llm_proxy,
        **local_kw,
    )

    processor = AutoglassOCRProcessor(catalog, media_store, llm)

    async def _run():
        click.echo(f"Обработка файла: {path}...")
        items = await processor.process_file(path)
        if not items:
            click.echo("Товары не найдены или OCR не сработал.")
            return
        
        click.echo(f"Успешно импортировано товаров: {len(items)}")
        for item in items:
            click.echo(f"  • {item.name} — {item.price} {item.currency}")

    asyncio.run(_run())


# ─── Sync (CRDT Multi-device) ────────────────────────────────────────────

@cli.group()
def sync():
    """CRDT-синхронизация памяти между устройствами."""
    pass


@sync.command("status")
@click.option("--config", default="config.yaml")
def sync_status(config):
    """Показать статус CRDT-индекса памяти.

    Загружает все записи из MemoryRepository и строит локальный CRDT-индекс.
    """
    from swarm.memory.sync import SyncEngine

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    engine = SyncEngine(node_id="local-cli")

    async def _run():
        # Загрузить все записи из репо в CRDT
        rows = await repo.query(limit=100_000)
        for row in rows:
            engine.track_put(row.ref, {
                "table": row.table,
                "tags": row.tags[:3],
            })
        s = engine.stats()
        click.echo("CRDT-индекс памяти:")
        click.echo(f"  Активных записей: {s['active_refs']}")
        click.echo(f"  Всего ref'ов:     {s['total_refs']}")
        click.echo(f"  Удалённых:        {s['deleted_refs']}")
        click.echo(f"  Версия:           {s['version']}")

    asyncio.run(_run())


@sync.command("export")
@click.option("--out", required=True, help="Путь для JSON-файла CRDT-состояния")
@click.option("--config", default="config.yaml")
def sync_export(out, config):
    """Экспортировать CRDT-состояние в файл для ручного переноса."""
    import json as _json

    from swarm.memory.sync import SyncEngine

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    engine = SyncEngine(node_id="local-cli")

    async def _run():
        rows = await repo.query(limit=100_000)
        for row in rows:
            engine.track_put(row.ref, {
                "table": row.table,
                "tags": row.tags[:5],
            })
        data = engine.crdt.serialize()
        with open(out, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        click.echo(f"Экспортировано {engine.crdt.active_count} записей → {out}")

    asyncio.run(_run())


@sync.command("import")
@click.argument("path")
@click.option("--config", default="config.yaml")
def sync_import(path, config):
    """Импортировать CRDT-состояние из файла и показать delta."""
    import json as _json

    from swarm.memory.crdt import MemoryIndexCRDT
    from swarm.memory.sync import SyncEngine

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    engine = SyncEngine(node_id="local-cli")

    async def _run():
        # Загрузить текущие записи
        rows = await repo.query(limit=100_000)
        for row in rows:
            engine.track_put(row.ref, {"table": row.table})

        # Загрузить внешний CRDT
        with open(path, encoding="utf-8") as f:
            remote_data = _json.load(f)
        remote = MemoryIndexCRDT.deserialize(remote_data)

        before = engine.crdt.active_count
        changes = engine.crdt.merge(remote)
        after = engine.crdt.active_count

        click.echo(f"Импорт из {path}:")
        click.echo(f"  Изменений:     {changes}")
        click.echo(f"  Записей до:    {before}")
        click.echo(f"  Записей после: {after}")
        click.echo(f"  Новых ref'ов:  {after - before}")

        # Показать, какие ref'ы нужно скачать
        local_refs = {row.ref for row in rows}
        missing = engine.missing_refs(local_refs)
        if missing:
            click.echo(f"\n  Отсутствуют локально ({len(missing)}):")
            for ref in missing[:20]:
                click.echo(f"    • {ref}")
            if len(missing) > 20:
                click.echo(f"    ... и ещё {len(missing) - 20}")

    asyncio.run(_run())




# ─── Media (Multi-modal) ─────────────────────────────────────────────────

@cli.group()
def media():
    """Мультимодальные медиа: изображения, аудио, документы."""
    pass


@media.command("import")
@click.argument("path", type=click.Path(exists=True))
@click.option("--tag", "tags", multiple=True, help="Теги (повторяемый)")
@click.option("--ocr", is_flag=True, help="Запустить OCR (Tesseract)")
@click.option("--no-content", is_flag=True, help="Не сохранять содержимое (только метаданные)")
@click.option("--config", default="config.yaml")
def media_import(path, tags, ocr, no_content, config):
    """Импортировать медиафайл в память.

    Пример:

      python node.py media import photo.jpg --tag клиент --tag заказ
      python node.py media import invoice.png --ocr
    """
    from swarm.media.processor import MediaStore

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    ms = MediaStore(repo)

    async def _run():
        # Дедупликация
        from swarm.media.processor import compute_file_meta
        meta = compute_file_meta(path)
        existing = await ms.find_by_hash(meta.sha256)
        if existing:
            click.echo(f"Дубликат! Файл уже импортирован: {existing.filename}")
            return

        ref, meta = await ms.import_file(
            path,
            tags=list(tags),
            ocr=ocr,
            store_content=not no_content,
        )
        click.echo(f"Импортировано: {meta.filename}")
        click.echo(f"  ref:  {ref}")
        click.echo(f"  тип:  {meta.media_type}")
        click.echo(f"  mime: {meta.mime}")
        click.echo(f"  размер: {meta.size_bytes} байт")
        if meta.width:
            click.echo(f"  размеры: {meta.width}x{meta.height}")
        if meta.duration_seconds:
            click.echo(f"  длительность: {meta.duration_seconds:.1f} сек")
        if meta.ocr_text:
            click.echo(f"  OCR: {meta.ocr_text[:200]}")

    asyncio.run(_run())


@media.command("list")
@click.option("--type", "media_type", default=None,
              type=click.Choice(["image", "audio", "document"]),
              help="Фильтр по типу")
@click.option("--limit", default=50, type=int, show_default=True)
@click.option("--json", "output_json", is_flag=True)
@click.option("--config", default="config.yaml")
def media_list(media_type, limit, output_json, config):
    """Список медиафайлов."""
    import json as _json

    from swarm.media.processor import MediaStore

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    ms = MediaStore(repo)

    async def _run():
        items = await ms.list_media(media_type=media_type, limit=limit)
        if output_json:
            click.echo(_json.dumps([m.to_dict() for m in items], ensure_ascii=False, indent=2))
            return
        if not items:
            click.echo("Медиафайлов нет. Импортируй: python node.py media import FILE")
            return
        click.echo(f"{'ФАЙЛ':<30} {'ТИП':<10} {'РАЗМЕР':>10} {'ИНФО':<20}")
        click.echo(f"{'-'*30} {'-'*10} {'-'*10} {'-'*20}")
        for m in items:
            name = (m.filename or "?")[:30]
            size = f"{m.size_bytes:,}"
            info = ""
            if m.width:
                info = f"{m.width}x{m.height}"
            elif m.duration_seconds:
                info = f"{m.duration_seconds:.1f}s"
            elif m.ocr_text:
                info = f"OCR:{len(m.ocr_text)}ch"
            click.echo(f"{name:<30} {m.media_type:<10} {size:>10} {info:<20}")
        click.echo(f"\nИтого: {len(items)}")

    asyncio.run(_run())


@media.command("stats")
@click.option("--config", default="config.yaml")
def media_stats(config):
    """Статистика медиафайлов по типам."""
    from swarm.media.processor import MediaStore

    cfg = load_config(config)
    repo = _build_local_memory_repository(cfg)
    ms = MediaStore(repo)

    async def _run():
        counts = await ms.count()
        total = sum(counts.values())
        click.echo("Медиа-статистика:")
        for mtype, n in sorted(counts.items()):
            click.echo(f"  {mtype:<12} {n}")
        click.echo(f"  {'ИТОГО':<12} {total}")

    asyncio.run(_run())


from swarm.cli_additions import register_all
register_all(cli)

if __name__ == "__main__":
    cli()
