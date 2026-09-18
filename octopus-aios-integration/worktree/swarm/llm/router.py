from __future__ import annotations
import asyncio, logging, time, httpx
from typing import Literal
from swarm.llm.key_pool import APIKey, KeyPool

logger = logging.getLogger("swarm.llm.router")
AuthKind = Literal["pool", "none", "local_bearer"]

class LLMRouter:
    def __init__(self, key_pool, models, base_url="https://openrouter.ai/api/v1", timeout=60, max_retries=3, backoff_base=2.0, proxy=None, local_base_url=None, local_models=None, local_api_key=None, prefer_local=False, model_aliases=None, bus=None):
        self.key_pool = key_pool
        self.models = list(models or [])
        if not self.models and not (local_models or []):
            raise ValueError("At least one model required")
        self.base_url = base_url.rstrip("/")
        self._local_base = local_base_url.rstrip("/") if local_base_url else None
        self.local_models = list(local_models or [])
        self._local_api_key = (local_api_key or "").strip() or None
        self.prefer_local = prefer_local
        self._model_aliases = dict(model_aliases or {})
        self.timeout = timeout
        self.max_retries = max_retries
        self._backoff_base = backoff_base
        self._proxy = proxy
        self._bus = bus
        self._clients = {}
        self.total_calls = 0; self.total_tokens_in = 0; self.total_tokens_out = 0; self.total_errors = 0
        self.calls_per_model = {}; self.errors_per_model = {}

    def _get_client(self):
        try: loop = asyncio.get_event_loop()
        except: loop = None
        if loop not in self._clients:
            self._clients[loop] = httpx.AsyncClient(timeout=self.timeout, proxy=self._proxy)
        return self._clients[loop]

    def _target_chain(self, explicit_model):
        cloud = [(self.base_url, m, "pool") for m in ([explicit_model] if explicit_model else self.models)] if (explicit_model or self.models) else []
        local = []
        if self._local_base and self.local_models:
            auth = "local_bearer" if self._local_api_key else "none"
            if explicit_model:
                resolved = self._model_aliases.get(explicit_model, explicit_model)
                # IF explicit model is cloud but we want fallback, we add all local models too
                if resolved in self.local_models: local = [(self._local_base, resolved, auth)]
                elif explicit_model in self.local_models: local = [(self._local_base, explicit_model, auth)]
                else: local = [(self._local_base, m, auth) for m in self.local_models]
            else:
                local = [(self._local_base, m, auth) for m in self.local_models]
        return (local + cloud) if self.prefer_local else (cloud + local)

    async def complete(self, messages, model=None):
        targets = self._target_chain(model)
        logger.info("LLM Complete: targets=%s", targets)
        last_error = None
        client = self._get_client()
        for base_url, m, auth in targets:
            for attempt in range(self.max_retries):
                try:
                    pool_key = self.key_pool.get_key() if auth == "pool" else None
                    headers = {"Content-Type": "application/json"}
                    if auth == "pool" and pool_key: headers["Authorization"] = f"Bearer {pool_key.key}"
                    elif auth == "local_bearer": headers["Authorization"] = f"Bearer {self._local_api_key}"
                    
                    response = await client.post(f"{base_url}/chat/completions", headers=headers, 
                                               json={"model": m, "messages": messages}, timeout=self.timeout)
                    if response.status_code == 404 and "local" in base_url:
                        # Maybe it's Ollama but without /v1?
                        logger.warning("Local LLM 404, trying without /v1 suffix")
                        response = await client.post(f"{base_url.replace('/v1','')}/api/generate", 
                                                   headers=headers, json={"model": m, "prompt": messages[-1]['content'], "stream": False})
                    
                    response.raise_for_status()
                    if pool_key: self.key_pool.mark_success(pool_key)
                    data = response.json()
                    
                    # Handle both OpenAI and Ollama native formats
                    if "choices" in data:
                        content = data["choices"][0]["message"]["content"]
                        usage = data.get("usage") or {}
                        tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
                    else:
                        content = data.get("response", "")
                        tin, tout = 0, 0
                        
                    self.total_calls += 1; self.total_tokens_in += tin; self.total_tokens_out += tout
                    self.calls_per_model[m] = self.calls_per_model.get(m, 0) + 1
                    return content
                except Exception as exc:
                    last_error = exc; self.total_errors += 1
                    self.errors_per_model[m] = self.errors_per_model.get(m, 0) + 1
                    logger.warning("  Model %s failed: %s", m, exc)
                    if pool_key and isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 400:
                        self.key_pool.mark_failed(pool_key)
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(min(self._backoff_base**attempt, 8))
        raise RuntimeError(f"All models failed. Last error: {last_error}")

    async def close(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.aclose()
            except Exception:
                pass
        self._clients.clear()

    def usage_snapshot(self):
        return {"total_calls": self.total_calls, "total_tokens": self.total_tokens_in + self.total_tokens_out,
                "total_tokens_in": self.total_tokens_in, "total_tokens_out": self.total_tokens_out,
                "total_errors": self.total_errors,
                "calls_per_model": dict(self.calls_per_model), "errors_per_model": dict(self.errors_per_model),
                "models": self.models, "local_models": self.local_models, "prefer_local": self.prefer_local,
                "model_aliases": dict(self._model_aliases)}
