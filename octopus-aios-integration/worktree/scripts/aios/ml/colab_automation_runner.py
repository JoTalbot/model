#!/usr/bin/env python3
"""
AIOS Google Colab Automated Runner & Activity Keeper (CDP 9222)
Запускает кодинг-модель в Google Colab через ваш текущий авторизованный браузер Chrome (CDP 9222),
извлекает публичный URL туннеля и поддерживает постоянную активность страницы,
чтобы сессия Colab не отключалась!
"""

import asyncio
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import suppress
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

os.environ["DISPLAY"] = os.environ.get("DISPLAY", ":1")


# Ноутбуки Colab-фермы по типу сервиса (для авто-запуска через COLAB_SERVICE_KIND)
NOTEBOOK_MAP = {
    "llm":        "AIOS_Google_Colab_LLM_Coding.ipynb",
    "whisper":    "AIOS_Google_Colab_Whisper_Transcriber.ipynb",
    "quant_ml":   "AIOS_Colab_Quant_ML_Training.ipynb",
    "rl":         "AIOS_Colab_Quant_RL_Training.ipynb",
    "clustering": "AIOS_Colab_Quant_Clustering.ipynb",
    "lora":       "AIOS_Colab_LoRA_FineTune.ipynb",
    "embeddings": "AIOS_Colab_Embeddings_Build.ipynb",
    "scraper":    "AIOS_Colab_Scraper_Farm.ipynb",
    "gguf":       "AIOS_Colab_GGUF_Quantize.ipynb",
}
GITHUB_NB = "https://colab.research.google.com/github/JoTalbot/AIOS/blob/main/docs/"


def _pick_notebook() -> str:
    """Определить URL ноутбука по env-переменным / аргументам."""
    # 1) явный URL
    env_url = os.getenv("COLAB_NOTEBOOK_URL", "").strip()
    if env_url:
        return env_url
    # 2) локальный файл (если указан COLAB_NOTEBOOK_FILE)
    local_file = os.getenv("COLAB_NOTEBOOK_FILE", "").strip()
    if local_file and Path(local_file).exists():
        return f"file://{Path(local_file).resolve()}"
    # 3) по типу сервиса
    kind = os.getenv("COLAB_SERVICE_KIND", "")
    if kind in NOTEBOOK_MAP:
        return GITHUB_NB + NOTEBOOK_MAP[kind]
    # 4) fallback: whisper/llm по аргументам
    return (GITHUB_NB + "AIOS_Google_Colab_Whisper_Transcriber.ipynb"
            if "whisper" in sys.argv else GITHUB_NB + "AIOS_Google_Colab_LLM_Coding.ipynb")


COLAB_KEYS_FILE = REPO_ROOT / "data" / ".llm_keys.json"
COLAB_ENV_FILE = REPO_ROOT / ".env"
COLAB_KEEPER_ENV_FILE = REPO_ROOT / "data" / ".colab_llm.env"
COLAB_MODEL = "colab/qwen2.5-coder"
_TUNNEL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com/v1")
_ENDPOINT_MARKER_PATTERN = re.compile(r"COLAB_LLM_URL=(https://[^\s<>\"']+/v1)")


def _load_colab_runtime_config() -> dict:
    try:
        data = json.loads(COLAB_KEYS_FILE.read_text(encoding="utf-8"))
        primary = data.get("colab_llm", {})
        node_id = os.getenv("COLAB_NODE_ID", "primary").strip() or "primary"
        nodes = data.get("colab_llm_nodes", [])
        if isinstance(nodes, list):
            for node in nodes:
                if isinstance(node, dict) and str(node.get("node_id", "")) == node_id:
                    return node
        if node_id == "primary" and isinstance(primary, dict):
            return primary
        return {}
    except (OSError, ValueError):
        return {}


def _probe_colab_config(config: dict, *, timeout: float = 12) -> bool:
    """Cheap authenticated readiness check used before deciding to rerun cells."""
    base_url = str(config.get("base_url", "")).strip().rstrip("/")
    api_key = str(config.get("api_key", "")).strip()
    model = str(config.get("model", COLAB_MODEL)).strip() or COLAB_MODEL
    if not base_url or not api_key or config.get("enabled", True) is False:
        return False
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    try:
        request = urllib.request.Request(
            base_url + "/models",
            headers={"Authorization": "Bearer " + api_key, "User-Agent": "AIOS-Colab-Keeper/2.0"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
        return model in {
            item.get("id") for item in payload.get("data", []) if isinstance(item, dict)
        }
    except Exception:
        return False


def _healthy_registered_colab() -> dict:
    if os.getenv("COLAB_REUSE_HEALTHY_ENDPOINT", "1").strip().lower() in ("0", "false", "no", "off"):
        return {}
    config = _load_colab_runtime_config()
    return config if _probe_colab_config(config) else {}


def _extract_endpoint_urls(output_text: str) -> list[str]:
    """Extract only explicit notebook endpoint markers (quick tunnel or Tailscale)."""
    marked = _ENDPOINT_MARKER_PATTERN.findall(output_text or "")
    legacy = _TUNNEL_PATTERN.findall(output_text or "")
    return list(dict.fromkeys(marked + legacy))


def _configured_tunnel_provider() -> str:
    requested = os.getenv("COLAB_TUNNEL_PROVIDER", "auto").strip().lower()
    if requested == "auto":
        has_tailscale = bool(
            os.getenv("TAILSCALE_AUTH_KEY", "").strip()
            and os.getenv("COLAB_LLM_PUBLIC_URL", "").strip()
        )
        return "tailscale" if has_tailscale else "quick"
    if requested not in ("tailscale", "quick"):
        raise RuntimeError("COLAB_TUNNEL_PROVIDER must be auto, tailscale or quick")
    return requested


def _select_fresh_tunnel(
    urls: list[str], old_urls: set[str], output_was_cleared: bool
) -> str:
    """Reject stale notebook output left by an earlier Run all generation."""
    candidates = [url for url in urls if output_was_cleared or url not in old_urls]
    return candidates[-1] if candidates else ""


def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _update_env_values(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    result: list[str] = []
    for line in lines:
        key = line.partition("=")[0] if "=" in line else ""
        if key in remaining:
            result.append(f"{key}={remaining.pop(key)}")
        else:
            result.append(line)
    result.extend(f"{key}={value}" for key, value in remaining.items())
    _atomic_write(path, "\n".join(result) + "\n")


def _remove_env_keys(path: Path, keys: set[str]) -> None:
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.partition("=")[0] not in keys]
    _atomic_write(path, "\n".join(kept) + ("\n" if kept else ""))


def _rotate_colab_api_key() -> str:
    """Create a short-lived recovery generation key without logging its value."""
    current = os.getenv("COLAB_LLM_API_KEY", "").strip()
    enabled = os.getenv("COLAB_ROTATE_KEY_ON_RECOVERY", "1").strip().lower() not in (
        "0", "false", "no", "off"
    )
    if not enabled and current:
        return current
    new_key = secrets.token_urlsafe(36)
    os.environ["COLAB_LLM_API_KEY"] = new_key
    credential_mode = os.getenv("AIOS_SYSTEMD_CREDENTIALS", "0").lower() in (
        "1", "true", "yes", "on"
    )
    if credential_mode:
        source_dir = Path(os.getenv("OCTOPUS_CREDENTIAL_SOURCE_DIR",
             os.getenv("AIOS_CREDENTIAL_SOURCE_DIR", "/etc/octopus/credentials")))
        _atomic_write(source_dir / "colab_llm_api_key", new_key + "\n")
        _remove_env_keys(COLAB_ENV_FILE, {"COLAB_LLM_API_KEY"})
        COLAB_KEEPER_ENV_FILE.unlink(missing_ok=True)
    else:
        _update_env_values(COLAB_ENV_FILE, {"COLAB_LLM_API_KEY": new_key})
        _atomic_write(COLAB_KEEPER_ENV_FILE, "COLAB_LLM_API_KEY=" + new_key + "\n")
    print("🔐 Bearer-ключ Colab ротирован для нового recovery generation")
    return new_key


async def _connect_runtime(page) -> bool:
    """Connect through the current Colab shadow host and report final state."""
    try:
        state = page.locator("#connect, #reconnect")
        host = page.locator("colab-connect-button")
        tip = (await state.get_attribute("tooltiptext") or "") if await state.count() else ""
        connected = bool(re.search(r"Подключено к|Connected to", tip, re.I))
        if connected:
            print("✅ Runtime Colab уже подключён")
            return True
        if await host.is_visible():
            await host.click(timeout=5000)
            print("👍 Runtime Colab подключается/переподключается")
            await asyncio.sleep(10)
            tip = (await state.get_attribute("tooltiptext") or "") if await state.count() else ""
            return bool(re.search(r"Подключено к|Connected to", tip, re.I))
    except Exception as exc:
        print(f"Connect note: {type(exc).__name__}")
    return False


async def _output_text(page) -> str:
    """Read rendered outputs only; never read notebook sources containing secrets."""
    parts: list[str] = []
    with suppress(Exception):
        parts.extend(await page.locator(".output-content, colab-error-output").all_inner_texts())
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            parts.append(await frame.locator("body").inner_text(timeout=1000))
        except Exception:
            continue
    return "\n".join(parts)


async def _scrub_live_notebook_secrets(page, values: list[str]) -> bool:
    """Remove injected bearer/tunnel secrets after running processes captured them."""
    secrets_to_scrub = [value for value in values if value]
    if not secrets_to_scrub:
        return False
    try:
        changed = await page.evaluate("""([secrets]) => {
          let changed = false;
          for (const model of monaco.editor.getModels()) {
            let value = model.getValue();
            for (const secret of secrets) {
              if (!secret || !value.includes(secret)) continue;
              value = value.split(secret).join('__AIOS_RUNTIME_SECRET_SCRUBBED__');
              changed = true;
            }
            if (value !== model.getValue()) model.setValue(value);
          }
          return changed;
        }""", [secrets_to_scrub])
        if changed:
            print("🧹 Runtime-секреты удалены из live editor DOM после запуска")
        return bool(changed)
    except Exception:
        return False


async def _run_tunnel_cell(page) -> bool:
    """Run only the tunnel cell when vLLM is already healthy in this runtime."""
    selectors = ("colab-code-cell", ".cell.code.notebook-cell", ".cell.code", ".code-cell")
    try:
        for selector in selectors:
            cells = page.locator(selector)
            for index in range(await cells.count() - 1, -1, -1):
                cell = cells.nth(index)
                text = await cell.inner_text(timeout=1500)
                if (
                    "# === Защищённый tunnel" not in text
                    and "# === Защищённый Cloudflare tunnel" not in text
                ):
                    continue
                await cell.click(timeout=3000)
                await page.keyboard.press("Control+Enter")
                await asyncio.sleep(2)
                await _confirm_dialogs(page)
                print("▶️ Запущена только tunnel-ячейка; vLLM сохранён")
                return True
        # Colab DOM variants may not expose a stable cell class, while the
        # source text is still searchable through Playwright's text engine.
        source = page.get_by_text("# === Защищённый tunnel", exact=False).last
        if await source.count() and await source.is_visible():
            await source.click(timeout=3000)
            await page.keyboard.press("Control+Enter")
            await asyncio.sleep(2)
            await _confirm_dialogs(page)
            print("▶️ Запущена tunnel-ячейка через source fallback; vLLM сохранён")
            return True
    except Exception as exc:
        print(f"Tunnel-only note: {type(exc).__name__}")
    return False


async def _wait_for_new_tunnel(
    page,
    *,
    old_urls: set[str],
    attempts: int,
    service_kind: str,
    old_output: str = "",
    expected_generation: str = "",
) -> tuple[str, bool]:
    output_was_cleared = not old_urls
    fatal_markers = (
        "GPU available: False",
        "T4 GPU не подключён",
        "vLLM завершился:",
        "vLLM не запустился за 8 минут",
        "tunnel URL не получен",
        "TAILSCALE_AUTH_KEY is required",
        "COLAB_LLM_PUBLIC_URL is required",
    )
    fatal_baseline = {marker: old_output.count(marker) for marker in fatal_markers}
    fatal_output_was_cleared = not any(fatal_baseline.values())
    for attempt in range(attempts):
        await asyncio.sleep(6)
        output_text = await _output_text(page)
        if service_kind == "llm":
            current_fatal_counts = {
                marker: output_text.count(marker) for marker in fatal_markers
            }
            if not any(current_fatal_counts.values()):
                fatal_output_was_cleared = True
            new_fatal = any(
                count > fatal_baseline[marker]
                or (fatal_output_was_cleared and count > 0)
                for marker, count in current_fatal_counts.items()
            )
            if new_fatal:
                print("❌ Обнаружена фатальная ошибка нового запуска LLM-ячейки")
                return "", True
            generation_ready = not expected_generation or (
                f"COLAB_TUNNEL_GENERATION={expected_generation}" in output_text
            )
            urls = _extract_endpoint_urls(output_text) if generation_ready else []
        else:
            generation_ready = True
            urls = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", output_text)
        if not urls:
            output_was_cleared = True
        if expected_generation and generation_ready and urls:
            fresh_url = urls[-1]
        else:
            fresh_url = _select_fresh_tunnel(urls, old_urls, output_was_cleared)
        if fresh_url:
            print("🎉 Получен URL нового выполнения tunnel-ячейки")
            return fresh_url, False
        print(f"⏳ [Сканирование {attempt + 1}/{attempts}] Ожидание нового tunnel generation...")
    return "", False


async def _confirm_dialogs(page):
    """Confirm known Colab dialogs, including reconnect and runtime changes."""
    js_confirm = """
    () => {
      const EXACT = [
        "Усе одно запустити", "Усе одно запустить", "Всё равно запустить",
        "Все равно запустить", "Выполнить", "Run anyway", "Run",
        "Подключиться повторно", "Підключитися повторно", "Reconnect",
        "Reconnect runtime", "Продолжить", "Continue", "ОК", "OK"
      ];
      const labels = EXACT.map(s => s.toLowerCase());
      let hit = null;
      const walk = root => {
        for (const el of root.querySelectorAll("*")) {
          if (hit) return;
          if (el.shadowRoot) walk(el.shadowRoot);
          const text = (el.innerText || el.textContent || "").trim();
          if (labels.includes(text.toLowerCase())) {
            el.click();
            hit = text;
          }
        }
      };
      const dialogs = Array.from(document.querySelectorAll(
        "mwc-dialog[open], md-dialog[open], paper-dialog[open]"
      ));
      if (dialogs.length) {
        for (const dialog of dialogs) {
          walk(dialog);
          if (hit) break;
        }
      } else {
        walk(document);
      }
      if (!hit) {
        for (const frame of document.querySelectorAll("iframe")) {
          try {
            if (frame.contentDocument) walk(frame.contentDocument);
          } catch (e) {}
          if (hit) break;
        }
      }
      return hit;
    }
    """
    try:
        hit = await page.evaluate(js_confirm)
        if hit:
            print(f"👍 Подтверждено (JS): {hit}")
            await asyncio.sleep(1)
        return hit
    except Exception:
        return None


async def _ensure_t4_runtime(page):
    """Select a T4 runtime for the LLM notebook without resetting an existing T4."""
    if os.getenv("COLAB_SERVICE_KIND", "llm") != "llm":
        return False
    if os.getenv("COLAB_AUTO_T4", "1").strip().lower() in ("0", "false", "no", "off"):
        return False

    try:
        # Clear reconnect/runtime warnings that would intercept the menu click.
        await _confirm_dialogs(page)
        menu = page.locator("#runtime-menu-button")
        await menu.click(timeout=5000)
        await asyncio.sleep(0.5)

        item = None
        for label in ("Сменить среду выполнения", "Change runtime type"):
            candidates = page.get_by_text(label, exact=True)
            for index in range(await candidates.count()):
                candidate = candidates.nth(index)
                if await candidate.is_visible():
                    item = candidate
                    break
            if item is not None:
                break
        if item is None:
            await page.keyboard.press("Escape")
            print("⚠️ Не найден пункт смены runtime; оставляю текущий тип")
            return False

        await item.click(timeout=5000)
        await asyncio.sleep(1)
        t4 = page.locator('mwc-radio[value="GPU,T4"]')
        if not await t4.count():
            await page.keyboard.press("Escape")
            print("⚠️ T4 недоступна в диалоге Colab")
            return False

        if await t4.evaluate("e => !!e.checked"):
            await page.evaluate("""() => {
              const dialog = document.querySelector('mwc-dialog.change-runtime-type[open]');
              if (!dialog) return;
              const walk = root => {
                for (const el of root.querySelectorAll('*')) {
                  if (el.shadowRoot) walk(el.shadowRoot);
                  const text = (el.innerText || el.textContent || '').trim();
                  if (text === 'Отмена' || text === 'Cancel') { el.click(); return; }
                }
              };
              walk(dialog);
            }""")
            print("✅ Runtime Colab уже настроен на T4")
            return False

        await t4.click(timeout=5000)
        if not await t4.evaluate("e => !!e.checked"):
            raise RuntimeError("T4 radio did not become checked")
        saved = await page.evaluate("""() => {
          const dialog = document.querySelector('mwc-dialog.change-runtime-type[open]');
          if (!dialog) return false;
          let hit = false;
          const walk = root => {
            for (const el of root.querySelectorAll('*')) {
              if (hit) return;
              if (el.shadowRoot) walk(el.shadowRoot);
              const text = (el.innerText || el.textContent || '').trim();
              if (text === 'Сохранить' || text === 'Save') { el.click(); hit = true; }
            }
          };
          walk(dialog);
          return hit;
        }""")
        if not saved:
            raise RuntimeError("runtime Save button not found")
        await asyncio.sleep(1)
        await _confirm_dialogs(page)
        await asyncio.sleep(12)
        print("✅ Runtime Colab автоматически переключён на T4")
        return True
    except Exception as exc:
        with suppress(Exception):
            await page.keyboard.press("Escape")
        print(f"⚠️ Auto-T4 note: {type(exc).__name__}: {str(exc)[:160]}")
        return False


async def _prepare_llm_notebook(page) -> str:
    """Patch the GitHub LLM notebook for the current Colab runtime.

    The upstream notebook used a non-existent PyPI ``cloudflared`` package and
    an unprotected full-precision model.  This runtime patch keeps the GitHub
    source generic while injecting the per-node API key only into the live,
    authenticated Colab session.
    """
    if os.getenv("COLAB_SERVICE_KIND", "llm") != "llm":
        return ""
    api_key = os.getenv("COLAB_LLM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("COLAB_LLM_API_KEY is required for the Colab LLM endpoint")

    tunnel_provider = _configured_tunnel_provider()
    tailscale_auth_key = os.getenv("TAILSCALE_AUTH_KEY", "").strip()
    tailscale_public_url = os.getenv("COLAB_LLM_PUBLIC_URL", "").strip().rstrip("/")
    tailscale_hostname = os.getenv("TAILSCALE_COLAB_HOSTNAME", "aios-colab-llm").strip()
    tailscale_mode = os.getenv("TAILSCALE_MODE", "funnel").strip().lower()
    recovery_generation = secrets.token_hex(8)

    cell1 = f"""# === Быстрая подготовка vLLM и tunnel binary ===
import importlib.util, os, pathlib, shutil, subprocess, sys, urllib.request
TUNNEL_PROVIDER = {tunnel_provider!r}
if importlib.util.find_spec("vllm") is None:
    print("STAGE install:vllm")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "vllm"])
else:
    print("STAGE install:vllm cached")
if importlib.util.find_spec("torchaudio") is not None:
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "-q", "torchaudio"], check=False)
if pathlib.Path("/content/drive/MyDrive").exists():
    cache = pathlib.Path("/content/drive/MyDrive/AIOS/huggingface_cache")
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache)
    print("STAGE cache:huggingface drive")
if TUNNEL_PROVIDER == "tailscale":
    if shutil.which("tailscale") is None:
        print("STAGE install:tailscale")
        subprocess.check_call("curl -fsSL https://tailscale.com/install.sh | sh", shell=True)
else:
    cloudflared = pathlib.Path("/usr/local/bin/cloudflared")
    if not cloudflared.exists():
        print("STAGE install:cloudflared")
        target = pathlib.Path("/tmp/cloudflared.new")
        urllib.request.urlretrieve(
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
            target,
        )
        target.chmod(0o755)
        os.replace(target, cloudflared)
print("✅ STAGE install:ready provider=" + TUNNEL_PROVIDER)
"""
    cell2 = f"""# === Защищённый vLLM OpenAI API на T4 ===
import os, subprocess, time, requests, pathlib, torch
API_KEY = {api_key!r}
print("GPU available:", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise RuntimeError("T4 GPU не подключён: torch.cuda.is_available() == False")
print("GPU:", torch.cuda.get_device_name(0))
headers = {{"Authorization": "Bearer " + API_KEY}}
try:
    existing = requests.get("http://127.0.0.1:8000/v1/models", headers=headers, timeout=3)
except Exception:
    existing = None
if existing is not None and existing.status_code == 200:
    print("✅ STAGE model:reused colab/qwen2.5-coder")
else:
    subprocess.run("pkill -f 'vllm.entrypoints.openai.api_server' || true", shell=True)
    log_path = "/tmp/aios_vllm.log"
    log_file = open(log_path, "w")
    cmd = [
        "python3", "-m", "vllm.entrypoints.openai.api_server",
        "--model", "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
        "--served-model-name", "colab/qwen2.5-coder",
        "--quantization", "awq", "--dtype", "half",
        "--port", "8000", "--max-model-len", "4096",
        "--gpu-memory-utilization", "0.90", "--api-key", API_KEY,
    ]
    vllm_proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, env=os.environ.copy())
    for attempt in range(240):
        if vllm_proc.poll() is not None:
            log_file.flush()
            tail = pathlib.Path(log_path).read_text(errors="replace")[-5000:]
            raise RuntimeError("vLLM завершился:\\n" + tail)
        try:
            response = requests.get("http://127.0.0.1:8000/v1/models", headers=headers, timeout=3)
            if response.status_code == 200:
                print("✅ vLLM API готов: colab/qwen2.5-coder")
                break
        except Exception:
            pass
        if attempt % 10 == 0:
            print(f"⏳ Загрузка модели: {{attempt * 2}} сек")
        time.sleep(2)
    else:
        log_file.flush()
        tail = pathlib.Path(log_path).read_text(errors="replace")[-5000:]
        raise TimeoutError("vLLM не запустился за 8 минут:\\n" + tail)
"""
    if tunnel_provider == "tailscale":
        cell3 = f"""# === Защищённый tunnel: Tailscale ===
import pathlib, subprocess, time
TAILSCALE_AUTH_KEY = {tailscale_auth_key!r}
PUBLIC_URL = {tailscale_public_url!r}
HOSTNAME = {tailscale_hostname!r}
MODE = {tailscale_mode!r}
if not TAILSCALE_AUTH_KEY:
    raise RuntimeError("TAILSCALE_AUTH_KEY is required")
if not PUBLIC_URL:
    raise RuntimeError("COLAB_LLM_PUBLIC_URL is required")
socket = "/tmp/aios-tailscaled.sock"
state = "/tmp/aios-tailscaled.state"
subprocess.run(["pkill", "-f", "tailscaled.*aios-tailscaled"], check=False)
daemon_log = open("/tmp/aios_tailscaled.log", "w")
daemon = subprocess.Popen([
    "tailscaled", "--tun=userspace-networking", "--socket=" + socket,
    "--state=" + state,
], stdout=daemon_log, stderr=subprocess.STDOUT)
for _ in range(30):
    if pathlib.Path(socket).exists():
        break
    if daemon.poll() is not None:
        raise RuntimeError("Tailscale daemon failed")
    time.sleep(1)
subprocess.check_call([
    "tailscale", "--socket=" + socket, "up", "--reset",
    "--authkey=" + TAILSCALE_AUTH_KEY, "--hostname=" + HOSTNAME,
    "--accept-routes=false",
])
if MODE == "serve":
    subprocess.check_call(["tailscale", "--socket=" + socket, "serve", "--bg", "http://127.0.0.1:8000"])
else:
    subprocess.check_call(["tailscale", "--socket=" + socket, "funnel", "--bg", "8000"])
tunnel_url = PUBLIC_URL.rstrip("/")
if not tunnel_url.endswith("/v1"):
    tunnel_url += "/v1"
print("🎉 COLAB_LLM_URL=" + tunnel_url)
print("COLAB_TUNNEL_GENERATION=" + {recovery_generation!r})
print("🔐 Tailscale tunnel и Bearer API готовы")
"""
    else:
        cell3 = f"""# === Защищённый tunnel: Cloudflare quick fallback ===
import subprocess, re, time
subprocess.run(["pkill", "-f", "cloudflared tunnel --url http://127.0.0.1:8000"], check=False)
time.sleep(1)
tunnel = subprocess.Popen(
    ["cloudflared", "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)
tunnel_url = ""
deadline = time.time() + 90
while time.time() < deadline:
    line = tunnel.stdout.readline()
    if not line and tunnel.poll() is not None:
        break
    match = re.search(r"https://[a-zA-Z0-9-]+\\.trycloudflare\\.com", line or "")
    if match:
        tunnel_url = match.group(0) + "/v1"
        print("🎉 COLAB_LLM_URL=" + tunnel_url)
        print("COLAB_TUNNEL_GENERATION=" + {recovery_generation!r})
        print("🔐 Quick tunnel и Bearer API готовы")
        break
if not tunnel_url:
    raise RuntimeError("Quick tunnel URL не получен")
"""
    patch_js = """([c1,c2,c3]) => {
      const models = monaco.editor.getModels();
      const find = (patterns) => models.find(m => patterns.some(p => m.getLineContent(1).startsWith(p)));
      const m1 = find(['# === ЯЧЕЙКА 1', '# === Установка vLLM', '# === Быстрая подготовка']);
      const m2 = find(['# === ЯЧЕЙКА 2', '# === Защищённый vLLM']);
      const m3 = find(['# === ЯЧЕЙКА 3', '# === Защищённый Cloudflare', '# === Защищённый tunnel']);
      if (!m1 || !m2 || !m3) return false;
      m1.setValue(c1); m2.setValue(c2); m3.setValue(c3);
      return true;
    }"""
    for _ in range(20):
        try:
            if await page.evaluate(patch_js, [cell1, cell2, cell3]):
                print("🛠️ LLM-ячейки Colab подготовлены для T4/AWQ и защищённого API")
                return recovery_generation
        except Exception:
            pass
        await asyncio.sleep(1)
    raise RuntimeError("Не удалось подготовить LLM-ячейки Colab")


async def run_colab_automation():
    from tg_bot.credentials import import_runtime_credential
    from tg_bot.recovery_slo import record_recovery

    recovery_started = time.monotonic()
    recovery_mode = "full_cold"
    import_runtime_credential("COLAB_LLM_API_KEY", "colab_llm_api_key")
    import_runtime_credential("TAILSCALE_AUTH_KEY", "tailscale_auth_key")
    cdp_url = (
        os.getenv("COLAB_CDP_URL")
        or os.getenv("AIOS_CHROME_CDP")
        or "http://localhost:9222"
    )
    print(f"🚀 [ColabRunner] Запуск автоматизации Google Colab через Chrome CDP ({cdp_url})...")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
        from playwright.async_api import async_playwright

    notebook_url = _pick_notebook()
    print(f"📒 Выбран ноутбук: {notebook_url}")

    async with async_playwright() as p:
        browser = None
        context = None

        # 1. Попытка подключения к запущенному Chrome по CDP 9222
        try:
            print(f"📡 Подключение к браузеру Chrome по CDP: {cdp_url}...")
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            print("✅ Успешно подключились к запущенному Chrome по CDP!")
        except Exception as e:
            print(f"⚠️ CDP недоступен ({e}). Запускаю фоновый контекст Playwright...")
            user_data_dir = Path(
                os.getenv(
                    "COLAB_CHROME_PROFILE",
                    str(REPO_ROOT / "data" / "chrome_twin" / "default"),
                )
            )
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=False,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )

        page = await context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        # Переиспользование уже открытой вкладки с тем же ноутбуком
        reused = False
        nb_key = notebook_url.split("/")[-1]
        for pg in context.pages:
            try:
                if nb_key and nb_key in pg.url and "colab" in pg.url:
                    page = pg
                    reused = True
                    print(f"✅ Переиспользована существующая вкладка Colab: {nb_key}")
                    break
            except Exception:
                continue

        tunnel_url = ""
        colab_api_key = os.getenv("COLAB_LLM_API_KEY", "").strip()
        endpoint_reused = False
        old_tunnel_urls: set[str] = set()
        old_output_text = ""
        expected_generation = ""
        service_kind = os.getenv("COLAB_SERVICE_KIND", "llm")

        tunnel_only_recovery = False
        full_run_started = False
        tunnel_provider = _configured_tunnel_provider()

        if reused:
            recovery_mode = "runtime_restart"
            print("ℹ️  Вкладка переиспользована. Проверяю runtime и endpoint перед recovery...")
            reconnect_hit = await _confirm_dialogs(page)
            if reconnect_hit and re.search(r"повторно|reconnect", reconnect_hit, re.I):
                await asyncio.sleep(12)
            await _ensure_t4_runtime(page)
            await _connect_runtime(page)
            await _confirm_dialogs(page)
            await asyncio.sleep(2)

            if service_kind == "llm":
                healthy = await asyncio.to_thread(_healthy_registered_colab)
                if healthy:
                    tunnel_url = str(healthy.get("base_url", "")).strip().rstrip("/")
                    colab_api_key = str(healthy.get("api_key", "")).strip()
                    endpoint_reused = True
                    recovery_mode = "endpoint_reuse"
                    print("✅ STAGE endpoint:healthy — выполнение ячеек пропущено")
                else:
                    current = _load_colab_runtime_config()
                    colab_api_key = (
                        os.getenv("COLAB_LLM_API_KEY", "").strip()
                        or str(current.get("api_key", "")).strip()
                    )
                    if not colab_api_key:
                        colab_api_key = _rotate_colab_api_key()
                    os.environ["COLAB_LLM_API_KEY"] = colab_api_key
                    expected_generation = await _prepare_llm_notebook(page)
                    old_output_text = await _output_text(page)
                    old_tunnel_urls = set(_extract_endpoint_urls(old_output_text))
                    if tunnel_provider == "tailscale":
                        # Stable Tailscale URLs are expected to repeat; an
                        # authenticated health probe below rejects stale output.
                        old_tunnel_urls.clear()
                    tunnel_only_recovery = await _run_tunnel_cell(page)
                    if tunnel_only_recovery:
                        recovery_mode = "tunnel_only"
                        print("⚡ STAGE recovery:tunnel-only")
                    else:
                        colab_api_key = _rotate_colab_api_key()
                        expected_generation = await _prepare_llm_notebook(page)
                        old_output_text = await _output_text(page)
                        old_tunnel_urls = set(_extract_endpoint_urls(old_output_text))
                        await page.keyboard.press("Control+F9")
                        full_run_started = True
                        print("▶️ STAGE recovery:full — Ctrl+F9")
                        await asyncio.sleep(3)
                        await _confirm_dialogs(page)
            else:
                await page.keyboard.press("Control+F9")
                full_run_started = True
                await asyncio.sleep(3)
                await _confirm_dialogs(page)
        else:
            print(f"🔗 Переход в Google Colab Notebook: {notebook_url}")
            await page.goto(notebook_url, wait_until="domcontentloaded", timeout=60000)
            print("✅ Страница Google Colab успешно загружена!")
            await asyncio.sleep(5)
            await _ensure_t4_runtime(page)
            await _connect_runtime(page)

            if service_kind == "llm":
                colab_api_key = _rotate_colab_api_key()
                expected_generation = await _prepare_llm_notebook(page)
                old_output_text = await _output_text(page)
                old_tunnel_urls = set(_extract_endpoint_urls(old_output_text))

            print("▶️ STAGE recovery:full — Ctrl+F9")
            await page.keyboard.press("Control+F9")
            full_run_started = True
            await asyncio.sleep(5)
            await _confirm_dialogs(page)

        print("\n⏳ Инициализация и слежение за выполнением...")

        kind_needs_tunnel = service_kind in ("llm", "whisper")
        if kind_needs_tunnel and not tunnel_url and tunnel_only_recovery:
            quick_attempts = int(os.getenv("COLAB_TUNNEL_ONLY_WAIT_ATTEMPTS", "20"))
            tunnel_url, fatal = await _wait_for_new_tunnel(
                page,
                old_urls=old_tunnel_urls,
                attempts=quick_attempts,
                service_kind=service_kind,
                old_output=old_output_text,
                expected_generation=expected_generation,
            )
            if tunnel_url and service_kind == "llm":
                candidate = {
                    "base_url": tunnel_url,
                    "api_key": colab_api_key,
                    "model": COLAB_MODEL,
                    "enabled": True,
                }
                if not await asyncio.to_thread(_probe_colab_config, candidate, timeout=15):
                    print("⚠️ Tunnel восстановлен, но локальный vLLM не отвечает; нужен полный recovery")
                    tunnel_url = ""
            if fatal:
                tunnel_url = ""

            if not tunnel_url:
                colab_api_key = _rotate_colab_api_key()
                expected_generation = await _prepare_llm_notebook(page)
                old_output_text = await _output_text(page)
                old_tunnel_urls = set(_extract_endpoint_urls(old_output_text))
                if tunnel_provider == "tailscale":
                    old_tunnel_urls.clear()
                await page.keyboard.press("Control+F9")
                full_run_started = True
                recovery_mode = "runtime_restart" if reused else "full_cold"
                print("▶️ STAGE recovery:full после неудачи tunnel-only")
                await asyncio.sleep(3)
                await _confirm_dialogs(page)

        if kind_needs_tunnel and not tunnel_url and full_run_started:
            wait_attempts = int(os.getenv("COLAB_TUNNEL_WAIT_ATTEMPTS", "160"))
            tunnel_url, fatal = await _wait_for_new_tunnel(
                page,
                old_urls=old_tunnel_urls,
                attempts=wait_attempts,
                service_kind=service_kind,
                old_output=old_output_text,
                expected_generation=expected_generation,
            )
            if fatal:
                await _scrub_live_notebook_secrets(
                    page, [colab_api_key, os.getenv("TAILSCALE_AUTH_KEY", "")]
                )
                record_recovery(
                    mode=recovery_mode,
                    duration_seconds=time.monotonic() - recovery_started,
                    success=False,
                    error_class="tunnel_fatal",
                )
                return
        elif not kind_needs_tunnel:
            print("ℹ️  Этот ноутбук не создаёт туннель — переходим сразу к watchdog")

        if tunnel_url:
            if service_kind == "whisper" or "Whisper" in notebook_url:
                if not endpoint_reused:
                    from scripts.register_colab_whisper import register_whisper_endpoint
                    register_whisper_endpoint(tunnel_url)
            elif not endpoint_reused:
                from scripts.register_colab_llm import register_colab_endpoint
                try:
                    register_colab_endpoint(
                        tunnel_url,
                        COLAB_MODEL,
                        api_key=colab_api_key,
                        verify=True,
                        node_id=os.getenv("COLAB_NODE_ID", "primary"),
                        publish_primary=(
                            os.getenv("COLAB_NODE_ROLE", "primary").strip().lower() != "standby"
                        ),
                    )
                finally:
                    await _scrub_live_notebook_secrets(
                        page,
                        [colab_api_key, os.getenv("TAILSCALE_AUTH_KEY", "")],
                    )
            else:
                await _scrub_live_notebook_secrets(
                    page,
                    [colab_api_key, os.getenv("TAILSCALE_AUTH_KEY", "")],
                )
                print("♻️ Используется уже зарегистрированный здоровый endpoint")

            # AIOS Colab Farm registry is refreshed even on the idempotent path.
            try:
                from aios_core.colab.colab_registry import colab_registry
                kind_map = {"rl": "quant_ml", "clustering": "quant_ml", "lora": "llm", "gguf": "llm"}
                kind = kind_map.get(service_kind, service_kind)
                node = os.getenv("COLAB_NODE_ID", "local")
                name = os.getenv("COLAB_SERVICE_NAME", f"colab-{kind}")
                model = os.getenv("COLAB_LLM_MODEL", COLAB_MODEL) if kind == "llm" else None
                colab_registry.register(
                    kind=kind,
                    base_url=tunnel_url,
                    model=model,
                    name=name,
                    node_id=node,
                )
                print(f"📦 [ColabFarm] Сервис '{name}' ({kind}) зарегистрирован")
            except Exception as reg_err:
                print(f"⚠️ [ColabFarm] Регистрация не удалась: {type(reg_err).__name__}")
        elif kind_needs_tunnel:
            await _scrub_live_notebook_secrets(
                page, [colab_api_key, os.getenv("TAILSCALE_AUTH_KEY", "")]
            )
            print("⚠️ Новый tunnel generation не появился; запускаю полный recovery")
            record_recovery(
                mode=recovery_mode,
                duration_seconds=time.monotonic() - recovery_started,
                success=False,
                error_class="tunnel_missing",
            )
            return

        recovery = record_recovery(
            mode=recovery_mode,
            duration_seconds=time.monotonic() - recovery_started,
            success=True,
        )
        print(
            "✅ STAGE recovery:slo "
            f"mode={recovery['mode']} duration={recovery['duration_seconds']:.1f}s "
            f"met={'yes' if recovery['slo_met'] else 'no'}"
        )

        # === БЕСКОНЕЧНЫЙ ЦИКЛ ПОДДЕРЖАНИЯ АКТИВНОСТИ (COLAB ACTIVITY KEEPER) ===
        print("\n🔄 [Colab Activity Keeper] Включен вочдог поддержания активности сессии Colab!")
        print("   Каждые 60 секунд отправляется колесо мыши и проверяются кнопки подключения, чтобы Colab не отключался.")

        click_counter = 0
        endpoint_failures = 0
        while True:
            await asyncio.sleep(60)
            click_counter += 1

            try:
                # 1. Движение и прокрутка колесом
                await page.mouse.wheel(0, 100)
                await asyncio.sleep(1)
                await page.mouse.wheel(0, -100)

                # 2. Проверка диалога отключения / переподключения
                rec_state = page.locator("#connect, #reconnect")
                rec_host = page.locator("colab-connect-button")
                rec_tip = (await rec_state.get_attribute("tooltiptext") or "") if await rec_state.count() else ""
                rec_connected = bool(re.search(r"Подключено к|Connected to", rec_tip, re.I))
                if await rec_host.is_visible() and not rec_connected:
                    reconnect_hit = await _confirm_dialogs(page)
                    if not reconnect_hit:
                        with suppress(Exception):
                            await rec_host.click(timeout=5000)
                    print(f"⚡ [Minute {click_counter}] Runtime Colab потерян; перезапускаю полную automation.")
                    return

                # Every two minutes verify that the protected LLM tunnel itself
                # is alive. Two consecutive failures trigger a full notebook rerun.
                is_llm_mode = "whisper" not in sys.argv and "Whisper" not in notebook_url
                if tunnel_url and is_llm_mode and click_counter % 2 == 0:
                    try:
                        import urllib.request as _ur
                        health_url = tunnel_url.rstrip("/") + "/models"
                        headers = {"Authorization": "Bearer " + colab_api_key}
                        req = _ur.Request(health_url, headers=headers)
                        with _ur.urlopen(req, timeout=12) as response:
                            if response.status != 200:
                                raise RuntimeError(f"HTTP {response.status}")
                        endpoint_failures = 0
                    except Exception as health_err:
                        endpoint_failures += 1
                        print(f"⚠️ [Minute {click_counter}] Tunnel health failure {endpoint_failures}/2: {type(health_err).__name__}")
                        if endpoint_failures >= 2:
                            print("♻️ Tunnel недоступен; перезапускаю полную automation.")
                            return

                print(f"🟢 [Minute {click_counter}] Colab Activity Keeper: сессия активна.")
            except Exception as err:
                print(f"Activity loop note: {err}")


if __name__ == "__main__":
    try:
        asyncio.run(run_colab_automation())
    except KeyboardInterrupt:
        print("\n👋 Colab Automation остановлена.")
    except Exception as e:
        print(f"❌ Ошибка Colab Automation: {e}")
