"""
swarm/api/spawn_endpoints.py
─────────────────────────────
Размножение узлов роя из админки + миграция payload + self-reflection.

Endpoints:
  GET  /api/v1/swarm/nodes              ─ список docker-нод (имя, порт, status)
  POST /api/v1/swarm/spawn              ─ {name, port, bootstrap}  → новый узел
  POST /api/v1/swarm/kill               ─ {name}                    → docker rm -f
  POST /api/v1/files/migrate_payload    ─ восстановить payload.bin для старых
  GET  /api/v1/agent/reflect            ─ агентская саморефлексия по истории
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("swarm.api.spawn_endpoints")

NODE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ───────────────────────────── swarm nodes ──────────────────────────────────

def handle_swarm_nodes(container) -> dict:
    """Список Docker-контейнеров octopus*."""
    try:
        r = subprocess.run(
            ["docker", "ps", "-a", "--format",
             "{{.Names}}|{{.Image}}|{{.Status}}|{{.Command}}|{{.RunningFor}}"],
            capture_output=True, text=True, timeout=8,
        )
        nodes = []
        for line in r.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 4)
            if len(parts) < 4:
                continue
            name = parts[0]
            if not name.startswith("octopus"):
                continue
            # порт из cmd: "... 8200 ..."
            cmd = parts[3].strip('"')
            m = re.search(r"\s(\d{4,5})(?:\s|$)", cmd)
            port = int(m.group(1)) if m else None
            running = "Up" in parts[2]
            nodes.append({
                "name":     name,
                "image":    parts[1],
                "status":   parts[2],
                "running":  running,
                "port":     port,
                "uptime":   parts[4] if len(parts) >= 5 else "",
                "is_self":  name == "octopus",
            })
        nodes.sort(key=lambda n: (not n["running"], n["port"] or 99999, n["name"]))
        return {"ok": True, "nodes": nodes, "count": len(nodes)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "nodes": []}


def handle_swarm_spawn(container, body: dict) -> dict:
    """
    Запустить новый узел через docker run.
    body: {name: str (опц.), port: int (опц.), bootstrap: str (опц.)}
    """
    name = (body.get("name") or "").strip()
    port = int(body.get("port") or 0)
    bootstrap = (body.get("bootstrap") or "127.0.0.1:8000").strip()

    auto_port = (not port or port < 1024 or port > 65535)
    if auto_port:
        # Получим список всех имён контейнеров один раз
        try:
            existing = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=5
            ).stdout.split()
        except Exception:
            existing = []
        for cand_port in range(8300, 8400):
            cand = f"octopus-child-{cand_port}"
            if cand in existing:
                continue
            if _port_taken(cand_port):  # UDP/TCP занят
                continue
            port = cand_port
            if not name:
                name = cand
            break
        else:
            return {"ok": False, "error": "no free port+name in 8300-8400"}
    if not name:
        name = f"octopus-child-{port}"

    if not NODE_NAME_RE.match(name):
        return {"ok": False, "error": "invalid name"}

    if name == "octopus":
        return {"ok": False, "error": "name 'octopus' reserved"}

    # Проверим — нет ли уже такого
    exist = subprocess.run(
        ["docker", "ps", "-a", "-q", "-f", f"name=^{name}$"],
        capture_output=True, text=True, timeout=5,
    )
    if exist.stdout.strip():
        return {"ok": False, "error": f"container {name} already exists"}

    # Готовим scratch dir
    node_dir = Path(f"/root/swarm_nodes/{name}")
    scratch = node_dir / ".swarm_scratch"
    keys_dir = node_dir / ".swarm_keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)

    # Генерируем конфиг наследник config-child
    src_cfg = Path("/etc/octopus/config-child.yaml")
    if not src_cfg.exists():
        src_cfg = Path("/etc/octopus/config.yaml")
    cfg_text = src_cfg.read_text()
    # подменяем порты в YAML
    cfg_text = re.sub(r"(\bport:\s*)\d{4,5}", lambda m, p=port: f"{m.group(1)}{p}",
                      cfg_text, count=1)  # node.port — берём первый
    # api.port
    cfg_text = re.sub(r"(api:[\s\S]*?port:\s*)\d{4,5}", lambda m, p=port+100: f"{m.group(1)}{p}",
                      cfg_text, count=1)
    # bootstrap
    cfg_text = re.sub(r"(bootstrap:\s*\n\s*-\s*)\S+", f"\\g<1>{bootstrap}",
                      cfg_text, count=1)
    # Substitute dashboard secret placeholder with the real OCTOPUS_DASH_PASS so
    # spawned children authenticate with the same credentials as systemd-managed
    # nodes. Without this, children keep the literal "__OCTOPUS_DASH_PASS__" and
    # control-port sync / status tooling cannot reach them. (fix 2026-05-30)
    _dash_pwd = os.environ.get("OCTOPUS_DASH_PASS", "")
    if _dash_pwd:
        cfg_text = cfg_text.replace("__OCTOPUS_DASH_PASS__", _dash_pwd)
    target_cfg = Path(f"/etc/octopus/config-{name}.yaml")
    target_cfg.write_text(cfg_text)

    # Pinned-pubkey родителя для авто-верификации handshake
    parent_pub = ""
    parent_id  = ""
    try:
        pub_path = Path("/etc/octopus/parent_node.pub")
        if not pub_path.exists():
            pub_path = Path("/app/.swarm_keys/node.pub")
        if pub_path.exists():
            parent_pub = pub_path.read_text().strip()
            try:
                import hashlib
                parent_id = hashlib.sha256(bytes.fromhex(parent_pub)).hexdigest()[:16]
            except Exception:
                parent_id = ""
    except Exception as exc:
        _LOG.warning("cannot read parent pubkey: %s", exc)

    
    # Systemd integration (Simplification, 2026-05-30)
    # We no longer use raw docker run. We use octopus-child@N.service.
    svc = f"octopus-child@{port}.service"
    try:
        subprocess.run(["systemctl", "enable", "--now", svc], check=True, capture_output=True, text=True, timeout=15)
        
        # Wait for container to appear
        for _ in range(10):
            time.sleep(1)
            exist = subprocess.run(["docker", "ps", "-q", "-f", f"name=^octopus-child-{port}$"], capture_output=True, text=True)
            if exist.stdout.strip():
                break
        else:
            return {"ok": False, "error": f"systemctl enabled service but container octopus-child-{port} did not start within 10s"}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": f"systemctl failed: {e.stderr}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}



def handle_swarm_spawn(container, body: dict) -> dict:
    """
    Запустить новый узел через docker run.
    body: {name: str (опц.), port: int (опц.), bootstrap: str (опц.)}
    """
    name = (body.get("name") or "").strip()
    port = int(body.get("port") or 0)
    bootstrap = (body.get("bootstrap") or "127.0.0.1:8000").strip()

    auto_port = (not port or port < 1024 or port > 65535)
    if auto_port:
        # Получим список всех имён контейнеров один раз
        try:
            existing = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=5
            ).stdout.split()
        except Exception:
            existing = []
        for cand_port in range(8300, 8400):
            cand = f"octopus-child-{cand_port}"
            if cand in existing:
                continue
            if _port_taken(cand_port):  # UDP/TCP занят
                continue
            port = cand_port
            if not name:
                name = cand
            break
        else:
            return {"ok": False, "error": "no free port+name in 8300-8400"}
    if not name:
        name = f"octopus-child-{port}"

    if not NODE_NAME_RE.match(name):
        return {"ok": False, "error": "invalid name"}

    if name == "octopus":
        return {"ok": False, "error": "name 'octopus' reserved"}

    # Проверим — нет ли уже такого
    exist = subprocess.run(
        ["docker", "ps", "-a", "-q", "-f", f"name=^{name}$"],
        capture_output=True, text=True, timeout=5,
    )
    if exist.stdout.strip():
        return {"ok": False, "error": f"container {name} already exists"}

    # Готовим scratch dir
    node_dir = Path(f"/root/swarm_nodes/{name}")
    scratch = node_dir / ".swarm_scratch"
    keys_dir = node_dir / ".swarm_keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)

    # Генерируем конфиг наследник config-child
    src_cfg = Path("/etc/octopus/config-child.yaml")
    if not src_cfg.exists():
        src_cfg = Path("/etc/octopus/config.yaml")
    cfg_text = src_cfg.read_text()
    # подменяем порты в YAML
    cfg_text = re.sub(r"(\bport:\s*)\d{4,5}", lambda m, p=port: f"{m.group(1)}{p}",
                      cfg_text, count=1)  # node.port — берём первый
    # api.port
    cfg_text = re.sub(r"(api:[\s\S]*?port:\s*)\d{4,5}", lambda m, p=port+100: f"{m.group(1)}{p}",
                      cfg_text, count=1)
    # bootstrap
    cfg_text = re.sub(r"(bootstrap:\s*\n\s*-\s*)\S+", f"\\g<1>{bootstrap}",
                      cfg_text, count=1)
    # Substitute dashboard secret placeholder with the real OCTOPUS_DASH_PASS so
    # spawned children authenticate with the same credentials as systemd-managed
    # nodes. Without this, children keep the literal "__OCTOPUS_DASH_PASS__" and
    # control-port sync / status tooling cannot reach them. (fix 2026-05-30)
    _dash_pwd = os.environ.get("OCTOPUS_DASH_PASS", "")
    if _dash_pwd:
        cfg_text = cfg_text.replace("__OCTOPUS_DASH_PASS__", _dash_pwd)
    target_cfg = Path(f"/etc/octopus/config-{name}.yaml")
    target_cfg.write_text(cfg_text)

    # Pinned-pubkey родителя для авто-верификации handshake
    parent_pub = ""
    parent_id  = ""
    try:
        pub_path = Path("/etc/octopus/parent_node.pub")
        if not pub_path.exists():
            pub_path = Path("/app/.swarm_keys/node.pub")
        if pub_path.exists():
            parent_pub = pub_path.read_text().strip()
            try:
                import hashlib
                parent_id = hashlib.sha256(bytes.fromhex(parent_pub)).hexdigest()[:16]
            except Exception:
                parent_id = ""
    except Exception as exc:
        _LOG.warning("cannot read parent pubkey: %s", exc)

    
    # docker run -d
    cmd = [
        # --restart unless-stopped: spawned children survive crashes/reboots
        # (parity with systemd octopus-child@.service Restart=always). 2026-05-30
        "docker", "run", "-d", "--restart", "unless-stopped",
        "--name", name,
        "--network", "host",
        "--env-file", "/etc/octopus/octopus.env",
        "--env-file", "/etc/octopus/secrets.env",
        "-v", "/opt/octopus-deploy:/deploy:ro",
        "-v", f"{scratch}:/app/.swarm_scratch",
        "-v", f"{keys_dir}:/app/.swarm_keys",
        "-v", "/var/lib/octopus/memory_pool:/app/memory_pool",
        "-v", "/var/lib/octopus/wiki:/app/wiki",
        "-v", f"{target_cfg}:/etc/octopus/config.yaml:ro",
    ]
    
    code_patches = [
        ("/opt/octopus/swarm/runtime.py", "/app/swarm/runtime.py"),
        ("/opt/octopus/swarm/runtime.py", "/usr/local/lib/python3.11/site-packages/swarm/runtime.py"),
        ("/opt/octopus/swarm/memory/repository.py", "/app/swarm/memory/repository.py"),
        ("/opt/octopus/swarm/memory/repository.py", "/usr/local/lib/python3.11/site-packages/swarm/memory/repository.py"),
        ("/opt/octopus/swarm/memory/vector_store.py", "/app/swarm/memory/vector_store.py"),
        ("/opt/octopus/swarm/memory/vector_store.py", "/usr/local/lib/python3.11/site-packages/swarm/memory/vector_store.py"),
        ("/opt/octopus/swarm/memory/graph_rag.py", "/app/swarm/memory/graph_rag.py"),
        ("/opt/octopus/swarm/memory/graph_rag.py", "/usr/local/lib/python3.11/site-packages/swarm/memory/graph_rag.py"),
        ("/opt/octopus/swarm/memory/adapters/postgres_adapter.py", "/app/swarm/memory/adapters/postgres_adapter.py"),
        ("/opt/octopus/swarm/memory/adapters/postgres_adapter.py", "/usr/local/lib/python3.11/site-packages/swarm/memory/adapters/postgres_adapter.py"),
        ("/opt/octopus/swarm/api/control_plane.py", "/app/swarm/api/control_plane.py"),
        ("/opt/octopus/swarm/api/control_plane.py", "/usr/local/lib/python3.11/site-packages/swarm/api/control_plane.py"),
        ("/opt/octopus/swarm/api/web_endpoints.py", "/app/swarm/api/web_endpoints.py"),
        ("/opt/octopus/swarm/api/web_endpoints.py", "/usr/local/lib/python3.11/site-packages/swarm/api/web_endpoints.py"),
    ]
    for src, dst in code_patches:
        cmd.extend(["-v", f"{src}:{dst}:ro"])

    cmd.extend([
        "-e", f"OCTOPUS_PARENT_PUBKEY={parent_pub}",
        "-e", f"OCTOPUS_PARENT_NODE_ID={parent_id}",
        "octopus-current:latest",
        "python", "/deploy/run_node.py", "/etc/octopus/config.yaml",
        str(port), bootstrap,
    ])

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.strip()[:300]}
        cid = r.stdout.strip()
        return {
            "ok": True, "name": name, "port": port, "bootstrap": bootstrap,
            "container_id": cid[:12], "scratch": str(scratch),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def handle_swarm_kill(container, body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if not NODE_NAME_RE.match(name) or name == "octopus":
        return {"ok": False, "error": "invalid or protected name"}
    try:
        r = subprocess.run(["docker", "rm", "-f", name],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.strip()}
        return {"ok": True, "name": name}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _port_taken(port: int) -> bool:
    import socket
    for fam in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        sk = socket.socket(socket.AF_INET, fam)
        try:
            sk.bind(("0.0.0.0", port))
        except OSError:
            sk.close()
            return True
        sk.close()
    return False


# ───────────────────────────── migrate payload ──────────────────────────────

def handle_files_migrate_payload(container, body: dict) -> dict:
    """
    Для всех VFS-файлов БЕЗ payload.bin — пересоздаём его из
    .swarm_scratch/<uuid>/blob (метаданных) + content_preview.
    Возвращает {migrated:int, skipped:int}.
    """
    SCRATCH = Path("/app/.swarm_scratch")
    if not SCRATCH.exists():
        return {"ok": False, "error": "scratch not found"}

    migrated = 0
    skipped = 0
    errors = 0
    details = []

    for d in SCRATCH.iterdir():
        if not d.is_dir():
            continue
        blob = d / "blob"
        payload = d / "payload.bin"
        if payload.exists() or not blob.exists():
            skipped += 1
            continue
        try:
            raw = blob.read_text(encoding="utf-8", errors="ignore")
            try:
                meta = json.loads(raw)
            except Exception:
                # blob это не JSON — значит это уже сырой файл, копируем
                payload.write_text(raw)
                migrated += 1
                details.append({"uuid": d.name, "from": "raw_blob", "size": len(raw)})
                continue
            preview = meta.get("content_preview", "")
            if preview:
                payload.write_text(preview)
                migrated += 1
                details.append({"uuid": d.name, "from": "preview", "size": len(preview)})
            else:
                skipped += 1
        except Exception as e:
            errors += 1
            _LOG.warning("migrate %s: %s", d.name, e)

    return {
        "ok": True,
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
        "details": details[:20],
    }



# ──────────────────────── recommendations engine ────────────────────────────

def _generate_recommendations(stats: dict, by_table: dict, by_tag: dict,
                              swarm_nodes: list, iter_last,
                              ts_min: float, ts_max: float) -> list:
    """
    Эвристический генератор рекомендаций «что улучшить дальше».
    Возвращает список {priority, vector, title, why, action}.
    Приоритеты: high|med|low. Векторы: размножаться|развиваться|учиться|меняться|жить.
    """
    recs = []
    now = time.time()

    # вектор «размножаться»
    running = [n for n in (swarm_nodes or []) if n.get("running")]
    total   = len(swarm_nodes or [])
    if total == 0:
        recs.append({
            "priority": "high", "vector": "размножаться",
            "title": "Рой пуст",
            "why": "Не вижу ни одной docker-ноды octopus*.",
            "action": "Проверить docker.sock в systemd unit и запустить spawn вручную через UI «Рой → Породить».",
        })
    elif len(running) < 2:
        recs.append({
            "priority": "high", "vector": "размножаться",
            "title": "Только одна активная нода",
            "why": "running=%d из %d. Вектор «размножаться» не закрыт." % (len(running), total),
            "action": "POST /api/v1/swarm/spawn {} — запустить хотя бы 2 child-узла.",
        })
    elif len(running) >= 6:
        recs.append({
            "priority": "low", "vector": "меняться",
            "title": "Много child-нод — стоит сделать чистку",
            "why": "%d активных контейнеров, ресурсы хоста ограничены." % len(running),
            "action": "Убить устаревшие octopus-child-* через /api/v1/swarm/kill.",
        })

    # вектор «учиться»
    records = stats.get("records", 0) if isinstance(stats, dict) else 0
    if records < 50:
        recs.append({
            "priority": "med", "vector": "учиться",
            "title": "Мало записей в памяти",
            "why": "всего %d записей — RAG/архивист почти не использовался." % records,
            "action": "Прогреть память: POST notes/files через API, запустить archivist.",
        })

    iter_table_present = any("iter" in (t or "").lower() for t in by_table.keys())
    if iter_last is None and not iter_table_present:
        recs.append({
            "priority": "med", "vector": "учиться",
            "title": "Нет логов итераций в памяти",
            "why": "В памяти не найдено записей с тегом/именем iteration_NN.",
            "action": "Синхронизировать ~/agents/-Octopus/logs/ в swarm-память (Archivist).",
        })

    if not by_tag:
        recs.append({
            "priority": "low", "vector": "учиться",
            "title": "Не используются теги",
            "why": "by_tag пуст — у записей нет тегов, поиск/группировка страдают.",
            "action": "Включить авто-тегирование при записи notes/files (по ключевым словам).",
        })

    # вектор «жить»
    if ts_max and (now - ts_max) > 3600 * 24:
        age_h = (now - ts_max) / 3600
        recs.append({
            "priority": "high", "vector": "жить",
            "title": "Память не обновлялась более суток",
            "why": "последняя запись была %.1fч назад." % age_h,
            "action": "Проверить, что archivist/notes-writer не упали; перезапустить octopus.service при необходимости.",
        })

    # вектор «развиваться» — закрыто в итерации #22
    # require_ed25519=true ВКЛЮЧЕНО, handshake whitelist'нут.
    # Динамический санити-чек: если кто-то откатил — снова показываем рекомендацию.
    try:
        import inspect as _ins
        from swarm.network.auth import AuthVerifier as _AV
        _verify_src = _ins.getsource(_AV.verify)
        _cfg_text = ""
        try:
            with open("/etc/octopus/config.yaml") as _f:
                _cfg_text = _f.read()
        except Exception:
            pass
        _ok = ("handshake_hello" in _verify_src) and ("require_ed25519: true" in _cfg_text)
        if not _ok:
            recs.append({
                "priority": "high", "vector": "развиваться",
                "title": "require_ed25519 откатился или whitelist потерян",
                "why": "После итерации #22 это должно быть включено. AuthVerifier.verify() должен иметь whitelist handshake_hello/ack/done, а config.yaml — require_ed25519: true.",
                "action": "Восстановить whitelist в swarm/network/auth.py и require_ed25519: true в /etc/octopus/config.yaml.",
            })
    except Exception:
        pass
    recs.append({
        "priority": "med", "vector": "размножаться",
        "title": "address пиров пустой в peer_list",
        "why": "После #21 parent видит child node_id, но без host:port — _handle_hello не знает remote addr.",
        "action": "Прокинуть в _handle_hello адрес отправителя через RPCServer middleware и сохранить в PeerInfo.address.",
    })
    recs.append({
        "priority": "med", "vector": "учиться",
        "title": "Awareness.swarm_map = 0 пиров",
        "why": "Несмотря на handshake, awareness gossip-карта пустая. Это отдельная подсистема.",
        "action": "Включить awareness broadcast в дочерних нодах и подписаться на gossip-топик в parent.",
    })
    recs.append({
        "priority": "low", "vector": "меняться",
        "title": "Дубликаты experience-файлов",
        "why": "В ~/agents/-Octopus/experience/ есть два *_context_restore_exp.md от 16:24.",
        "action": "Дедуплицировать по хэшу содержимого, оставить один.",
    })

    order = {"high": 0, "med": 1, "low": 2}
    recs.sort(key=lambda r: order.get(r["priority"], 9))
    return recs


# ───────────────────────────── self-reflection ──────────────────────────────

def handle_agent_reflect(container) -> dict:
    """LLM-powered self-reflection using GraphRAG, Wiki and Smoke Test."""
    import asyncio, time, json, subprocess
    out = {"ok": True, "ts": time.time(), "insights": [], "recommendations": []}
    
    if container is None:
        return {"ok": False, "error": "no container"}
        
    try:
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        
        async def _reflect():
            llm = container.llm
            grag = getattr(container, "graph_rag", None)
            if not llm or not grag:
                return "LLM or GraphRAG not ready for deep reflection."
            
            # 1. Run Smoke Test
            try:
                smoke_out = subprocess.check_output("/opt/octopus-smoke.sh", shell=True, text=True, stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                smoke_out = e.output
            except Exception as e:
                smoke_out = f"Smoke test failed to run: {e}"
                
            query = "Analyze current swarm state and propose technical improvements."
            context = await grag.retrieve_context(query, top_k=5)
            
            prompt = f"""You are the Swarm Architect. Analyze the current state of Octopus and propose development actions.
            
            Current Smoke Test Results:
            {smoke_out}
            
            Context from Knowledge Base:
            {context}
            
            Return a JSON object with:
            1. 'insights': list of strings (analysis of health and knowledge)
            2. 'recommendations': list of objects {{'priority': 'high|med|low', 'vector': 'развиваться|жить|...', 'title': str, 'why': str, 'action': str}}
            
            Prioritize fixing any FAILED smoke tests.
            """
            
            messages = [
                {"role": "system", "content": "You are a self-improving P2P system architect. Respond ONLY with JSON."},
                {"role": "user", "content": prompt}
            ]
            
            raw_resp = await llm.complete(messages)
            try:
                clean = raw_resp.strip()
                if clean.startswith("```json"): clean = clean[7:].strip()
                if clean.endswith("```"): clean = clean[:-3].strip()
                return json.loads(clean)
            except:
                return {
                    "insights": ["LLM response was not valid JSON", raw_resp[:200]],
                    "recommendations": []
                }

        llm_data = loop.run_until_complete(_reflect())
        loop.close()
        if isinstance(llm_data, dict):
            out.update(llm_data)
        return out
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    except Exception as exc:
        _LOG.exception("reflect failed")
        return {"ok": False, "error": str(exc), "insights": out["insights"]}
