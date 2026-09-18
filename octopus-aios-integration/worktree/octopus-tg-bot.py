#!/usr/bin/env python3
"""
Octopus Telegram Bot — standalone, подключается к control-plane API.
Запускается отдельно от ноды, общается через HTTP к 127.0.0.1:9100.
Поддерживает: /ask (LLM), /swarm, /nodes, /status, /peers, /health, /registry + все старые команды.
"""
from __future__ import annotations

import sqlite3
import re
import hmac
import hashlib

import sys as _sys
_sys.path.insert(0, '/opt')
from octopus_healthz import start_healthz as _start_healthz

_sys.path.insert(0, '/opt/aios')
try:
    from llm.llm_balancer import llm_balancer
except Exception:
    llm_balancer = None


import asyncio
import json
import logging
import os
import time
import subprocess
import shlex
import inspect
import urllib.request
import urllib.error
import urllib.parse
from base64 import b64encode

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [tg-bot] %(message)s")
log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

TG_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOW_IDS  = {int(x) for x in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").replace(";", ",").split(",") if x.strip().isdigit()}
OPEN_ACCESS = os.environ.get("TELEGRAM_OPEN_ACCESS", "0") == "1"
DASH_PASS  = os.environ.get("OCTOPUS_DASH_PASS", "")
CP_URL     = os.environ.get("OCTOPUS_CP_URL", "http://127.0.0.1:9100")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")

# ── Arena.ai Integration ─────────────────────────────────────────────────
ARENA_URL = os.environ.get("ARENA_API_URL", "http://127.0.0.1:13011/chat/api/v1/chat/completions")
ARENA_MODELS_URL = os.environ.get("ARENA_MODELS_URL", "http://127.0.0.1:13011/chat/api/v1/models")
ARENA_DEFAULT_MODEL = os.environ.get("ARENA_DEFAULT_MODEL", "gpt-5.5-instant")
ARENA_STATE_FILE = os.environ.get("ARENA_STATE_FILE", "/var/lib/octopus/arena_tg_state.json")
ARENA_TIMEOUT = int(os.environ.get("ARENA_TIMEOUT", "120"))


def _arena_load_state() -> dict:
    """Load persisted arena state (selected model per chat)."""
    try:
        with open(ARENA_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _arena_save_state(state: dict) -> None:
    """Persist arena state atomically."""
    try:
        import tempfile
        d = os.path.dirname(ARENA_STATE_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, ARENA_STATE_FILE)
    except Exception as e:
        log.warning("arena state save error: %s", e)


def _arena_get_model(chat_id: int) -> str:
    """Get the selected model for a chat, or default."""
    state = _arena_load_state()
    return state.get(str(chat_id), {}).get("model", ARENA_DEFAULT_MODEL)


def _arena_set_model(chat_id: int, model: str) -> None:
    """Set the model for a chat and persist."""
    state = _arena_load_state()
    key = str(chat_id)
    if key not in state:
        state[key] = {}
    state[key]["model"] = model
    _arena_save_state(state)


async def cmd_arena(text: str, chat_id: int = 0) -> str:
    """Ask Arena.ai any question. /arena <question>"""
    q = text.strip()
    if not q:
        return (
            "⚔️ *Arena.ai Chat*\n\n"
            "Использование: `/arena <вопрос>`\n"
            "Модель: см. `/arena_model`\n"
            "Список моделей: `/arena_models`\n\n"
            "_130+ моделей через arena.ai (headless browser automation)._"
        )
    # We don't know the chat_id here; it will be set by the wrapper
    model = _arena_get_model(chat_id) if chat_id else ARENA_DEFAULT_MODEL; return await _arena_ask_internal(q, model=model)


async def _arena_ask_internal(question: str, model: str | None = None) -> str:
    """Internal: send question to Arena API, return response text."""
    if model is None:
        model = ARENA_DEFAULT_MODEL
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Отвечай кратко и по делу. Если вопрос на русском — отвечай на русском."},
            {"role": "user", "content": question},
        ],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=ARENA_TIMEOUT) as c:
            r = await c.post(ARENA_URL, json=payload)
        if r.status_code != 200:
            try:
                err = r.json().get("error", {}).get("message", r.text[:200])
            except Exception:
                err = r.text[:200]
            return f"❌ Arena HTTP {r.status_code}: {err}"
        data = r.json()
        content = ""
        if "choices" in data and data["choices"]:
            content = data["choices"][0].get("message", {}).get("content", "")
        if not content:
            return "⚠️ Arena вернула пустой ответ"
        model_used = data.get("model", model)
        elapsed_ms = data.get("elapsed_ms", 0)
        header = f"⚔️ *Arena ({model_used})*"
        if elapsed_ms:
            header += f" _{elapsed_ms // 1000}s_"
        return f"{header}\n\n{content[:3500]}"
    except httpx.TimeoutException:
        return f"⏱ Arena timeout ({ARENA_TIMEOUT}s). Модель `{model}` может быть занята."
    except Exception as e:
        return f"❌ Ошибка Arena: {e}"


async def cmd_arena_model(text: str, chat_id: int = 0) -> str:
    """Get or set the arena model. /arena_model [model_name]"""
    parts = text.strip().split(None, 1)
    if not parts:
        current = _arena_get_model(chat_id) if chat_id else ARENA_DEFAULT_MODEL
        return (
            f"🔧 *Arena Model*\n\n"
            f"Текущая модель: `{current}`\n\n"
            f"Для смены: `/arena_model <имя>`\n"
            f"Список: `/arena_models`"
        )
    new_model = parts[0].strip()
    if chat_id:
        _arena_set_model(chat_id, new_model)
        return f"✅ Модель установлена: `{new_model}`"
    else:
        return f"⚙️ Модель для следующего запроса: `{new_model}` (chat_id неизвестен, не сохранено)"


async def cmd_arena_models(text: str) -> str:
    """List available arena models. /arena_models [search_filter]"""
    search = text.strip().lower()
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(ARENA_MODELS_URL)
        if r.status_code != 200:
            return f"❌ Не удалось получить список моделей (HTTP {r.status_code})"
        data = r.json()
        models = data.get("data", [])
        if not models:
            return "📋 Список моделей пуст"
        # Filter if search term provided
        if search:
            models = [m for m in models if search in m.get("id", "").lower()]
        if not models:
            return f"📋 Модели по запросу `{search}` не найдены"
        # Group by provider
        providers: dict[str, list] = {}
        for m in models:
            owner = m.get("owned_by", "other")
            arena_info = m.get("arena", {})
            provider = arena_info.get("provider", owner) if isinstance(arena_info, dict) else owner
            if provider not in providers:
                providers[provider] = []
            providers[provider].append(m)
        lines = [f"📋 *Arena Models* ({len(models)}total)"]
        if search:
            lines[0] += f" фильтр: `{search}`"
        lines.append("")
        for provider, pmodels in sorted(providers.items()):
            lines.append(f"*{provider}* ({len(pmodels)}):")
            for m in pmodels[:8]:
                mid = m.get("id", "?")
                desc = ""
                arena_info = m.get("arena", {})
                if isinstance(arena_info, dict):
                    desc = arena_info.get("description", "")
                if desc:
                    lines.append(f"  • `{mid}` — {desc[:50]}")
                else:
                    lines.append(f"  • `{mid}`")
            if len(pmodels) > 8:
                lines.append(f"  _...и ещё {len(pmodels) - 8}_")
            lines.append("")
        return "\n".join(lines)[:3900]
    except Exception as e:
        return f"❌ Ошибка получения моделей: {e}"


TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"
_offset = 0
_client: httpx.AsyncClient | None = None


# ── Control-plane helper ──────────────────────────────────────────────────────

def cp_get(path: str) -> dict:
    creds = b64encode(f"admin:{DASH_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{CP_URL}{path}",
        headers={"Authorization": f"Basic {creds}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


# ── LLM ───────────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

async def _gemini_ask(question: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("no gemini key")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": question}]}],
        "systemInstruction": {"parts": [{"text": "Ты агент P2P системы Octopus. Отвечай кратко и по делу по-русски."}]},
        "generationConfig": {"maxOutputTokens": 800, "temperature": 0.4},
    }
    async with httpx.AsyncClient(timeout=40.0) as c:
        r = await c.post(url, json=payload)
        d = r.json()
        return d["candidates"][0]["content"]["parts"][0]["text"].strip()

async def _ollama_ask(question: str) -> str:
    async with httpx.AsyncClient(timeout=35.0) as c:
        r = await c.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": question, "stream": False,
                  "system": "Ты агент P2P системы Octopus. Отвечай кратко по-русски."}
        )
        d = r.json()
        return d.get("response", "Нет ответа").strip()

async def llm_ask(question: str) -> str:
    if llm_balancer is not None:
        try:
            ans = await llm_balancer.generate(question, tier="default")
            if ans and not ans.startswith("Error:"):
                return ans
        except Exception as e:
            log.warning("LLMBalancer error, trying direct fallback: %s", e)
    try:
        ans = await _gemini_ask(question)
        if ans:
            return ans
    except Exception as e:
        log.warning("Gemini failed, fallback to ollama: %s", str(e)[:120])
    try:
        return await _ollama_ask(question)
    except asyncio.TimeoutError:
        return "⏱ Timeout — LLM занята"
    except Exception as e:
        return f"❌ LLM ошибка: {e}"


def load_registry() -> dict:
    try:
        with open('/var/lib/octopus/nodes.json') as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e), "nodes": []}


# ── Команды ───────────────────────────────────────────────────────────────────


# ── AIOS & LLMBalancer Control Center ─────────────────────────────────────────
AIOS_URL = os.environ.get("OCTOPUS_AIOS_URL", "http://127.0.0.1:9600")

async def cmd_aios(goal: str) -> str:
    """Submit autonomous goal to AIOS Kernel. /aios <goal>"""
    g = goal.strip()
    if not g:
        return (
            "🐙 *AIOS Autonomous Kernel*\n\n"
            "Использование: `/aios <цель>`\n"
            "Пример: `/aios Проверь целостность снапшотов OCI и здоровье нод`\n\n"
            "_Автономно декомпозирует задачу, выполняет через LLMBalancer; статус отслеживается по task_id._"
        )
    try:
        payload = {"goal": g}
        async with httpx.AsyncClient(timeout=45.0) as c:
            r = await c.post(f"{AIOS_URL}/api/v1/aios/execute", json=payload)
        if r.status_code == 200:
            data = r.json()
            task_id = data.get("task_id")
            status = data.get("status", "queued")
            result = data.get("result")
            if status not in ("completed", "failed") and task_id:
                async with httpx.AsyncClient(timeout=10.0) as c:
                    for _ in range(8):
                        await asyncio.sleep(5)
                        tr = await c.get(f"{AIOS_URL}/api/v1/aios/tasks/{task_id}")
                        if tr.status_code == 200:
                            td = tr.json()
                            status = td.get("status", status)
                            result = td.get("result") or result
                            if status in ("completed", "failed"):
                                break
            icon = {"completed": "✅", "failed": "❌"}.get(status, "⏳")
            res_str = str(result)[:600] if result else ""
            return (
                f"🐙 *AIOS Execution Report*\n\n"
                f"*Цель:* {g}\n"
                f"*Задача:* `{task_id}`\n"
                f"*Статус:* {icon} `{status}`\n\n"
                f"*Результат:*\n{res_str or '_задача ещё выполняется — повторите проверку позже_'}"
            )
        else:
            return f"❌ AIOS Error HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return f"❌ Ошибка вызова AIOS: {e}"

async def cmd_debate(topic: str) -> str:
    """Multi-Agent debate tribunal. /debate <topic>"""
    t = topic.strip()
    if not t:
        return (
            "⚖️ *AIOS Debate Tribunal*\n\n"
            "Использование: `/debate <тема или вопрос>`\n"
            "Пример: `/debate Стоит ли переносить базу PostgreSQL на AMD micro ноду?`\n\n"
            "_Запускает 3-агентный трибунал (Тезис, Антитезис, Синтез/Судья) через LLMBalancer._"
        )
    try:
        p1 = f"Ты эксперт 1 (Тезис). Защищай позицию 'ЗА' по теме: {t}. Аргументируй кратко и строго (до 3 пунктов)."
        ans1 = await llm_ask(p1)
        p2 = f"Ты эксперт 2 (Антитезис/Критик). Приведи главные риски и контраргументы против позиции:\n{ans1}\nТема: {t}."
        ans2 = await llm_ask(p2)
        p3 = f"Ты Верховный Судья AIOS. Взвесь оба мнения и сформулируй итоговый консенсус и рекомендацию:\n\nТезис:\n{ans1}\n\nАнтитезис:\n{ans2}"
        verdict = await llm_ask(p3)
        return (
            f"⚖️ *AIOS Multi-Agent Tribunal*\n\n"
            f"*Тема:* {t}\n\n"
            f"🟢 *Тезис (Agent A):*\n{ans1[:600]}\n\n"
            f"🔴 *Антитезис (Agent B):*\n{ans2[:600]}\n\n"
            f"👑 *Вердикт Судьи:*\n{verdict[:1200]}"
        )
    except Exception as e:
        return f"❌ Ошибка дебатов: {e}"

async def cmd_cluster(text: str = "") -> str:
    """Real-time 3-node cluster topology & health. /cluster"""
    import socket
    nodes = [
        {"name": "arm-server-01 (Primary)", "ip": "10.0.0.3", "role": "AIOS Kernel, Parent Swarm, LLMBalancer", "port": 9600},
        {"name": "octopus-micro-01 (AMD)", "ip": "10.0.0.2", "role": "AIOS Worker 1, Memory Mirror", "port": 9400},
        {"name": "octopus-micro-02 (AMD)", "ip": "10.0.0.87", "role": "AIOS Worker 2, CAS/Sync Backup", "port": 9400}
    ]
    lines = ["🌐 *Octopus 3-Node OCI Free-Tier Cluster*", ""]
    for n in nodes:
        try:
            with socket.create_connection((n["ip"], n["port"]), timeout=0.8):
                st = "🟢 UP"
        except Exception:
            st = "🔴 DOWN"
        lines.append(f"*{n['name']}* [{st}]")
        lines.append(f"  • IP: `{n['ip']}` | Порт: `{n['port']}`")
        lines.append(f"  • Роль: _{n['role']}_")
        lines.append("")
    lines.append("🔀 *LLMBalancer:* Gemini 2.5 Flash + Ollama Local Pool (qwen2.5, deepseek-r1, llama3.2)")
    lines.append("🛡 *OCI Vault Storage:* 20 GB Bucket Quota Guard Active")
    return "\n".join(lines)

async def cmd_vault(text: str = "") -> str:
    """OCI Vault Object Storage snapshot status. /vault"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "python3", "/opt/octopus-oci-vault-sync.py", "list",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        out = stdout.decode().strip()
        return (
            f"🛡 *OCI Immortal Vault Storage*\n\n"
            f"```text\n{out[:3000]}\n```\n"
            f"💾 *Квота:* Защищена жестким лимитом (до 18 GB из 20 GB Free-Tier)."
        )
    except Exception as e:
        return f"❌ Ошибка получения статуса Vault: {e}"

async def cmd_skills(query: str = "") -> str:
    """Semantic vector search across crystallized knowledge base. /skills <query>"""
    q = query.strip()
    if not q:
        return (
            "📚 *AIOS Crystallized Skills Memory Fabric*\n\n"
            "Всего навыков в базе: 51 (автоматически кристаллизовано из логов и опыта).\n"
            "Векторный поиск: `nomic-embed-text` (768-мерные эмбеддинги).\n\n"
            "Использование: `/skills <запрос>`\n"
            "Пример: `/skills расширение диска без перезагрузки`"
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "python3", "/opt/octopus-skills-vectorizer.py", "find", q,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout.decode().strip())
        results = data.get("results", [])
        if not results:
            return f"🔍 По запросу `{q}` навыки не найдены."
        lines = [f"📚 *Найдено навыков по запросу:* `{q}`\n"]
        for r in results[:4]:
            lines.append(f"• *{r.get('title')}* (score: `{r.get('score')}`)")
            lines.append(f"  _{r.get('snippet')[:120]}..._\n")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Ошибка векторного поиска: {e}"

async def cmd_slo(text: str = "") -> str:
    """Octopus 15/15 Service-Level Objectives checker. /slo"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "python3", "/opt/octopus-slo-checker.py",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return f"🩺 *Octopus Cluster SLO Report*\n\n```text\n{stdout.decode()[:3500]}\n```"
    except Exception as e:
        return f"❌ Ошибка проверки SLO: {e}"

async def cmd_tools(text: str = "") -> str:
    """AIOS Dynamic Tool Sandbox Registry. /tools"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "/opt/aios-venv/bin/python3", "/opt/octopus-aios-tool-factory.py", "list",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout.decode().strip())
        lines = ["🎛 *AIOS Dynamic Tool Factory*", ""]
        for name, info in data.items():
            lines.append(f"• `{name}` — _{info.get('description')}_")
        lines.append("\nВызов: `/tool <имя_инструмента>`")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Ошибка реестра инструментов: {e}"

async def cmd_tool(text: str = "") -> str:
    """Execute dynamic sandboxed AIOS tool. /tool <name>"""
    name = text.strip().split()[0] if text.strip() else "cluster_health"
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "/opt/aios-venv/bin/python3", "/opt/octopus-aios-tool-factory.py", "run", name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return f"🎛 *Tool Execution ({name}):*\n```json\n{stdout.decode()[:3500]}\n```"
    except Exception as e:
        return f"❌ Ошибка исполнения инструмента: {e}"


async def transcribe_voice_groq(file_id: str) -> str:
    """Download audio file from Telegram and transcribe via Groq Whisper with rotating keys."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(f"{TG_API}/getFile?file_id={file_id}")
            if res.status_code != 200:
                return ""
            file_path = res.json().get("result", {}).get("file_path")
            if not file_path:
                return ""
            
            dl_url = f"https://api.telegram.org/file/bot{TG_TOKEN}/{file_path}"
            audio_data = (await client.get(dl_url)).content
            
            groq_keys = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
            if not groq_keys:
                groq_keys = [os.environ.get("GROQ_API_KEY", "")]
            
            for k in groq_keys:
                try:
                    files = {"file": ("voice.oga", audio_data, "audio/ogg")}
                    data = {"model": "whisper-large-v3-turbo"}
                    headers = {"Authorization": f"Bearer {k}"}
                    w_res = await client.post("https://api.groq.com/openai/v1/audio/transcriptions", headers=headers, files=files, data=data)
                    if w_res.status_code == 200:
                        return w_res.json().get("text", "").strip()
                except Exception:
                    continue
    except Exception as e:
        log.warning("Whisper transcription error: %s", e)
    return ""


async def cmd_keys(rest: str) -> str:
    from aios.llm.llm_balancer import LLMBalancer
    b = LLMBalancer.get_instance()
    stats = b.get_stats()
    lines = [
        "🔑 *Статус пула API-ключей и провайдеров AIOS*",
        f"Всего провайдеров: `{stats['total_providers']}`",
        f"Кэш запросов: `{stats['cache_size']}` записей\n",
        "*Активные провайдеры:*"
    ]
    for p in stats["providers"]:
        status = "🟢 Онлайн" if p["healthy"] else "🔴 Недоступен"
        lines.append(f"• *{p['name']}* ({p['tier']}): {status} | Ключей: `{p['keys_count']}` | Вызовов: `{p['calls']}` | RTT: `{p['avg_latency_ms']}ms`")
    return "\n".join(lines)


async def cmd_benchmark(rest: str) -> str:
    from aios.llm.llm_balancer import LLMBalancer
    b = LLMBalancer.get_instance()
    lines = ["⚡ *Бенчмарк производительности AI-провайдеров*:\n"]
    for tier in ["fast", "reasoning", "code"]:
        t0 = time.time()
        res = await b.ask("Ответь 'OK'", task_type=tier, use_cache=False)
        dt = round((time.time() - t0) * 1000, 1)
        lines.append(f"• Уровень `{tier}` -> *{res.get('provider')}*: `{dt} ms`")
    return "\n".join(lines)


async def cmd_route(rest: str) -> str:
    if not rest:
        return "ℹ️ Использование: `/route <fast|reasoning|code|long_context|local> <запрос>`"
    parts = rest.split(None, 1)
    tier = parts[0].lower()
    prompt = parts[1] if len(parts) > 1 else "Привет"
    from aios.llm.llm_balancer import LLMBalancer
    b = LLMBalancer.get_instance()
    res = await b.ask(prompt, task_type=tier, use_cache=False)
    return f"🧭 *Маршрут:* `{res.get('tier')}` via *{res.get('provider')}*\n\n{res.get('text')}"

async def cmd_ask(text: str) -> str:
    q = text.strip()
    if not q:
        return "Использование: `/ask <вопрос>`"
    answer = await llm_ask(q)
    return f"🤖 *Octopus AI:*\n{answer[:3000]}"


async def cmd_expert(text: str) -> str:
    q = text.strip()
    if not q:
        return "Использование: `/expert <запрос>`\nГлубокий анализ через Hermes CLI (bounded, max-turns=8)."
    if not os.path.exists("/usr/local/bin/hermes"):
        return "❌ Hermes CLI не найден: /usr/local/bin/hermes"
    try:
        proc = await asyncio.create_subprocess_exec(
            "/usr/local/bin/hermes", "chat", "-q", q, "-Q", "--max-turns", "8",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            return "⏱ Hermes timeout (180s). Попробуй сузить задачу."
        result = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        if not result:
            result = err or "Hermes не вернул ответ."
        elif err and "error" in err.lower():
            result += "\n\n(stderr) " + err[:600]
        return f"🧠 *Hermes Expert:*\n{result[:3500]}"
    except Exception as e:
        return f"❌ Ошибка Hermes: {e}"


def _registry_node_lines(limit: int = 12) -> list[str]:
    reg = load_registry()
    nodes = reg.get('nodes', []) if not reg.get('error') else []
    lines = []
    for n in nodes[:limit]:
        if n.get('quarantined'):
            icon = '🔴'
        elif not n.get('enabled'):
            icon = '⚫'
        elif n.get('external'):
            icon = '🌐'
        else:
            icon = '🟢'
        lines.append(f"{icon} `{n.get('id','?')}` {n.get('ip','?')}:{n.get('control_port','?')} role=`{n.get('role','?')}`")
    return lines


def cmd_swarm(_: str) -> str:
    info = cp_get("/api/v1/node/info")
    if "error" in info:
        summary = _run("octopus summary | head -16", 12)
        lines = ["🐙 *Octopus Swarm Status*", "", "_Control-plane legacy API недоступен, показываю live ops fallback._", "", "```text", summary[:1200], "```", "", "*Registry nodes:*"]
        lines.extend(_registry_node_lines(10) or ["— registry пуст/недоступен"])
        return "\n".join(lines)[:3800]
    peers_data = cp_get("/api/v1/network/peers")
    auth = info.get("auth", {})
    gossip = info.get("gossip", {})
    hk = info.get("handshake", {})
    uptime = int(info.get("uptime_seconds") or 0)
    peers_list = sorted(set(peers_data.get("peers", [])))
    lines = [
        "🐙 *Octopus Swarm Status*",
        f"Node: `{info.get('node_id','')[:16]}...`",
        f"Verified peers: `{auth.get('verified_peers', 0)}`",
        f"Known (handshake): `{hk.get('known_peers', 0)}`",
        f"Gossip peers: `{gossip.get('peers', 0)}` | seen: `{gossip.get('seen', 0)}`",
        f"Uptime: `{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s`",
    ]
    if peers_list:
        lines.append("\n*Kademlia peers:*")
        for p in peers_list[:8]:
            lines.append(f"  • `{p}`")
    return "\n".join(lines)


def cmd_nodes(_: str) -> str:
    peers_data = cp_get("/api/v1/network/peers")
    if "error" in peers_data:
        lines = ["🌐 *Ноды роя (registry fallback):*"]
        lines.extend(_registry_node_lines(20) or [f"❌ registry/control-plane недоступны: {peers_data['error']}"])
        return "\n".join(lines)[:3800]
    peers = sorted(set(peers_data.get("peers", [])))
    if not peers:
        return "🌐 *Нет известных нод*\nРой только стартует или изолирован."
    lines = [f"🌐 *Ноды роя* ({len(peers)}):"]
    for p in peers:
        lines.append(f"  `{p}`")
    return "\n".join(lines)


def cmd_status(_: str) -> str:
    info = cp_get("/api/v1/node/info")
    if "error" in info:
        summary = _run("octopus summary | head -14", 12)
        return "*Octopus Node Status* (fallback)\n```text\n" + summary[:1600] + "\n```"
    auth = info.get("auth", {})
    gossip = info.get("gossip", {})
    uptime = int(info.get("uptime_seconds") or 0)
    lines = [
        "*Octopus Node Status*",
        f"Node ID: `{info.get('node_id','')[:20]} `",
        f"Port: `{info.get('port', 0)}`",
        f"Uptime: `{uptime // 3600}h {(uptime % 3600) // 60}m`",
        f"Verified peers: `{auth.get('verified_peers', 0)}`",
        f"Ed25519: `{auth.get('ed25519', False)}`",
        f"Gossip received: `{gossip.get('total_received', 0)}`",
        f"Gossip sent: `{gossip.get('total_sent', 0)}`",
    ]
    return "\n".join(lines)


def cmd_peers(_: str) -> str:
    return cmd_nodes(_)


def cmd_registry(_: str) -> str:
    reg = load_registry()
    if reg.get('error'):
        return f"❌ Registry error: {reg['error']}"
    nodes = reg.get('nodes', [])
    if not nodes:
        return "🗂️ *Registry пуст*"
    enabled = [n for n in nodes if n.get('enabled')]
    online = [n for n in enabled if not n.get('quarantined')]
    external = [n for n in nodes if n.get('external')]
    quarantined = [n for n in nodes if n.get('quarantined')]
    lines = [
        "🗂️ *Octopus Registry*",
        f"Всего: `{len(nodes)}` | online/enabled: `{len(online)}/{len(enabled)}` | external: `{len(external)}` | quarantine: `{len(quarantined)}`",
    ]
    for n in nodes:
        if n.get('quarantined'):
            status = '🔴'
        elif not n.get('enabled'):
            status = '⚫'
        elif n.get('external'):
            status = '🌐'
        else:
            status = '🟢'
        role = n.get('role','?')
        ip = n.get('ip','?')
        control = n.get('control_port','?')
        swarm = n.get('swarm_port','?')
        suffix = ''
        if n.get('quarantined'):
            suffix = ' — ' + (n.get('quarantine_reason','quarantined')[:80])
        lines.append(f"{status} `{n.get('id','?')}` `{role}` {ip}:{control} / swarm:{swarm}{suffix}")
    return "\n".join(lines)[:3800]


def cmd_health(_: str) -> str:
    reg = load_registry()
    nodes = [n for n in reg.get('nodes', []) if n.get('enabled') and not n.get('quarantined')]
    if not nodes:
        nodes = [{'id': 'parent-8000', 'ip': '127.0.0.1', 'control_port': 9100}]
    lines = ["🏥 *Node Health Check (registry-driven):*"]
    creds = b64encode(f"admin:{DASH_PASS}".encode()).decode()
    for n in nodes[:12]:
        host = n.get('ip') or '127.0.0.1'
        port = n.get('control_port')
        label = n.get('id', f"{host}:{port}")
        if not port:
            lines.append(f"  ⚠️ `{label}` — no control_port")
            continue
        try:
            ok = False
            last_err = ""
            for path in ("/healthz", "/metrics", "/"):
                try:
                    req = urllib.request.Request(f"http://{host}:{port}{path}", headers={"Authorization": f"Basic {creds}"})
                    with urllib.request.urlopen(req, timeout=2) as rr:
                        if 200 <= getattr(rr, "status", 200) < 400:
                            ok = True
                            break
                except Exception as ee:
                    last_err = str(ee)[:45]
            if ok:
                lines.append(f"  ✅ `{label}` ({host}:{port})")
            else:
                lines.append(f"  ❌ `{label}` ({host}:{port}) — {last_err}")
        except Exception as e:
            lines.append(f"  ❌ `{label}` ({host}:{port}) — {str(e)[:45]}")
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as r:
            models = json.loads(r.read()).get("models", [])
            model_names = [m.get("name", "") for m in models]
        lines.append(f"  ✅ `ollama` — {', '.join(model_names[:3])}")
    except Exception:
        lines.append(f"  ❌ `ollama` — недоступен")
    return "\n".join(lines)[:3800]


def cmd_ai_health(_: str) -> str:
    """Check status of Hermes AI loop and last audit."""
    lines = ["🧠 *AI Health Status*"]
    try:
        with open('/mnt/swarm/hermes_home/logs/self_audit.log', 'r') as f:
            last_lines = f.readlines()[-5:]
            lines.append("\\n*Last Audit Logs:*")
            lines.extend([f"  `{l.strip()}`" for l in last_lines])
    except Exception as e:
        lines.append(f"❌ Could not read audit logs: {e}")
    
    try:
        import subprocess
        res = subprocess.run(['systemctl', 'is-active', 'hermes-gateway'], capture_output=True, text=True)
        status = "🟢 Active" if res.stdout.strip() == "active" else "🔴 Inactive"
        lines.append(f"\\nGateway: {status}")
    except:
        lines.append("\\nGateway: Status unknown")
        
    return "\\n".join(lines)


def _run(cmd: str, timeout: int = 12) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        return out.strip()
    except subprocess.TimeoutExpired:
        return "timeout"
    except Exception as e:
        return str(e)


def _pg(sql: str, timeout: int = 8) -> str:
    return _run("sudo -u postgres psql -d ingest_db -Atc " + shlex.quote(sql), timeout)


def _bar(ok: int, total: int, width: int = 10) -> str:
    if total <= 0: return "░" * width
    fill = max(0, min(width, round(width * ok / total)))
    return "█" * fill + "░" * (width - fill)


def cmd_ops(_: str) -> str:
    summary = _run("octopus summary", 15)
    # Full smoke can be slow; keep Telegram responsive and rely on cached summary when test times out.
    test = _run("octopus test", 12)
    df = _run("df -h / | tail -1 | awk '{print $3\"/\"$2\" \"$5}'")
    slo = "green" if "SLO: green" in summary else ("yellow" if "SLO: yellow" in summary else "red")
    passed = total = 0
    import re
    m = re.search(r"Result: (\d+)/(\d+) pass", test)
    if m:
        passed, total = int(m.group(1)), int(m.group(2))
    color = "🟢" if slo == "green" else ("🟡" if slo == "yellow" else "🔴")
    lines = [
        "📊 *Octopus Центр управления*",
        f"{color} SLO: *{slo}*",
        f"Тесты: `{passed}/{total}` `{_bar(passed,total)}`",
        f"Диск: `{df}`",
    ]
    if "Failed octopus units: none" in summary:
        lines.append("Сервисы: ✅ failed units нет")
    else:
        lines.append("Сервисы: ⚠️ есть проблемы — нажми 🏥 Health")
    lines.append("\n_Выбери действие кнопками ниже._")
    return "\n".join(lines)


def cmd_audio_queue(_: str) -> str:
    q = _run("su - postgres -c \"psql -d ingest_db -Atc \\\"select status,count(*) from transcriptions group by status order by status;\\\"\"", 10)
    recent = _run("su - postgres -c \"psql -d ingest_db -Atc \\\"select upload_id,status,coalesce(left(error,60),''),to_char(updated_at,'HH24:MI') from transcriptions order by updated_at desc limit 6;\\\"\"", 10)
    counts = {}
    for line in q.splitlines():
        if '|' in line:
            k,v=line.split('|',1); counts[k]=int(v or 0)
    total=sum(counts.values()) or 1
    lines=["🎙 *Audio Queue*", ""]
    for k,emoji in [("done","✅"),("processing","⏳"),("transcribed","📤"),("failed","❌"),("corrupt","🧱"),("empty","▫️")]:
        v=counts.get(k,0)
        if v:
            lines.append(f"{emoji} {k}: `{v}` `{_bar(v,total,8)}`")
    lines.append("\n*Последние:*")
    for line in recent.splitlines():
        parts=line.split('|')
        if len(parts)>=4:
            uid,st,err,tm=parts[:4]
            extra=f" — {err}" if err else ""
            lines.append(f"`#{uid}` {st} `{tm}`{extra}")
    return "\n".join(lines)[:3800]


def cmd_duplicates(_: str) -> str:
    out = _run("su - postgres -c \"psql -d ingest_db -Atc \\\"select left(sha256,12),count(*),min(id),left(string_agg(filename, ', ' order by uploaded_at desc),120) from uploads group by sha256 having count(*)>1 order by count(*) desc limit 15;\\\"\"", 10)
    lines = ["♻️ *Дубликаты audio uploads*", ""]
    if not out:
        return "♻️ *Дубликаты*\n\n✅ Дубликатов в БД нет. Web uploader теперь пропускает повторные файлы до upload."
    for line in out.splitlines():
        parts=line.split('|')
        if len(parts)>=4:
            sha,n,first,names=parts[:4]
            lines.append(f"• `{sha}` ×`{n}` first=`#{first}` — {names}")
    try:
        st = json.load(open('/var/lib/octopus/duplicate_prevented.json'))
        bs = int(st.get('bytes_saved') or 0)
        def fb(b):
            return (str(b)+' B') if b<1024 else (f"{b/1024:.1f} KB" if b<1048576 else (f"{b/1048576:.1f} MB" if b<1073741824 else f"{b/1073741824:.2f} GB"))
        lines.append(f"\n*Prevented:* `{st.get('total',0)}` · bytes saved `{fb(bs)}`")
        for r in (st.get('recent') or [])[:5]:
            lines.append(f"  saved `{str(r.get('sha256',''))[:12]}` {r.get('filename','')} · {fb(int(r.get('size_bytes') or 0))}")
    except Exception:
        pass
    return "\n".join(lines)[:3500]


def cmd_voice_id(_: str) -> str:
    prof = _pg("select p.name,vp.samples,round(vp.speech_sec::numeric,1) from voice_profiles vp join people p on p.id=vp.person_id order by vp.samples desc,p.name limit 10;")
    matches = _pg("select svm.recording_id,svm.speaker,p.name,round(svm.score::numeric,3),svm.status from speaker_voice_matches svm left join people p on p.id=svm.matched_person_id order by svm.score desc,svm.updated_at desc limit 12;")
    lines=["🎤 *Voice ID*", ""]
    lines.append("*Профили:*")
    lines += (["• "+x.replace('|',' · ') for x in prof.splitlines()] if prof else ["— пока нет"])
    lines.append("\n*Совпадения:*")
    lines += (["• #"+x.replace('|',' / ',1).replace('|',' → ',1).replace('|',' · score ',1).replace('|',' · ') for x in matches.splitlines()] if matches else ["— пока нет"])
    lines.append("\nPWA: Панель → 🎤 Voice ID. Команда запуска на сервере ограничена и консервативна.")
    return "\n".join(lines)[:3800]


def cmd_speakers(_: str) -> str:
    out = _run("/opt/octopus_speaker_map.py list | head -30", 10)
    if not out:
        return "👥 *Speakers*\nПока нет speaker rows."
    return "👥 *Speaker Mapping*\n`/speaker_assign <rec> <SPK> <Имя>`\n\n```text\n" + out[:2800] + "\n```"


def cmd_speaker_assign(text: str) -> str:
    parts = text.strip().split()
    if len(parts) < 3:
        return "Использование: `/speaker_assign <recording_id> <speaker> <person_name>`"
    rec, sp, name = parts[0], parts[1], " ".join(parts[2:])
    out = _run(f"/opt/octopus_speaker_map.py assign {rec} {sp} {name!r}", 10)
    return "👥 *Speaker assign*\n```text\n" + out[:1200] + "\n```"


def cmd_retry(text: str) -> str:
    t = text.strip()
    if not t.isdigit():
        return "Использование: `/retry <upload_id>`"
    out = _run("su - postgres -c \"psql -d ingest_db -c \\\"update transcriptions set status='failed', error='manual_retry_from_tg', updated_at=now()-interval '2 hours' where upload_id=%s and status <> 'corrupt';\\\"\"" % t, 10)
    return f"🔁 Retry #{t}\n```text\n{out[:1000]}\n```"


def cmd_person_merge(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return "Использование: `/person_merge <from_id_or_name> <to_id_or_name>`"
    out = _run(f"/opt/octopus_people_tools.py merge {parts[0]!r} {parts[1]!r}", 20)
    return "🔀 *Person merge*\n```text\n" + out[:1500] + "\n```"


def cmd_person_rename(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return "Использование: `/person_rename <old_id_or_name> <new_name>`"
    out = _run(f"/opt/octopus_people_tools.py rename {parts[0]!r} {parts[1]!r}", 20)
    return "✏️ *Person rename*\n```text\n" + out[:1500] + "\n```"


def cmd_people_graph(_: str) -> str:
    nodes = _run("su - postgres -c \"psql -d ingest_db -Atc \\\"select id,name,mention_count from people order by mention_count desc,name limit 12;\\\"\"", 10)
    edges = _run("su - postgres -c \"psql -d ingest_db -Atc \\\"select pa.name,pb.name,pr.weight from person_relations pr join people pa on pa.id=pr.person_a join people pb on pb.id=pr.person_b order by pr.weight desc, pr.last_seen desc limit 12;\\\"\"", 10)
    lines=["🕸 *Граф людей*", ""]
    lines.append("*Люди:*")
    if nodes:
        for line in nodes.splitlines():
            p=line.split('|')
            if len(p)>=3: lines.append(f"• `#{p[0]}` {p[1]} · mentions `{p[2]}`")
    else:
        lines.append("— нет людей")
    lines.append("\n*Связи:*")
    if edges:
        for line in edges.splitlines():
            p=line.split('|')
            if len(p)>=3: lines.append(f"• {p[0]} ↔ {p[1]} · `{p[2]}`")
    else:
        lines.append("— связей пока нет")
    lines.append("\n_PWA: вкладка Панель → Граф людей._")
    return "\n".join(lines)[:3800]


def cmd_roadmap(_: str) -> str:
    path = "/root/agents/-Octopus/instructions/ROADMAP_2026-06-19_vectors.md"
    try:
        txt = open(path, encoding="utf-8").read().splitlines()
    except Exception as e:
        return f"❌ roadmap недоступен: {e}"
    heads = [l for l in txt if l.startswith("## ")][:10]
    lines = ["🧭 *Roadmap Octopus*", ""]
    for h in heads:
        name = h.replace("## ", "")
        lines.append("• " + name[:80])
    lines.append("\nПолный файл: `~/agents/-Octopus/instructions/ROADMAP_2026-06-19_vectors.md`")
    return "\n".join(lines)


def cmd_recovery(_: str) -> str:
    """Issue exactly one one-time agent recovery URL for the authorized Telegram chat."""
    return "RECOVERY_REQUIRES_CHAT_ID"


RECOVERY_USERS = {
    "octopus-operator": {"label":"Octopus Operator", "projects":["octopus"]},
    "autosklo-agent": {"label":"AutoSklo Agent", "projects":["autosklo","parent"]},
    "autohelp-agent": {"label":"AutoHelp Agent", "projects":["autohelp"]},
    "traff-agent": {"label":"Traff Agent", "projects":["traff"]},
    "shared-agent": {"label":"Shared Integrations Agent", "projects":["shared-integrations"]},
}
RECOVERY_PROJECT_LABELS = {
    "octopus":"Octopus", "autosklo":"AutoSklo", "parent":"AutoSklo Parent",
    "autohelp":"AutoHelp", "traff":"Traff", "shared-integrations":"Shared Integrations",
}

def recovery_user_markup():
    rows=[]
    for user,meta in RECOVERY_USERS.items():
        rows.append([{"text":f"👤 {meta['label']}","callback_data":f"recover_user:{user}"}])
    return {"inline_keyboard":rows}

def recovery_project_markup(user: str):
    meta=RECOVERY_USERS.get(user)
    if not meta: return recovery_user_markup()
    rows=[]
    for project in meta['projects']:
        rows.append([{"text":f"📁 {RECOVERY_PROJECT_LABELS.get(project,project)}","callback_data":f"recover_project:{user}:{project}"}])
    rows.append([{"text":"⬅️ Другой пользователь","callback_data":"recover_start"}])
    return {"inline_keyboard":rows}

def recovery_agent_message(chat_id: int, user: str, project: str) -> str:
    link=f"https://autosklo.org.ua/agent/{project}/{chat_id}"
    label=RECOVERY_PROJECT_LABELS.get(project,project)
    return (
        "Открой ссылку, дождись подтверждения в Telegram и продолжи подключение:\n\n"
        f"{link}\n\n"
        f"Проект: {label}\nПользователь SSH: {user}\n\n"
        "После подтверждения создай временную SSH-пару, передай только публичный ключ в grant endpoint, "
        "подключись по выданным реквизитам, прочитай /mnt/agents/ и AGENT_ENTRYPOINT.md проекта, затем выполни инструкции. "
        "Не передавай приватный ключ или токены."
    )

def cmd_controls(_: str) -> str:
    quiet = _run("octopus quiet status", 8)
    return "🎛 *Управление автономией*\n\n" + (quiet[:900] if quiet else "Выбери действие кнопками.")


def cmd_help_v2(_: str) -> str:
    base = (
        "🐙 *Octopus Bot — интуитивное управление*\n\n"
        "Главное меню: /menu\n"
        "AI: просто напиши вопрос или /ask <вопрос>\n"
        "⚔️ Arena.ai: /arena <вопрос> — 130+ моделей\n"
        "   /arena_model — выбрать модель\n"
        "   /arena_models — список моделей\n"
        "Экспертный режим: /expert <задача>\n\n"
        "Recovery-доступ нового агента: /recovery\n\n"
        "Быстрые команды: /ops /audio_queue /duplicates /speakers /people_graph /voice_id /speaker_assign /person_merge /person_rename /roadmap /controls /health /swarm /registry /ai_health"
    )
    if os.environ.get("OCTOPUS_TGBOT_QUANT", "0") == "1":
        base += chr(10) + chr(10) + "📊 Quant (paper): /quant /digest /ab /basket /scoreboard"
    return base



def audio_queue_markup():
    rows = [[{"text":"⬅️ Меню", "callback_data":"menu"}, {"text":"🔄 Обновить", "callback_data":"audio"}]]
    out = _run("su - postgres -c \"psql -d ingest_db -Atc \\\"select upload_id,status from transcriptions where status in ('failed','corrupt','transcribed') order by updated_at desc limit 6;\\\"\"", 8)
    btns=[]
    for line in out.splitlines():
        if '|' not in line: continue
        uid, st = line.split('|',1)
        label = ("🔁" if st != 'corrupt' else "⚠️") + f" retry #{uid}"
        btns.append({"text": label, "callback_data": f"retry:{uid}:{'force' if st=='corrupt' else 'normal'}"})
    for i in range(0, len(btns), 2):
        rows.append(btns[i:i+2])
    return {"inline_keyboard": rows}


def speakers_markup():
    rows = [[{"text":"⬅️ Меню", "callback_data":"menu"}, {"text":"🔄 Обновить", "callback_data":"speakers"}]]
    out = _run("su - postgres -c \"psql -d ingest_db -Atc \\\"select recording_id,speaker from recording_speakers where person_id is null order by recording_id desc, speech_sec desc limit 8;\\\"\"", 8)
    btns=[]
    for line in out.splitlines():
        if '|' not in line: continue
        rec, sp = line.split('|',1)
        btns.append({"text": f"👤 {rec}/{sp}", "callback_data": f"speaker:{rec}:{sp}"})
    for i in range(0, len(btns), 2): rows.append(btns[i:i+2])
    return {"inline_keyboard": rows}


def speaker_people_markup(rec: str, sp: str):
    rows=[]
    out = _run("su - postgres -c \"psql -d ingest_db -Atc \\\"select id,name from people order by mention_count desc,name limit 10;\\\"\"", 8)
    btns=[]
    for line in out.splitlines():
        if '|' not in line: continue
        pid, name = line.split('|',1)
        btns.append({"text": f"{name[:22]}", "callback_data": f"assignsp:{rec}:{sp}:{pid}"})
    for i in range(0, len(btns), 2): rows.append(btns[i:i+2])
    rows.append([{"text":"⬅️ Голоса", "callback_data":"speakers"}, {"text":"✍️ Командой", "callback_data":"speaker_help"}])
    return {"inline_keyboard": rows}


def people_graph_markup():
    rows = [[{"text":"⬅️ Меню", "callback_data":"menu"}, {"text":"🔄 Обновить", "callback_data":"people_graph"}]]
    out = _run("su - postgres -c \"psql -d ingest_db -Atc \\\"select id,name from people order by mention_count desc,name limit 10;\\\"\"", 8)
    btns=[]
    for line in out.splitlines():
        if '|' not in line: continue
        pid,name=line.split('|',1)
        btns.append({"text": f"👤 {name[:20]}", "callback_data": f"person:{pid}"})
    for i in range(0,len(btns),2): rows.append(btns[i:i+2])
    return {"inline_keyboard": rows}


def person_actions_markup(pid: str):
    rows=[]
    out = _run("su - postgres -c \"psql -d ingest_db -Atc \\\"select id,name from people where id<>%s order by mention_count desc,name limit 8;\\\"\"" % pid, 8)
    btns=[]
    for line in out.splitlines():
        if '|' not in line: continue
        other,name=line.split('|',1)
        btns.append({"text": f"🔀 merge→ {name[:18]}", "callback_data": f"mergeconfirm:{pid}:{other}"})
    for i in range(0,len(btns),1): rows.append(btns[i:i+1])
    rows.append([{"text":"✏️ Rename help", "callback_data": f"renamehelp:{pid}"}])
    rows.append([{"text":"⬅️ Граф", "callback_data":"people_graph"}, {"text":"⬅️ Меню", "callback_data":"menu"}])
    return {"inline_keyboard": rows}


def voice_id_markup():
    rows = [[{"text":"⬅️ Меню", "callback_data":"menu"}, {"text":"🔄 Обновить", "callback_data":"voice_id"}]]
    out = _pg("select recording_id,speaker,round(score::numeric,3),status from speaker_voice_matches where status<>'applied' order by score desc,updated_at desc limit 8;")
    btns=[]
    for line in out.splitlines():
        if '|' not in line: continue
        rec, sp, score, st = line.split('|',3)
        try: sc=float(score)
        except: sc=0.0
        icon = '✅' if sc>=0.82 else ('🟡' if sc>=0.70 else '⚪')
        btns.append({"text": f"{icon} apply {rec}/{sp} {score}", "callback_data": f"applyvoice:{rec}:{sp}"})
    for i in range(0, len(btns), 1): rows.append(btns[i:i+1])
    return {"inline_keyboard": rows}

def main_menu_markup():
    return {"inline_keyboard": [
        [{"text":"🐙 AIOS Control", "callback_data":"aios_help"}, {"text":"⚔️ Arena.ai", "callback_data":"arena_help"}],
        [{"text":"🌐 3-Node Cluster", "callback_data":"cluster"}, {"text":"🛡 Vault OCI", "callback_data":"vault"}],
        [{"text":"📚 Навыки (51)", "callback_data":"skills_help"}, {"text":"⚖️ Дебаты", "callback_data":"debate_help"}],
        [{"text":"🩺 SLO 15/15", "callback_data":"slo"}, {"text":"🎛 Инструменты", "callback_data":"tools"}],
        [{"text":"📊 Состояние /ops", "callback_data":"ops"}, {"text":"🎙 Аудио", "callback_data":"audio"}],
        [{"text":"🐙 Рой", "callback_data":"swarm"}, {"text":"🏥 Health", "callback_data":"health"}],
        [{"text":"🧭 Roadmap", "callback_data":"roadmap"}, {"text":"🧠 AI", "callback_data":"ai"}],
        [{"text":"🎛 Управление", "callback_data":"controls"}, {"text":"🔄 Обновить", "callback_data":"ops"}],
    ]}


def back_markup(section="ops"):
    return {"inline_keyboard": [[{"text":"⬅️ Меню", "callback_data":"menu"}, {"text":"🔄 Обновить", "callback_data":section}]]}


def controls_markup():
    return {"inline_keyboard": [
        [{"text":"⏸ Pause", "callback_data":"ctl:pause"}, {"text":"▶️ Resume", "callback_data":"ctl:resume"}],
        [{"text":"🧊 Freeze", "callback_data":"ctl:freeze"}, {"text":"♨️ Thaw", "callback_data":"ctl:thaw"}],
        [{"text":"🌙 Quiet status", "callback_data":"ctl:quiet status"}, {"text":"🚨 Panic…", "callback_data":"panic_confirm"}],
        [{"text":"⬅️ Меню", "callback_data":"menu"}],
    ]}


async def answer_callback(callback_id: str, text: str = "") -> None:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    try:
        r = await _client.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text[:180], "show_alert": False})
        if not (r.status_code == 200 and r.json().get("ok") is True):
            log.warning("Callback answer rejected status=%s body=%s", r.status_code, r.text[:300])
    except Exception as e:
        log.warning("Callback answer error: %s", e)


async def tg_edit(chat_id: int, message_id: int, text: str, reply_markup=None) -> None:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    text = str(text or "")
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text[:3900], "parse_mode": "Markdown"}
    if reply_markup is not None: payload["reply_markup"] = reply_markup
    try:
        r = await _client.post(f"{TG_API}/editMessageText", json=payload)
        if r.status_code == 200 and (r.json().get("ok") is True):
            return
        # Часто Telegram отвергает Markdown из-за `_`, `*`, длинных логов; fallback plain text.
        payload.pop("parse_mode", None)
        r2 = await _client.post(f"{TG_API}/editMessageText", json=payload)
        if r2.status_code == 200 and (r2.json().get("ok") is True):
            return
        await tg_send(chat_id, text, reply_markup=reply_markup)
    except Exception as e:
        log.warning("Edit error: %s", e)
        await tg_send(chat_id, text, reply_markup=reply_markup)


async def handle_callback(cb: dict) -> None:
    data = cb.get("data", "")
    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    user_id = cb.get("from", {}).get("id")
    if not chat_id or not message_id: return
    if not OPEN_ACCESS and ALLOW_IDS and user_id not in ALLOW_IDS and chat_id not in ALLOW_IDS:
        return
    markup = back_markup(data)
    if data in {"menu", "ops", "audio", "roadmap", "duplicates", "speakers", "people_graph", "voice_id", "swarm", "health", "ai", "controls", "arena_help", "aios_help", "debate_help", "skills_help", "cluster", "vault", "slo", "tools"}:
        await answer_callback(cb.get("id", ""), "Выполняю…")
        text, markup = await render_callback(data)
        await tg_edit(chat_id, message_id, text or "_пусто_", reply_markup=markup)
        return
    if data == "recover_start":
        await answer_callback(cb.get("id", ""), "Выберите пользователя")
        await tg_edit(chat_id,message_id,"🔐 *Recovery: выберите пользователя доступа*",reply_markup=recovery_user_markup())
        return
    if data.startswith("recover_user:"):
        user=data.split(":",1)[1]
        if user not in RECOVERY_USERS:
            await answer_callback(cb.get("id", ""), "Неизвестный пользователь")
            return
        await answer_callback(cb.get("id", ""), "Теперь выберите проект")
        await tg_edit(chat_id,message_id,f"👤 Пользователь: `{user}`\n\nВыберите проект:",reply_markup=recovery_project_markup(user))
        return
    if data.startswith("recover_project:"):
        parts=data.split(":",2)
        if len(parts)!=3:
            await answer_callback(cb.get("id", ""), "Некорректный выбор")
            return
        _,user,project=parts
        allowed=RECOVERY_USERS.get(user,{}).get("projects",[])
        if project not in allowed:
            await answer_callback(cb.get("id", ""), "Проект не соответствует пользователю")
            return
        await answer_callback(cb.get("id", ""), "Готово — сообщение можно копировать")
        text="✅ *Готовый текст для агента*\n\n"+recovery_agent_message(chat_id,user,project)
        await tg_edit(chat_id,message_id,text,reply_markup={"inline_keyboard":[[{"text":"🔄 Создать другую ссылку","callback_data":"recover_start"}]]})
        return
    if data.startswith("recovery_approve:") or data.startswith("recovery_deny:"):
        action, rid = data.split(":",1)
        log.info("recovery callback action=%s request_id=%s chat_id=%s user_id=%s",action,rid,chat_id,user_id)
        wanted='approved' if action=='recovery_approve' else 'denied'
        try:
            con=sqlite3.connect('/var/lib/octopus-agent-recovery/recovery.db',timeout=5)
            cur=con.execute("UPDATE approval_requests SET status=?,decided=?,activation_notified=1 WHERE request_id=? AND chat_id=? AND status='pending' AND expires>=?",(wanted,int(time.time()),rid,chat_id,int(time.time())))
            con.commit(); changed=cur.rowcount; con.close()
        except Exception as e:
            log.exception('recovery decision failed'); changed=0
        if changed:
            text='✅ Подключение Octopus подтверждено. Агент может продолжить.' if wanted=='approved' else '🚫 Подключение Octopus отклонено.'
            await tg_edit(chat_id,message_id,text,reply_markup={'inline_keyboard':[]})
            await answer_callback(cb.get('id',''),'Подтверждено' if wanted=='approved' else 'Отклонено')
        else:
            await answer_callback(cb.get('id',''),'Запрос уже обработан или истёк')
        return
    if data.startswith("person:"):
        _, pid = data.split(":", 1)
        info = _pg("select id,name,mention_count,coalesce(notes,'') from people where id=%s;" % pid)
        rel = _pg("select case when person_a=%s then pb.name else pa.name end, weight from person_relations pr join people pa on pa.id=pr.person_a join people pb on pb.id=pr.person_b where person_a=%s or person_b=%s order by weight desc limit 8;" % (pid,pid,pid))
        rel_txt = "\n".join(["• "+x.replace("|", " · ") for x in rel.splitlines()]) if rel else "—"
        text = "👤 *Person*\n```text\n" + (info or pid)[:800] + "\n```\n*Связи:*\n" + rel_txt
        await tg_edit(chat_id, message_id, text, reply_markup=person_actions_markup(pid)); return
    if data.startswith("renamehelp:"):
        _, pid = data.split(":", 1)
        await tg_edit(chat_id, message_id, f"✏️ Rename для person `#{pid}`:\n`/person_rename {pid} Новое Имя`", reply_markup=person_actions_markup(pid)); return
    if data.startswith("mergeconfirm:"):
        _, src, dst = data.split(":", 2)
        names = _pg("select id||':'||name from people where id in (%s,%s) order by id;" % (src,dst))
        markup = {"inline_keyboard":[[{"text":"✅ Merge", "callback_data":f"mergeperson:{src}:{dst}"}], [{"text":"⬅️ Назад", "callback_data":f"person:{src}"}]]}
        await tg_edit(chat_id, message_id, f"⚠️ *Подтвердить merge*\n```text\n{names}\n```\nИсточник `#{src}` будет объединён в `#{dst}`.", reply_markup=markup); return
    if data.startswith("mergeperson:"):
        _, src, dst = data.split(":", 2)
        out = _run(f"/opt/octopus_people_tools.py merge {src!r} {dst!r}", 30)
        await tg_edit(chat_id, message_id, f"🔀 *Merge done*\n```text\n{out[:1600]}\n```", reply_markup=people_graph_markup()); return
    if data.startswith("speaker:"):
        _, rec, sp = data.split(":", 2)
        await tg_edit(chat_id, message_id, f"👥 *Назначить голос* `{rec}/{sp}`\nВыбери человека:", reply_markup=speaker_people_markup(rec, sp)); return
    if data == "speaker_help":
        await tg_edit(chat_id, message_id, "✍️ Использование:\n`/speaker_assign <recording_id> <SPK> <Имя>`\n`/person_rename <old> <new>`\n`/person_merge <from> <to>`", reply_markup=speakers_markup()); return
    if data.startswith("assignsp:"):
        _, rec, sp, pid = data.split(":", 3)
        name = _run("su - postgres -c \"psql -d ingest_db -Atc \\\"select name from people where id=%s;\\\"\"" % pid, 8).strip() or pid
        out = _run(f"/opt/octopus_speaker_map.py assign {rec} {sp} {name!r}", 15)
        await tg_edit(chat_id, message_id, f"✅ *Speaker assigned* `{rec}/{sp}` → *{name}*\n```text\n{out[:1200]}\n```", reply_markup=speakers_markup()); return
    if data.startswith("applyvoice:"):
        _, rec, sp = data.split(":", 2)
        name = _pg("select p.name from speaker_voice_matches svm join people p on p.id=svm.matched_person_id where svm.recording_id=%s and svm.speaker='%s';" % (rec, sp.replace("'", "''"))).strip()
        if not name:
            await tg_edit(chat_id, message_id, f"❌ Voice match not found for `{rec}/{sp}`", reply_markup=voice_id_markup()); return
        out = _run(f"/opt/octopus_speaker_map.py assign {rec} {sp} {name!r} voice-id-tg", 20)
        _pg("update speaker_voice_matches set status='applied', updated_at=now() where recording_id=%s and speaker='%s';" % (rec, sp.replace("'", "''")))
        await tg_edit(chat_id, message_id, f"🎤✅ *Voice ID applied* `{rec}/{sp}` → *{name}*\n```text\n{out[:1200]}\n```", reply_markup=voice_id_markup()); return
    if data.startswith("retry:"):
        _, uid, mode = data.split(":", 2)
        force = (mode == "force")
        if force:
            out = _run("su - postgres -c \"psql -d ingest_db -c \\\"update transcriptions set status='failed', error='manual_force_retry_from_tg', updated_at=now()-interval '2 hours' where upload_id=%s;\\\"\"" % uid, 10)
        else:
            out = _run("su - postgres -c \"psql -d ingest_db -c \\\"update transcriptions set status='failed', error='manual_retry_from_tg', updated_at=now()-interval '2 hours' where upload_id=%s and status <> 'corrupt';\\\"\"" % uid, 10)
        await tg_edit(chat_id, message_id, f"🔁 *Retry queued* `#{uid}`\n```text\n{out[:1200]}\n```", reply_markup=audio_queue_markup()); return
    if data.startswith("ctl:"):
        action = data.split(":",1)[1]
        if action not in {"pause","resume","freeze","thaw","quiet status","panic"}:
            out = "unknown action"
        else:
            out = _run("octopus " + action, 30 if action == "panic" else 20)
        await tg_edit(chat_id, message_id, f"🎛 *Control:* `{action}`\n```text\n{out[:2500]}\n```", reply_markup=controls_markup()); return
    if data == "panic_confirm":
        await tg_edit(chat_id, message_id, "🚨 *PANIC остановит автономию и воркеры.*\nПодтвердить?", reply_markup={"inline_keyboard":[[{"text":"✅ Да, panic", "callback_data":"ctl:panic"}], [{"text":"⬅️ Назад", "callback_data":"controls"}]]}); return
    if data == "ctl:panic":
        out = _run("octopus panic", 30)
        await tg_edit(chat_id, message_id, f"🚨 *PANIC выполнен*\n```text\n{out[:2500]}\n```", reply_markup=controls_markup()); return


async def call_command(fn, text: str, timeout: int = 25) -> str:
    """Run sync/async command without blocking Telegram polling."""
    try:
        if inspect.iscoroutinefunction(fn):
            return str(await asyncio.wait_for(fn(text), timeout=timeout))
        result = await asyncio.wait_for(asyncio.to_thread(fn, text), timeout=timeout)
        if inspect.isawaitable(result):
            result = await asyncio.wait_for(result, timeout=timeout)
        return str(result)
    except asyncio.TimeoutError:
        return f"⏱ Команда превысила таймаут {timeout}s. Попробуй позже или сузить запрос."
    except Exception as e:
        log.exception("command failed")
        return f"❌ Ошибка команды: {type(e).__name__}: {str(e)[:500]}"


async def render_callback(data: str) -> tuple[str, dict | None]:
    """Fast callback renderer for common buttons; heavy sync functions run in a thread."""
    if data == "menu":
        return "🐙 *Octopus Центр управления*\n\nВыбери раздел — кнопки отвечают сразу, тяжёлые проверки запускаются bounded.", main_menu_markup()
    if data == "aios_help":
        return ("🐙 *AIOS Autonomous Kernel*\n\n"
            "AIOS распределяет автономные цели по воркерам кластера.\n\n"
            "Команды:\n"
            "`/aios <цель>` — запуск задачи в AIOS\n"
            "`/debate <тема>` — многоагентный трибунал\n"
            "`/cluster` — статус 3-х нод кластера\n"
            "`/vault` — снапшоты OCI Vault\n"
            "`/skills <запрос>` — векторный поиск знаний\n"
            "`/slo` — отчет SLO 15/15\n"
            "`/tools` — динамические песочницы", main_menu_markup())
    if data == "debate_help":
        return ("⚖️ *AIOS Multi-Agent Tribunal*\n\n"
            "Запускает 3-агентный консенсус (Тезис, Антитезис, Судья).\n\n"
            "Использование: `/debate <тема или вопрос>`", main_menu_markup())
    if data == "skills_help":
        return ("📚 *AIOS Skills Memory Fabric*\n\n"
            "51 кристаллизованный навык с векторным поиском nomic-embed-text.\n\n"
            "Использование: `/skills <запрос>`", main_menu_markup())
    if data == "arena_help":
        return ("⚔️ *Arena.ai — 130+ LLM моделей*\n\n"
            "Отправь текст — он уйдёт в Arena!\n\n"
            "`/arena <вопрос>` — спросить Arena\n"
            "`/arena_model` — текущая модель\n"
            "`/arena_model <name>` — сменить модель\n"
            "`/arena_models [фильтр]` — список моделей", main_menu_markup())
    renderers = {
        "ops": (cmd_ops, main_menu_markup),
        "audio": (cmd_audio_queue, audio_queue_markup),
        "roadmap": (cmd_roadmap, lambda: back_markup("roadmap")),
        "duplicates": (cmd_duplicates, lambda: back_markup("duplicates")),
        "speakers": (cmd_speakers, speakers_markup),
        "people_graph": (cmd_people_graph, people_graph_markup),
        "voice_id": (cmd_voice_id, voice_id_markup),
        "swarm": (cmd_swarm, lambda: back_markup("swarm")),
        "health": (cmd_health, lambda: back_markup("health")),
        "ai": (cmd_ai_health, lambda: back_markup("ai")),
        "controls": (cmd_controls, controls_markup),
        "cluster": (cmd_cluster, main_menu_markup),
        "vault": (cmd_vault, main_menu_markup),
        "slo": (cmd_slo, main_menu_markup),
        "tools": (cmd_tools, main_menu_markup),
    }
    fn_pair = renderers.get(data)
    if not fn_pair:
        return "", None
    fn, markup_fn = fn_pair
    text = await call_command(fn, "", timeout=55 if data in {"ops"} else 25)
    try:
        markup = await asyncio.to_thread(markup_fn)
    except Exception:
        markup = back_markup(data if data != "menu" else "ops")
    return text, markup


async def handle_recovery_approval_message(msg: dict) -> bool:
    """Handle approval commands before the generic command router."""
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()
    token = text.split(None, 1)[0].split("@", 1)[0] if text else ""
    m = re.match(r"^/approve_?agent_?([A-Za-z0-9_-]{6,40})$", token, re.IGNORECASE)
    if not m:
        return False
    rid = m.group(1)
    try:
        now = int(time.time())
        con = sqlite3.connect('/var/lib/octopus-agent-recovery/recovery.db', timeout=5)
        row = con.execute("SELECT user_agent,status,expires FROM approval_requests WHERE lower(request_id)=lower(?) AND chat_id=?", (rid, chat_id)).fetchone()
        changed = 0; agent_name = "Agent"
        if row:
            ua = (row[0] or "").lower()
            if "chatgpt" in ua or "openai" in ua: agent_name = "ChatGPT"
            elif "arena" in ua: agent_name = "Arena.ai"
            elif "claude" in ua or "anthropic" in ua: agent_name = "Claude"
            elif "gemini" in ua or "google" in ua: agent_name = "Gemini"
            elif "chrome" in ua or "mozilla" in ua: agent_name = "Browser Agent"
            cur = con.execute("UPDATE approval_requests SET status='approved',decided=? WHERE lower(request_id)=lower(?) AND chat_id=? AND status='pending' AND expires>=?", (now, rid, chat_id, now))
            changed = cur.rowcount
        con.commit(); con.close()
        log.info("recovery approval command request_id=%s chat_id=%s changed=%s", rid, chat_id, changed)
    except Exception:
        log.exception("recovery approval command failed")
        changed = 0; agent_name = "Agent"
    if changed:
        await tg_send(chat_id, f"✅ Агент {agent_name} авторизован!")
    else:
        await tg_send(chat_id, "⌛ Запрос уже подтверждён, использован или истёк.")
    return True

async def handle_message(msg: dict) -> None:
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id: return
    if not OPEN_ACCESS and ALLOW_IDS and chat_id not in ALLOW_IDS: return

    text = msg.get("text", "").strip()
    voice = msg.get("voice") or msg.get("audio")
    if voice and not text:
        file_id = voice.get("file_id")
        await tg_send(chat_id, "🎙️ _Слушаю и транскрибирую голосовое сообщение через Groq Whisper Turbo..._")
        transcribed = await transcribe_voice_groq(file_id)
        if transcribed:
            await tg_send(chat_id, f"🗣️ *Распознано:* _{transcribed}_")
            text = transcribed
        else:
            await tg_send(chat_id, "❌ Не удалось распознать голосовое сообщение.")
            return
    photo = msg.get("photo")
    if photo and not text:
        file_id = photo[-1].get("file_id")
        caption = msg.get("caption", "").strip() or "Опиши подробно, что изображено на картинке, извлеки текст (OCR) и ключевые сущности."
        await tg_send(chat_id, "👁️ _Анализирую изображение через AI Vision & OCR Pipeline..._")
        
        try:
            from aios.cognition.vision_pipeline import vision_pipeline
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(f"{TG_API}/getFile?file_id={file_id}")
                if res.status_code == 200:
                    file_path = res.json().get("result", {}).get("file_path")
                    if file_path:
                        img_bytes = (await client.get(f"https://api.telegram.org/file/bot{TG_TOKEN}/{file_path}")).content
                        v_res = await vision_pipeline.analyze_image_bytes(img_bytes, prompt=caption)
                        if v_res.get("ok"):
                            await tg_send(chat_id, f"👁️ *AI Vision Анализ ({v_res.get('provider')}):*\n\n{v_res.get('analysis')}")
                            return
        except Exception as e:
            log.warning("Vision handler error: %s", e)
        await tg_send(chat_id, "❌ Не удалось проанализировать изображение.")
        return

    if not text: return

    if await handle_recovery_approval_message(msg):
        return

    if text.startswith("/"):
        parts = text.split(None, 1)
        raw_cmd = parts[0].split("@")[0]
        cmd = raw_cmd.lower()
        rest = parts[1] if len(parts) > 1 else ""
    else:
        cmd, rest = "/ask", text

    ASYNC_CMDS = {"/ask", "/say", "/expert", "/arena", "/arena_model", "/arena_models", "/aios", "/debate", "/cluster", "/vault", "/skills", "/slo", "/tools", "/tool", "/keys", "/benchmark", "/route"}

    if cmd in {"/recover", "/recovery"}:
        await tg_send(chat_id,"🔐 *Recovery: выберите пользователя доступа*",reply_markup=recovery_user_markup())
        return

    if cmd in {"/menu", "/start"}:
        await tg_send(chat_id, "🐙 *Octopus Центр управления*\n\nВыбери раздел. Для полного статуса нажми 📊 Состояние или /ops.", reply_markup=main_menu_markup())
        return

    if cmd in ASYNC_CMDS:
        await tg_send(chat_id, "⏳ _Думаю..._")
        if cmd == "/ask":
            reply = await cmd_ask(rest)
        elif cmd == "/expert":
            reply = await cmd_expert(rest)
        elif cmd == "/say":
            reply = "🔊 _говорю..._"
        elif cmd == "/arena":
            await tg_send(chat_id, "⚔️ _Arena думает... (~30с)_")
            reply = await cmd_arena(rest, chat_id=chat_id)
        elif cmd == "/arena_model":
            reply = await cmd_arena_model(rest, chat_id=chat_id)
        elif cmd == "/arena_models":
            reply = await cmd_arena_models(rest)
        elif cmd == "/aios":
            reply = await cmd_aios(rest)
        elif cmd == "/keys":
            reply = await cmd_keys(rest)
        elif cmd == "/benchmark":
            reply = await cmd_benchmark(rest)
        elif cmd == "/route":
            reply = await cmd_route(rest)
        elif cmd == "/debate":
            reply = await cmd_debate(rest)
        elif cmd == "/cluster":
            reply = await cmd_cluster(rest)
        elif cmd == "/vault":
            reply = await cmd_vault(rest)
        elif cmd == "/skills":
            reply = await cmd_skills(rest)
        elif cmd == "/slo":
            reply = await cmd_slo(rest)
        elif cmd == "/tools":
            reply = await cmd_tools(rest)
        elif cmd == "/tool":
            reply = await cmd_tool(rest)
        else:
            reply = "Unknown"
    else:
        SYNC_MAP = {
            "/start": cmd_help_v2,
            "/help":  cmd_help_v2,
            "/swarm": cmd_swarm,
            "/registry": cmd_registry,
            "/nodes": cmd_nodes,
            "/status": cmd_status,
            "/peers": cmd_peers,
            "/health": cmd_health,
            "/ai_health": cmd_ai_health,
            "/ops": cmd_ops,
            "/audio_queue": cmd_audio_queue,
            "/audio_q": cmd_audio_queue,
            "/audio": cmd_audio_queue,
            "/roadmap": cmd_roadmap,
            "/controls": cmd_controls,
            "/duplicates": cmd_duplicates,
            "/speakers": cmd_speakers,
            "/people_graph": cmd_people_graph,
            "/voice_id": cmd_voice_id,
            "/speaker_assign": cmd_speaker_assign,
            "/retry": cmd_retry,
            "/person_merge": cmd_person_merge,
            "/person_rename": cmd_person_rename,
        }
        if os.environ.get("OCTOPUS_TGBOT_QUANT", "0") == "1":
            from swarm.tgbot import bot_commands as _quant

            SYNC_MAP.update(
                {
                    "/quant": _quant.cmd_quant_text,
                    "/digest": _quant.cmd_digest_text,
                    "/ab": _quant.cmd_ab_text,
                    "/basket": _quant.cmd_basket_text,
                    "/scoreboard": _quant.cmd_scoreboard_text,
                }
            )
        fn = SYNC_MAP.get(cmd)
        if fn:
            reply = await call_command(fn, rest, timeout=60 if cmd in {"/ops", "/audio_queue", "/audio", "/audio_q"} else 25)
        else:
            if cmd.startswith(("/approveagent", "/approve_agent")):
                return
            reply = f"Неизвестная команда: `{cmd}`\nПопробуй /help"

    await tg_send(chat_id, reply)


async def tg_send(chat_id: int, text: str, reply_markup=None):
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    text = str(text or "")
    chunks = [text[i:i+3900] for i in range(0, max(len(text), 1), 3900)] or ["_"]
    first_message_id = None
    for i, chunk in enumerate(chunks[:4]):
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"}
        if reply_markup and i == 0:
            payload["reply_markup"] = reply_markup
        try:
            r = await _client.post(f"{TG_API}/sendMessage", json=payload)
            if r.status_code == 200 and (r.json().get("ok") is True):
                if first_message_id is None:
                    first_message_id = (r.json().get("result") or {}).get("message_id")
                continue
            payload.pop("parse_mode", None)
            r2 = await _client.post(f"{TG_API}/sendMessage", json=payload)
            if not (r2.status_code == 200 and (r2.json().get("ok") is True)):
                log.warning("Send rejected: %s", r2.text[:300])
            elif first_message_id is None:
                first_message_id = (r2.json().get("result") or {}).get("message_id")
        except Exception as e:
            log.warning("Send error: %s", e)
    return first_message_id


async def recovery_approval_notifier() -> None:
    while True:
        try:
            now=int(time.time()); con=sqlite3.connect('/var/lib/octopus-agent-recovery/recovery.db',timeout=5)
            rows=con.execute("SELECT request_id,chat_id,peer,user_agent,created FROM approval_requests WHERE status='pending' AND notified=0 AND expires>=? ORDER BY created LIMIT 20",(now,)).fetchall()
            for rid,chat_id,peer,ua,created in rows:
                if ALLOW_IDS and chat_id not in ALLOW_IDS:
                    con.execute("UPDATE approval_requests SET status='denied',decided=?,notified=1 WHERE request_id=?",(now,rid)); continue
                expires=con.execute('SELECT expires FROM approval_requests WHERE request_id=?',(rid,)).fetchone()[0]
                key=open('/var/lib/octopus-agent-recovery/approval.key','rb').read().strip()
                token=hmac.new(key,f'{rid}:{chat_id}:{expires}'.encode(),hashlib.sha256).hexdigest()[:32]
                approve_url=f'https://autosklo.org.ua/agent/approve/{rid}/{token}'
                message_id = await tg_send(chat_id,f"🔐 *Запрос подключения к Octopus*\n\nIP: `{peer}`\nАгент: `{(ua or 'не указан')[:120]}`\nЗапрос: `{rid}`\n\nДля подтверждения откройте одноразовую ссылку:\n\n{approve_url}\n\nПосле активации ссылка перестанет работать.")
                con.execute('UPDATE approval_requests SET notified=1,telegram_message_id=? WHERE request_id=?',(message_id,rid))
            con.commit()
            approved=con.execute("SELECT request_id,chat_id,telegram_message_id FROM approval_requests WHERE status='approved' AND notified=1 AND activation_notified=0 AND telegram_message_id IS NOT NULL ORDER BY decided LIMIT 20").fetchall()
            for rid,chat_id,message_id in approved:
                await tg_edit(chat_id,message_id,"✅ Подключение успешно активировано. Агент может продолжить.",reply_markup={'inline_keyboard':[]})
                con.execute('UPDATE approval_requests SET activation_notified=1 WHERE request_id=?',(rid,))
            con.commit(); con.close()
        except Exception as e:
            log.warning('recovery notifier error: %s',e)
        await asyncio.sleep(2)

async def poll() -> None:
    global _offset
    log.info("Polling started | allowlist=%s open=%s", sorted(ALLOW_IDS), OPEN_ACCESS)
    async with httpx.AsyncClient(timeout=40.0) as client:
        while True:
            try:
                r = await client.post(f"{TG_API}/getUpdates", json={
                    "offset": _offset,
                    "timeout": 30,
                    "allowed_updates": ["message", "callback_query"],
                })
                updates = r.json().get("result", [])
                for upd in updates:
                    _offset = upd["update_id"] + 1
                    msg = upd.get("message")
                    cb = upd.get("callback_query")
                    if msg:
                        text=(msg.get("text") or "").strip()
                        if re.match(r"^/approve_?agent_?", text.split(None,1)[0].split("@",1)[0] if text else "", re.IGNORECASE):
                            asyncio.create_task(handle_recovery_approval_message(msg))
                        else:
                            asyncio.create_task(handle_message(msg))
                    if cb:
                        asyncio.create_task(handle_callback(cb))
            except Exception as e:
                log.warning("Poll error: %s", e)
                await asyncio.sleep(5)


async def main():
    _start_healthz(port=9715, name='tg-bot')
    if not TG_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set")
        return
    asyncio.create_task(recovery_approval_notifier())
    await poll()


if __name__ == "__main__":
    asyncio.run(main())
