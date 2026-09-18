"""
LLM Balancer v2.2 — улучшенная балансировка с приоритетом рабочих провайдеров.

Исправления v2.1:
- 402 Payment Required = permanent dead (24h cooldown)
- Приоритет: groq > deepseek > zai > mistral > cohere > gemini > huggingface > airforce > openrouter > local
- local_first удален, local теперь всегда последний fallback
- Fallback цепочка: groq/llama, huggingface/gemma-3-27b, qwen2.5-coder:7b вместо 1.5b
- Экспоненциальный backoff для 429
- Учет installed моделей для local

Исправления v2.2 (2026-08-02, проверка ротации ключей):
- ГАРАНТИРОВАННЫЙ local-fallback: если ВСЕ облачные провайдеры недоступны,
  балансер пробует локальную Ollama (aios-coder:7b -> qwen2.5-coder:7b -> 1.5b),
  а не возвращает ошибку. Работает и для автокодера, и для чата.
- FIX: cohere переведён на формат v2 API (OpenAI-style messages) — старый
  формат v1 (message/chat_history) отклонялся с HTTP 422.
- FIX: local-провайдер добавлена модель aios-coder:7b (fine-tune qwen2.5-coder).
- LOCAL_LLM: если переменная не задана и процесс не в docker — local
  включается автоматически при живой Ollama. В docker требуется явный
  LOCAL_LLM=1 и LOCAL_LLM_BASE_URL=http://172.18.0.1:11434/v1/chat/completions.
- Проверка Ollama (/api/tags) теперь идёт через LOCAL_LLM_BASE_URL,
  а не захардкоженный localhost.

Исправления v2.3 (2026-08-02, запуск автокодера):
- Маппинг моделей на провайдера: groq-имя "llama-3.3-70b-versatile" больше не
  уходит на mistral/zai/openrouter (гарантированный HTTP 400) — подставляется
  родная модель провайдера. Убирает ~15 мёртвых запросов в каждом цикле
  автокодера и резко снижает потребность в медленном local fallback.
"""

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

for _env_path in (Path(__file__).resolve().parents[1] / ".env",):
    try:
        _env_lines = _env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        _env_lines = []
    for _line in _env_lines:
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _value = _line.partition("=")
        _key = _key.strip()
        _value = _value.strip().strip('"').strip("'")
        if _key and _key not in os.environ:
            os.environ[_key] = _value


@dataclass
class APIKey:
    key: str
    provider: str
    last_error: str = ""
    last_used: float = 0.0
    error_count: int = 0
    cooldown_until: float = 0.0
    permanently_dead: bool = False
    base_url: str = ""
    model: str = ""
    node_id: str = ""

    @property
    def is_available(self) -> bool:
        if self.permanently_dead:
            return False
        return time.time() > self.cooldown_until


@dataclass
class Provider:
    name: str
    base_url: str
    keys: list[APIKey] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    _key_index: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    installed: set = field(default_factory=set)
    # v2.4: лимит у провайдера аккаунт-уровневый (groq: 4 ключа = 1 аккаунт) —
    # когда падает последний стоящий ключ, не долбимся в провайдера ещё 240с.
    account_cooldown_until: float = 0.0

    def _notify_all_keys_dead(self) -> None:
        """Telegram-алерт при полном исчерпании ключей провайдера (не чаще раза в 4ч)."""
        if self.name != "groq":
            return
        try:
            _last = float(os.environ.get("_AIOS_GROQ_DEAD_ALERT_TS", "0") or 0)
            if time.time() - _last < 14400:
                return
            os.environ["_AIOS_GROQ_DEAD_ALERT_TS"] = str(time.time())
            _root = Path(__file__).resolve().parents[1]
            _token = ""
            _chat = ""
            for line in (_root / ".env").read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("TELEGRAM_BOT_TOKEN="):
                    _token = line.split("=", 1)[1].strip().strip('"').strip("'")
                if line.strip().startswith("TELEGRAM_CHAT_ID="):
                    _chat = line.split("=", 1)[1].strip().strip('"').strip("'")
            if not _token or not _chat:
                return
            import json as _json

            _payload = _json.dumps(
                {
                    "chat_id": int(_chat),
                    "text": "🚨 <b>Groq: все ключи в cooldown!</b>\nПополните/создайте ключи:\n<code>python tools/make_groq_keys.py 4 aios-server &lt;2captcha_key&gt; &lt;org&gt; &lt;project&gt;</code>",
                    "parse_mode": "HTML",
                }
            ).encode()
            import urllib.request as _ur

            _req = _ur.Request(
                f"https://api.telegram.org/bot{_token}/sendMessage",
                data=_payload,
                headers={"Content-Type": "application/json"},
            )
            with _ur.urlopen(_req, timeout=15):
                pass
        except Exception:
            pass

    def get_next_key(self) -> APIKey | None:
        with self._lock:
            if time.time() < self.account_cooldown_until:
                return None
            available = [k for k in self.keys if k.is_available]
            if not available:
                return None
            # Least recently used + lowest error count
            available_sorted = sorted(
                available, key=lambda k: (k.error_count, k.last_used)
            )
            key = available_sorted[0]
            key.last_used = time.time()
            # round-robin index update
            self._key_index = (self._key_index + 1) % len(self.keys)
            return key

    def mark_key_error(self, key: APIKey, error: str, cooldown: int = 300):
        key.last_error = error
        key.error_count += 1
        # Permanent dead for 402
        if "402" in error or "Payment" in error or "insufficient" in error.lower():
            key.cooldown_until = time.time() + 86400  # 24h
            if key.error_count >= 3:
                key.permanently_dead = True
            print(
                f"  [Balancer] {key.provider} key marked DEAD 24h: {error} (errors={key.error_count})"
            )
        else:
            # Exponential backoff for 429
            if "429" in error:
                cd = min(60 * (2 ** min(key.error_count, 4)), 600)
            else:
                cd = cooldown
            key.cooldown_until = time.time() + cd
            print(
                f"  [Balancer] {key.provider} key cooled down {cd}s: {error} (errors={key.error_count})"
            )
        # v2.4: если после этой ошибки не осталось доступных ключей — это лимит
        # аккаунта, а не ключа. Ставим аккаунт-куulдаun и не тратим HTTP-вызовы.
        if not any(k.is_available for k in self.keys):
            _now = time.time()
            if self.account_cooldown_until < _now:
                self.account_cooldown_until = _now + 240
                print(
                    f"  [Balancer] {self.name}: все {len(self.keys)} ключ(а) в cooldown "
                    f"(лимит аккаунта) — провайдер пропускается 240с"
                )


class LLMBalancer:
    PROVIDERS = {
        "openrouter": {
            "base_url": "https://openrouter.ai/api/v1/chat/completions",
            "models": [
                "google/gemini-2.0-flash-001",
                "mistralai/pixtral-12b-2409",
                "meta-llama/llama-4-maverick",
                "mistralai/mistral-small-3.2-24b-instruct",
                "deepseek/deepseek-chat-v3-0324",
                "openai/gpt-oss-20b:free",
                "cohere/north-mini-code:free",
                "google/gemma-4-31b-it:free",
            ],
        },
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "models": [
                "gemini-2.5-flash",
                "gemini-2.5-pro",
            ],
        },
        "openai": {
            "base_url": "https://api.openai.com/v1/chat/completions",
            "models": [
                "gpt-4o-mini",
                "gpt-4o",
                "gpt-4.1-mini",
            ],
        },
        "groq": {
            "base_url": "https://api.groq.com/openai/v1/chat/completions",
            "models": [
                "qwen/qwen3.6-27b",
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
                "mixtral-8x7b-32768",
                "gemma2-9b-it",
            ],
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com/chat/completions",
            "models": [
                "deepseek-chat",
                "deepseek-reasoner",
                "deepseek-coder",
            ],
        },
        "zai": {
            "base_url": "https://api.z.ai/api/v1/chat/completions",
            "models": [
                "glm-4.5-flash",
                "glm-4.7-flash",
                "glm-4.5",
                "glm-5",
            ],
        },
        "cerebras": {
            "base_url": "https://api.cerebras.ai/v1/chat/completions",
            "models": [
                "llama-3.3-70b",
                "llama-3.1-8b",
            ],
        },
        "mistral": {
            "base_url": "https://api.mistral.ai/v1/chat/completions",
            "models": [
                "pixtral-12b-2409",
                "pixtral-large-latest",
                "mistral-small-latest",
                "mistral-medium-latest",
                "open-mistral-7b",
                "codestral-latest",
            ],
        },
        "cohere": {
            "base_url": "https://api.cohere.ai/v2/chat",
            "models": [
                "command-a-03-2025",
                "command-r-08-2024",
                "command-r7b-12-2024",
            ],
        },
        "together": {
            "base_url": "https://api.together.xyz/v1/chat/completions",
            "models": [
                "meta-llama/Meta-Llama-3-70B-Instruct-Turbo",
                "mistralai/Mistral-7B-Instruct-v0.3",
                "Qwen/Qwen2.5-7B-Instruct-Turbo",
            ],
        },
        "airforce": {
            "base_url": "https://api.airforce/v1/chat/completions",
            "models": [
                "gpt-4o-mini",
                "gpt-4o",
                "claude-sonnet-4.6-rp",
                "llama-4-scout-17b-16e-instruct",
            ],
        },
        "aimlapi": {
            "base_url": "https://api.aimlapi.com/v1/chat/completions",
            "models": [
                "gpt-4o-mini",
                "gpt-4o",
                "meta-llama/Llama-3.3-70B-Instruct",
            ],
        },
        "ibm": {
            "base_url": "https://us-south.ml.cloud.ibm.com/ml/v1/chat/completions",
            "models": [
                "meta-llama/llama-3-3-70b-instruct",
            ],
        },
        "huggingface": {
            "base_url": "https://router.huggingface.co/v1/chat/completions",
            "models": [
                "meta-llama/Llama-3.3-70B-Instruct",
                "google/gemma-3-27b-it",
                "Qwen/Qwen3-30B-A3B-Instruct",
            ],
        },
        "local": {
            "base_url": os.environ.get(
                "LOCAL_LLM_BASE_URL", "http://localhost:11434/v1/chat/completions"
            ),
            "models": [
                "qwen2.5vl:7b",
                "qwen2.5vl:3b",
                "aios-coder:7b",  # AIOS fine-tune на базе qwen2.5-coder:7b
                "qwen2.5-coder:7b",  # prefer 7b over 1.5b
                "qwen2.5-coder:1.5b",
                "qwen2.5-coder:14b",
                "deepseek-coder:6.7b",
            ],
        },
    }

    MODEL_FALLBACKS = {
        "openai/gpt-oss-20b:free": [
            "meta-llama/llama-4-maverick",
            "llama-3.1-8b-instant",
            "google/gemma-3-27b-it",
            "mistralai/mistral-small-3.2-24b-instruct",
        ],
        "meta-llama/llama-4-maverick": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "gemini-2.5-flash",
            "mistralai/mistral-small-3.2-24b-instruct",
            "gpt-4o-mini",
            "deepseek-chat",
            "glm-4.5-flash",
        ],
        "gemini-2.0-flash": [
            "gemini-2.5-flash",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "meta-llama/llama-4-maverick",
            "gpt-4o-mini",
        ],
        "gemini-2.5-flash": [
            "gemini-2.0-flash",
            "llama-3.1-8b-instant",
            "meta-llama/llama-4-maverick",
            "gpt-4o-mini",
        ],
        # Топ-модель для ответов клиентам: при недоступности -> flash -> groq llama-70b
        "gemini-2.5-pro": [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
        ],
        # gpt-4o-mini: cloud-first, local 7b last
        "gpt-4o-mini": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "google/gemma-3-27b-it",
            "mistral-small-latest",
            "deepseek-chat",
            "glm-4.5-flash",
            "qwen2.5-coder:7b",  # local strong fallback
        ],
        "gpt-4o": [
            "gpt-4o-mini",
            "llama-3.3-70b-versatile",
            "google/gemma-3-27b-it",
            "qwen2.5-coder:7b",
        ],
        "mistralai/mistral-small-3.2-24b-instruct": [
            "llama-3.1-8b-instant",
            "meta-llama/llama-4-maverick",
            "gemini-2.0-flash",
            "gpt-4o-mini",
        ],
        "glm-4.5-flash": [
            "glm-4.7-flash",
            "deepseek-chat",
            "llama-3.1-8b-instant",
            "gemini-2.0-flash",
        ],
        "deepseek-chat": [
            "deepseek-reasoner",
            "llama-3.1-8b-instant",
            "meta-llama/llama-4-maverick",
            "gpt-4o-mini",
        ],
        "deepseek/deepseek-chat-v3-0324": [
            "deepseek-chat",
            "llama-3.1-8b-instant",
            "mistral-small-latest",
            "gpt-4o-mini",
        ],
        "llama-3.3-70b-versatile": [
            "llama-3.1-8b-instant",
            "google/gemma-3-27b-it",
            "mistral-small-latest",
        ],
        "llama-3.1-8b-instant": [
            "llama-3.3-70b-versatile",
            "mistral-small-latest",
            "google/gemma-3-27b-it",
            "gemini-2.0-flash",
        ],
        "gpt-3.5-turbo": [
            "llama-3.1-8b-instant",
            "google/gemma-3-27b-it",
            "mistralai/mistral-small-3.2-24b-instruct",
            "deepseek-chat",
        ],
        # Local -> cloud fallback
        "qwen2.5-coder:1.5b": [
            "qwen2.5-coder:7b",
            "google/gemma-3-27b-it",
            "llama-3.1-8b-instant",
            "meta-llama/llama-4-maverick",
            "gpt-4o-mini",
        ],
        "qwen2.5-coder:7b": [
            "llama-3.1-8b-instant",
            "google/gemma-3-27b-it",
            "meta-llama/Llama-3.3-70B-Instruct",
            "Qwen/Qwen3-30B-A3B-Instruct",
            "meta-llama/llama-4-maverick",
            "gpt-4o-mini",
        ],
    }

    def __init__(self):
        self.providers: dict[str, Provider] = {}
        self._runtime_config_signature: tuple | None = None
        self._runtime_lock = threading.RLock()
        self._route_local = threading.local()
        self.last_route = {}
        self._load_from_env()
        self._total_requests = 0
        self._total_errors = 0
        self._provider_stats: dict[str, int] = {}
        self._cache: dict[str, str] = {}
        self._cache_max = int(os.environ.get("LLM_CACHE_MAX", "256"))
        # Private Colab is preferred for text tasks; cloud providers and local
        # Ollama remain automatic fallbacks when the Colab session is unavailable.
        self.task_priority = {
            "vision": ["gemini", "mistral", "openrouter", "local"],
            "chat": [
                "colab",
                "groq",
                "gemini",
                "cerebras",
                "github",
                "mistral",
                "cohere",
                "together",
                "nvidia",
                "sambanova",
                "deepseek",
                "huggingface",
                "openai",
                "airforce",
                "openrouter",
                "aimlapi",
                "ibm",
                "local",
            ],
            "code": [
                "colab",
                "groq",
                "cerebras",
                "github",
                "mistral",
                "cohere",
                "together",
                "nvidia",
                "sambanova",
                "huggingface",
                "gemini",
                "openai",
                "airforce",
                "openrouter",
                "aimlapi",
                "deepseek",
                "zai",
                "ibm",
                "local",
            ],
            "analysis": [
                "colab",
                "groq",
                "gemini",
                "cerebras",
                "github",
                "mistral",
                "cohere",
                "together",
                "nvidia",
                "huggingface",
                "openai",
                "airforce",
                "openrouter",
                "local",
            ],
            "general": [
                "colab",
                "groq",
                "gemini",
                "cerebras",
                "github",
                "mistral",
                "cohere",
                "together",
                "nvidia",
                "sambanova",
                "huggingface",
                "openai",
                "airforce",
                "openrouter",
                "aimlapi",
                "deepseek",
                "ibm",
                "local",
            ],
            # Планировщик автономии (JSON-структурированный вывод) — приоритет на
            # надёжные модели: groq llama-3.1-8b-instant, затем mistral/gemini/zai.
            "reasoning": [
                "colab",
                "groq",
                "gemini",
                "mistral",
                "cohere",
                "deepseek",
                "openrouter",
                "local",
            ],
        }

    @property
    def last_route(self) -> dict[str, object]:
        return dict(getattr(self._route_local, "value", {}))

    @last_route.setter
    def last_route(self, value: dict[str, object]) -> None:
        self._route_local.value = dict(value or {})

    def _load_from_env(self):
        for key_file in (
            Path("/app/data/.llm_keys.json"),
            Path(__file__).resolve().parents[1] / "data/.llm_keys.json",
        ):
            try:
                runtime = json.loads(key_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            env_prefix = {
                "openrouter": "OPENROUTER_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "openai": "OPENAI_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "zai": "ZAI_API_KEY",
                "cerebras": "CEREBRAS_API_KEY",
                "mistral": "MISTRAL_API_KEY",
                "cohere": "COHERE_API_KEY",
                "together": "TOGETHER_API_KEY",
                "huggingface": "HUGGINGFACE_API_KEY",
                "airforce": "AIRFORCE_API_KEY",
                "aimlapi": "AIMLAPI_API_KEY",
                "ibm": "IBM_API_KEY",
                "groq": "GROQ_API_KEY",
            }
            for provider, keys in runtime.items():
                prefix = env_prefix.get(provider)
                if not prefix or not isinstance(keys, list):
                    continue
                for index, key in enumerate(keys, 1):
                    if key and not os.environ.get(f"{prefix}_{index}"):
                        os.environ[f"{prefix}_{index}"] = str(key)

        # Generic loader helper
        def load_keys(prefix, prov_name):
            keys = []
            for i in range(1, 10):
                k = os.environ.get(f"{prefix}_{i}", "")
                if k:
                    keys.append(APIKey(key=k, provider=prov_name))
            base = os.environ.get(prefix, "")
            if base and not any(k.key == base for k in keys):
                keys.append(APIKey(key=base, provider=prov_name))
            if keys and prov_name in self.PROVIDERS:
                self.providers[prov_name] = Provider(
                    name=prov_name,
                    base_url=self.PROVIDERS[prov_name]["base_url"],
                    keys=keys,
                    models=self.PROVIDERS[prov_name]["models"],
                )

        for p, env_name in [
            ("openrouter", "OPENROUTER_API_KEY"),
            ("gemini", "GEMINI_API_KEY"),
            ("openai", "OPENAI_API_KEY"),
            ("huggingface", "HUGGINGFACE_API_KEY"),
            ("airforce", "AIRFORCE_API_KEY"),
            ("aimlapi", "AIMLAPI_API_KEY"),
            ("ibm", "IBM_API_KEY"),
            ("groq", "GROQ_API_KEY"),
            ("deepseek", "DEEPSEEK_API_KEY"),
            ("zai", "ZAI_API_KEY"),
            ("cerebras", "CEREBRAS_API_KEY"),
            ("mistral", "MISTRAL_API_KEY"),
            ("cohere", "COHERE_API_KEY"),
            ("together", "TOGETHER_API_KEY"),
        ]:
            load_keys(env_name, p)

        # Local Ollama
        _local_flag = (
            os.environ.get("LOCAL_LLM", "").strip().strip('"').strip("'").lower()
        )
        _local_explicit = _local_flag in ("1", "true", "yes")
        _local_disabled = _local_flag in ("0", "false", "no")
        _in_docker = os.path.exists("/.dockerenv")
        # Явно включено (LOCAL_LLM=1) -> регистрируем всегда.
        # Не задано -> авто-включение ТОЛЬКО на хосте (не в docker): в контейнере
        # localhost указывает на сам контейнер, там нужен явный LOCAL_LLM=1
        # и LOCAL_LLM_BASE_URL на адрес хоста (например http://172.18.0.1:11434/...).
        _local_enabled = _local_explicit or (not _local_disabled and not _in_docker)
        if _local_enabled:
            _local_base = self.PROVIDERS["local"]["base_url"]
            _tags_url = _local_base.replace("/v1/chat/completions", "/api/tags")
            try:
                import urllib.request as _ur

                with _ur.urlopen(_tags_url, timeout=2) as _r:
                    _installed = {
                        m["name"]
                        for m in json.loads(_r.read().decode("utf-8", "ignore")).get(
                            "models", []
                        )
                    }
                _reachable = True
            except Exception:
                _installed = set()
                _reachable = False

            if _reachable or _local_explicit:
                # Filter: only keep models that are actually installed if we have info
                if _installed:
                    available_models = [
                        m
                        for m in self.PROVIDERS["local"]["models"]
                        if m in _installed or any(m in ins for ins in _installed)
                    ]
                    if not available_models:
                        available_models = list(_installed)[:5]
                else:
                    available_models = self.PROVIDERS["local"]["models"]
                    _installed = set(self.PROVIDERS["local"]["models"])

                self.providers["local"] = Provider(
                    name="local",
                    base_url=_local_base,
                    keys=[APIKey(key="local", provider="local")],
                    models=available_models,
                    installed=_installed,
                )

        # Private OpenAI-compatible model hosted in Google Colab. The runtime
        # registry is authoritative over process environment because keeper can
        # rotate URL/key without restarting Telegram.
        self.refresh_runtime_config(force=True)

    @staticmethod
    def _runtime_key_paths() -> tuple[Path, ...]:
        return (
            Path("/app/data/.llm_keys.json"),
            Path(__file__).resolve().parents[1] / "data" / ".llm_keys.json",
        )

    def _read_colab_runtime(self) -> tuple[dict, tuple]:
        mode = os.environ.get("AIOS_COLAB_MODE", "").strip().lower()
        if not mode:
            try:
                mode = (
                    Path(
                        os.environ.get(
                            "AIOS_COLAB_MODE_FILE", "/etc/octopus/colab-mode"
                        )
                    )
                    .read_text(encoding="utf-8")
                    .strip()
                    .lower()
                )
            except OSError:
                mode = "active"
        if mode in ("maintenance", "human_action_required", "disabled"):
            return {"enabled": False}, ("colab-mode", mode)
        for path in self._runtime_key_paths():
            try:
                stat = path.stat()
                data = json.loads(path.read_text(encoding="utf-8"))
                candidate = data.get("colab_llm", {})
                nodes = data.get("colab_llm_nodes", [])
                valid_nodes = (
                    [item for item in nodes if isinstance(item, dict)]
                    if isinstance(nodes, list)
                    else []
                )
                if not isinstance(candidate, dict) or not candidate:
                    candidate = valid_nodes[0] if valid_nodes else {}
                if isinstance(candidate, dict) and candidate:
                    candidate = dict(candidate)
                    candidate["_nodes"] = valid_nodes
                    signature = (str(path), stat.st_mtime_ns, stat.st_size)
                    return candidate, signature
            except (OSError, ValueError):
                continue
        env_cfg = {
            "enabled": os.environ.get("COLAB_LLM_ENABLED", "1"),
            "base_url": os.environ.get("COLAB_LLM_URL", ""),
            "api_key": os.environ.get("COLAB_LLM_API_KEY", ""),
            "model": os.environ.get("COLAB_LLM_MODEL", "colab/qwen2.5-coder"),
        }
        # Include only a process-local hash in the signature; never log it.
        signature = ("env", hash(tuple(str(env_cfg[key]) for key in sorted(env_cfg))))
        return env_cfg, signature

    @staticmethod
    def _colab_endpoint(config: dict) -> tuple[str, str, str, str] | None:
        enabled_raw = str(config.get("enabled", True)).strip().lower()
        if enabled_raw in ("0", "false", "no", "off"):
            return None
        base_url = str(config.get("base_url", "")).strip().rstrip("/")
        api_key = str(config.get("api_key", "")).strip()
        model = str(config.get("model", "colab/qwen2.5-coder")).strip()
        node_id = str(config.get("node_id", "primary")).strip() or "primary"
        if not base_url or not api_key or not model:
            return None
        if base_url.endswith("/chat/completions"):
            endpoint = base_url
        elif base_url.endswith("/v1"):
            endpoint = base_url + "/chat/completions"
        else:
            endpoint = base_url + "/v1/chat/completions"
        return endpoint, api_key, model, node_id

    @classmethod
    def _build_colab_provider(cls, config: dict) -> Provider | None:
        candidates = [config, *list(config.get("_nodes", []))]
        endpoints: list[tuple[str, str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            parsed = cls._colab_endpoint(candidate)
            if not parsed:
                continue
            identity = (parsed[0], parsed[1])
            if identity in seen:
                continue
            seen.add(identity)
            endpoints.append(parsed)
        if not endpoints:
            return None
        keys = [
            APIKey(
                key=api_key,
                provider="colab",
                base_url=endpoint,
                model=model,
                node_id=node_id,
            )
            for endpoint, api_key, model, node_id in endpoints
        ]
        models = list(dict.fromkeys(item[2] for item in endpoints))
        return Provider(
            name="colab",
            base_url=endpoints[0][0],
            keys=keys,
            models=models,
        )

    def refresh_runtime_config(self, *, force: bool = False) -> bool:
        """Hot-reload a rotated Colab generation while preserving other cooldowns."""
        with self._runtime_lock:
            return self._refresh_runtime_config_unlocked(force=force)

    def _refresh_runtime_config_unlocked(self, *, force: bool = False) -> bool:
        config, signature = self._read_colab_runtime()
        if not force and signature == self._runtime_config_signature:
            return False
        replacement = self._build_colab_provider(config)
        current = self.providers.get("colab")
        current_nodes = (
            [
                (key.base_url or current.base_url, key.key, key.model, key.node_id)
                for key in current.keys
            ]
            if current
            else []
        )
        replacement_nodes = (
            [
                (key.base_url or replacement.base_url, key.key, key.model, key.node_id)
                for key in replacement.keys
            ]
            if replacement
            else []
        )
        unchanged = bool(current and replacement and current_nodes == replacement_nodes)
        if not unchanged:
            if replacement is None:
                self.providers.pop("colab", None)
            else:
                self.providers["colab"] = replacement
        self._runtime_config_signature = signature
        return not unchanged

    @staticmethod
    def _fit_colab_messages(messages: list[dict], max_chars: int = 6000) -> list[dict]:
        """Fit the large AIOS prompt into the Colab model's 4096-token window.

        Keep the beginning of the system prompt (identity and safety rules) and
        the newest dialogue turns. This applies only to the private Colab
        provider; cloud providers retain the full context.
        """
        max_chars = max(1000, int(max_chars))
        system_messages = [m for m in messages if m.get("role") == "system"]
        dialogue = [m for m in messages if m.get("role") != "system"]

        dialogue_total = sum(len(str(m.get("content", ""))) for m in dialogue)
        dialogue_limit = (
            max_chars if not system_messages else min(dialogue_total, max_chars // 3)
        )
        kept_reversed: list[dict] = []
        remaining = dialogue_limit
        for message in reversed(dialogue):
            if remaining <= 0:
                break
            content = str(message.get("content", ""))
            if len(content) > remaining:
                truncation_marker = (
                    "\n...[earlier content truncated for Colab context]...\n"
                )
                usable = max(0, remaining - len(truncation_marker))
                head = usable // 2
                tail = usable - head
                suffix = content[-tail:] if tail else ""
                content = content[:head] + truncation_marker + suffix
            kept_reversed.append({**message, "content": content})
            remaining -= len(content)
        kept_dialogue = list(reversed(kept_reversed))

        system_budget = max_chars - sum(
            len(str(m.get("content", ""))) for m in kept_dialogue
        )
        kept_system: list[dict] = []
        for message in system_messages:
            if system_budget <= 0:
                break
            content = str(message.get("content", ""))[:system_budget]
            kept_system.append({**message, "content": content})
            system_budget -= len(content)
        return kept_system + kept_dialogue

    def add_key(self, provider: str, key: str):
        if provider not in self.providers:
            if provider in self.PROVIDERS:
                self.providers[provider] = Provider(
                    name=provider,
                    base_url=self.PROVIDERS[provider]["base_url"],
                    models=self.PROVIDERS[provider]["models"],
                )
            else:
                print(f"  [Balancer] Unknown provider: {provider}")
                return
        self.providers[provider].keys.append(APIKey(key=key, provider=provider))

    def chat(
        self,
        messages: list[dict],
        model: str = "",
        system: str = "",
        max_tokens: int = 2000,
        temperature: float = 0.3,
        task_type: str = "general",
    ) -> str:
        self.refresh_runtime_config()
        self._total_requests += 1
        self.last_route = {}

        if not model:
            # Игнорируем LLM_MODEL, если это плейсхолдер/устаревшая gpt-3.5-turbo,
            # ради которой балансер гоняет мёртвые openrouter-запросы.
            _def = os.environ.get("LLM_MODEL", "").strip()
            if _def in ("", "sk-your-key-here", "gpt-3.5-turbo"):
                _def = "llama-3.1-8b-instant"
            model = _def

        if os.environ.get("LLM_CACHE", "1") == "1":
            _key = str(
                (
                    system or "",
                    [
                        tuple(sorted(m.items()))
                        for m in messages
                        if isinstance(m, dict) and "role" in m and "content" in m
                    ],
                )
            )
            if _key in self._cache:
                self.last_route = {
                    "provider": "cache",
                    "model": model,
                    "latency_sec": 0.0,
                }
                return self._cache[_key]

        models_to_try = [model, *self.MODEL_FALLBACKS.get(model, [])]
        # Deduplicate
        seen = set()
        uniq_models = []
        for m in models_to_try:
            if m not in seen:
                uniq_models.append(m)
                seen.add(m)
        models_to_try = uniq_models

        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        for try_model in models_to_try:
            max_keys_to_try = sum(len(p.keys) for p in self.providers.values())
            keys_tried = 0

            while keys_tried < max_keys_to_try:
                # Smart provider ordering, NO local_first override
                _prio = self.task_priority.get(task_type, self.task_priority["general"])
                _providers = []
                for _n in _prio:
                    if _n in self.providers:
                        _providers.append((_n, self.providers[_n]))
                for _n, _pr in self.providers.items():
                    if _n not in _prio:
                        _providers.append((_n, _pr))

                best_provider = None
                best_key = None

                for prov_name, provider in _providers:
                    # Check model support
                    if prov_name == "openrouter":
                        model_supported = True
                    elif prov_name == "colab":
                        # The private Colab runtime serves one configured model;
                        # map any text task to it and keep normal provider fallback.
                        model_supported = True
                    elif prov_name == "local":
                        inst = getattr(provider, "installed", set())
                        model_supported = (
                            try_model in inst or try_model in provider.models
                        )
                    else:
                        model_supported = try_model in provider.models
                        # For groq etc, also allow openrouter-style fallback models if provider is generic
                        # Allow any model if provider is known to be flexible (they will 404 if not)
                        # But we prefer to only try if model is in list or is common
                        if (
                            not model_supported
                            and prov_name in (
                                "groq",
                                "deepseek",
                                "zai",
                                "mistral",
                            )
                            and try_model in (
                                "gpt-4o-mini",
                                "gpt-4o",
                                "llama-3.1-8b-instant",
                                "llama-3.3-70b-versatile",
                            )
                        ):
                            model_supported = True

                    if not model_supported:
                        continue
                    k = provider.get_next_key()
                    if k:
                        best_provider = provider
                        best_key = k
                        break

                if not best_key or not best_provider:
                    break

                keys_tried += 1
                prov_name = best_provider.name
                req_model = try_model

                try:
                    import requests as _req_lib

                    # v2.3: маппинг модели на провайдера. Имя вида
                    # "llama-3.3-70b-versatile" существует только у groq — mistral/zai/
                    # openrouter отвечают 400. Подставляем родную модель провайдера.
                    if prov_name == "colab":
                        req_model = best_key.model or best_provider.models[0]
                    elif prov_name == "openrouter":
                        if "/" not in try_model:
                            # Голое имя (gpt-3.5-turbo и т.п.) → корректный openrouter slug.
                            # Не льёмся в устаревший :free-модель, от которой OpenRouter
                            # отдаёт 404 — это генерировало бесполезные мёртвые запросы.
                            _or_map = {
                                "gpt-3.5-turbo": "openai/gpt-3.5-turbo",
                                "gpt-4o-mini": "openai/gpt-4o-mini",
                                "gpt-4o": "openai/gpt-4o",
                                "llama-3.1-8b-instant": "meta-llama/llama-3.1-8b-instruct",
                                "llama-3.3-70b-versatile": "meta-llama/llama-3.3-70b-instruct",
                            }
                            req_model = _or_map.get(try_model)
                            if not req_model:
                                # Неизвестная модель без префикса — пропускаем openrouter
                                # (шанс 404 высок), лучше уйти на следующий провайдер.
                                continue
                    elif prov_name != "local" and try_model not in provider.models:
                        req_model = provider.models[0] if provider.models else try_model
                    req_messages = all_messages
                    req_max_tokens = max_tokens
                    if prov_name == "colab":
                        _colab_chars = int(
                            os.environ.get("COLAB_LLM_MAX_INPUT_CHARS", "6000")
                        )
                        _colab_output = int(
                            os.environ.get("COLAB_LLM_MAX_OUTPUT_TOKENS", "768")
                        )
                        req_messages = self._fit_colab_messages(
                            all_messages, _colab_chars
                        )
                        req_max_tokens = min(max_tokens, max(1, _colab_output))
                    payload = {
                        "model": req_model,
                        "messages": req_messages,
                        "max_tokens": req_max_tokens,
                        "temperature": temperature,
                    }

                    # Cohere v2 API (/v2/chat) принимает OpenAI-style messages,
                    # старый формат v1 (message/chat_history) отклоняется с 422.
                    # Ответ Cohere v2 разбирается в общей ветке парсинга ("message" -> content list).

                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {best_key.key}",
                        "HTTP-Referer": "https://github.com/JoTalbot/AIOS",
                        "X-Title": "AIOS Coder Orchestrator v2",
                    }

                    _request_started = time.monotonic()
                    request_url = best_key.base_url or best_provider.base_url
                    _resp = _req_lib.post(
                        request_url, json=payload, headers=headers, timeout=120
                    )
                    _resp.raise_for_status()
                    data = _resp.json()

                    if isinstance(data, dict):
                        if data.get("success") is False or (
                            data.get("code") and data["code"] not in (0, 200, None)
                        ):
                            err_msg = (
                                data.get("msg")
                                or data.get("message")
                                or str(data.get("code"))
                            )
                            print(f"  [Balancer] {prov_name} app-error: {err_msg}")
                            best_provider.mark_key_error(
                                best_key, f"app-error: {err_msg}", cooldown=300
                            )
                            continue
                        if "error" in data:
                            err_msg = data["error"].get("message", str(data["error"]))[
                                :80
                            ]
                            print(f"  [Balancer] {prov_name} error: {err_msg}")
                            best_provider.mark_key_error(
                                best_key, f"error: {err_msg}", cooldown=300
                            )
                            continue

                    self._provider_stats[prov_name] = (
                        self._provider_stats.get(prov_name, 0) + 1
                    )
                    print(f"  [Balancer] OK: {prov_name}/{req_model}")

                    # Parse response
                    content = ""
                    if data.get("choices"):
                        _c = data["choices"][0].get("message", {}).get("content", "")
                        content = _c if isinstance(_c, str) else ""
                    elif (
                        "data" in data
                        and isinstance(data["data"], dict)
                        and "choices" in data["data"]
                    ):
                        content = data["data"]["choices"][0]["message"]["content"]
                    elif "message" in data:
                        _mc = data["message"]
                        if isinstance(_mc, dict):
                            c = _mc.get("content")
                            if isinstance(c, list):
                                content = "".join(
                                    x.get("text", "") for x in c if isinstance(x, dict)
                                )
                            else:
                                content = str(c or "")
                        else:
                            content = str(_mc)
                    elif "text" in data:  # Cohere
                        content = data.get("text", "")
                    elif "result" in data:
                        content = str(data["result"])

                    if content:
                        self.last_route = {
                            "provider": prov_name,
                            "model": req_model,
                            "latency_sec": round(
                                time.monotonic() - _request_started, 3
                            ),
                            "node_id": best_key.node_id if prov_name == "colab" else "",
                        }
                        # Usage tracking (v2.4): пишем лог токенов/латентности по вызову
                        try:
                            _usage = (data or {}).get("usage") or {}
                            _usage_log = {
                                "ts": time.time(),
                                "provider": prov_name,
                                "model": req_model,
                                "key_tail": str(best_key.key)[-6:]
                                if best_key.key
                                else "",
                                "prompt_tokens": int(_usage.get("prompt_tokens") or 0),
                                "completion_tokens": int(
                                    _usage.get("completion_tokens") or 0
                                ),
                                "total_tokens": int(_usage.get("total_tokens") or 0),
                                "latency_sec": round(
                                    time.monotonic() - _request_started, 3
                                ),
                                "task_type": task_type,
                            }
                            _log_dir = (
                                Path(__file__).resolve().parents[1] / "data" / "llm"
                            )
                            _log_dir.mkdir(parents=True, exist_ok=True)
                            with open(
                                _log_dir / "usage.jsonl", "a", encoding="utf-8"
                            ) as _f:
                                _f.write(
                                    json.dumps(_usage_log, ensure_ascii=False) + "\n"
                                )
                        except Exception:
                            pass
                        if os.environ.get("LLM_CACHE", "1") == "1":
                            _cache_key = str(
                                (
                                    system or "",
                                    [
                                        tuple(sorted(m.items()))
                                        for m in messages
                                        if isinstance(m, dict)
                                        and "role" in m
                                        and "content" in m
                                    ],
                                )
                            )
                            if len(self._cache) < self._cache_max:
                                self._cache[_cache_key] = content
                        return content
                    else:
                        print(f"  [Balancer] {prov_name}: empty response")
                        best_provider.mark_key_error(
                            best_key, "empty response", cooldown=60
                        )
                        continue

                except Exception as e:
                    _code = getattr(
                        getattr(e, "response", None), "status_code", None
                    ) or getattr(e, "code", None)
                    if _code:
                        code = int(_code)
                        print(f"  [Balancer] {prov_name}/{req_model}: HTTP {code}")
                        if code == 402:
                            best_provider.mark_key_error(
                                best_key,
                                f"HTTP {code} Payment Required",
                                cooldown=86400,
                            )
                            continue
                        elif code == 429:
                            best_provider.mark_key_error(
                                best_key, f"HTTP {code} Rate Limited", cooldown=60
                            )
                            continue
                        elif code == 404:
                            break
                        elif code == 401:
                            best_provider.mark_key_error(
                                best_key, "Auth failed", cooldown=600
                            )
                            continue
                        elif code == 403:
                            body = str(
                                getattr(getattr(e, "response", None), "text", "") or ""
                            )[:100]
                            cd = 900 if "1010" in body else 600
                            best_provider.mark_key_error(
                                best_key, f"HTTP {code} {body[:40]}", cooldown=cd
                            )
                            continue
                        elif code >= 500:
                            best_provider.mark_key_error(
                                best_key, f"HTTP {code}", cooldown=60
                            )
                            continue
                        else:
                            best_provider.mark_key_error(
                                best_key, f"HTTP {code}", cooldown=300
                            )
                            continue
                    print(f"  [Balancer] {prov_name}/{req_model}: {str(e)[:80]}")
                    best_provider.mark_key_error(best_key, str(e)[:60], cooldown=60)
                    continue

        # FINAL SAFETY NET (v2.2): все облачные провайдеры/ключи недоступны —
        # пробуем локальную Ollama напрямую, минуя fallback-цепочки моделей.
        # Это гарантирует ответ для автокодера и чата, пока жива Ollama.
        _local_answer = self._try_local_fallback(all_messages, max_tokens, temperature)
        if _local_answer:
            return _local_answer

        self._total_errors += 1
        return "⚠️ Все LLM-провайдеры временно недоступны. Проверьте квоты и API-ключи."

    def _try_local_fallback(
        self, all_messages: list[dict], max_tokens: int, temperature: float
    ) -> str:
        """Last-resort fallback на локальную Ollama, когда ВСЕ облака умерли.

        Перебирает установленные локальные модели (aios-coder:7b, qwen2.5-coder:7b, 1.5b).
        Возвращает ответ или пустую строку, если и local недоступен.
        """
        provider = self.providers.get("local")
        if provider is None:
            return ""
        import requests as _req_lib

        for local_model in provider.models:
            try:
                print(f"  [Balancer] CLOUDS DOWN -> local fallback: {local_model}")
                _local_started = time.monotonic()
                _resp = _req_lib.post(
                    provider.base_url,
                    json={
                        "model": local_model,
                        "messages": all_messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "stream": False,
                    },
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": "Bearer local",
                    },
                    timeout=300,  # CPU-инференс 7B медленный
                )
                _resp.raise_for_status()
                data = _resp.json()
                content = ""
                if data.get("choices"):
                    _c = data["choices"][0].get("message", {}).get("content", "")
                    content = _c if isinstance(_c, str) else ""
                if content.strip():
                    self._provider_stats["local"] = (
                        self._provider_stats.get("local", 0) + 1
                    )
                    self.last_route = {
                        "provider": "local",
                        "model": local_model,
                        "latency_sec": round(time.monotonic() - _local_started, 3),
                    }
                    print(f"  [Balancer] LOCAL fallback OK: {local_model}")
                    return content
                print(f"  [Balancer] LOCAL fallback {local_model}: пустой ответ")
            except Exception as e:
                print(
                    f"  [Balancer] LOCAL fallback {local_model} failed: {str(e)[:80]}"
                )
                continue
        return ""

    def status(self) -> dict:
        result = {
            "total_requests": self._total_requests,
            "total_errors": self._total_errors,
            "providers": {},
            "last_route": dict(self.last_route),
        }
        for name, prov in self.providers.items():
            result["providers"][name] = {
                "keys_total": len(prov.keys),
                "keys_available": sum(1 for k in prov.keys if k.is_available),
                "requests": self._provider_stats.get(name, 0),
                "models": prov.models[:5],
                "nodes": len(prov.keys) if name == "colab" else 0,
            }
        return result

    def _query_colab_llm(
        self, all_messages: list[dict], max_tokens: int = 2000, temperature: float = 0.3
    ) -> str | None:
        """Запрос к кастомной кодинг-модели LLM, запущенной в Google Colab через OpenAI API."""
        import json
        import os
        import urllib.request
        from pathlib import Path

        colab_url = os.environ.get("COLAB_LLM_URL", "").strip().rstrip("/")
        colab_api_key = os.environ.get("COLAB_LLM_API_KEY", "").strip()
        keys_p = (
            Path(os.environ.get("OCTOPUS_DATA_DIR", "/var/lib/octopus"))
            / ".llm_keys.json"
        )
        if keys_p.exists():
            try:
                kd = json.loads(keys_p.read_text(encoding="utf-8"))
                colab_cfg = kd.get("colab_llm", {})
                if not colab_url:
                    colab_url = colab_cfg.get("base_url", "").strip().rstrip("/")
                if not colab_api_key:
                    colab_api_key = colab_cfg.get("api_key", "").strip()
            except Exception:
                pass

        if not colab_url:
            return None

        if not colab_url.endswith("/v1"):
            colab_url += "/v1"

        endpoint = f"{colab_url}/chat/completions"
        payload = {
            "model": os.environ.get("COLAB_LLM_MODEL", "colab/qwen2.5-coder"),
            "messages": all_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "AIOS-LLMBalancer/1.0",
            }
            if colab_api_key:
                headers["Authorization"] = f"Bearer {colab_api_key}"
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
        except Exception:
            return None
        return None
