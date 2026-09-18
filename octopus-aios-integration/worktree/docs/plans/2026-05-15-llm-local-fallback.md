# Local LLM Fallback — Plan & Implementation

## Status: ✅ Fully Implemented

## Goal

Give the node the ability to work without any external API when a local model is available.

## Solution (implemented)

- **Interface:** HTTP, OpenAI-compatible `POST …/chat/completions` (e.g. [llama.cpp server](https://github.com/ggerganov/llama.cpp/blob/master/examples/server/README.md), [Ollama](https://ollama.com), [vLLM](https://docs.vllm.ai), [LM Studio](https://lmstudio.ai)).
- **Config:** `llm.local` block in `config.yaml` (see README.md for full examples): `enabled`, `base_url`, `models`, optionally `prefer_local`, `api_key`, `model_aliases`.
- **Behavior:** `LLMRouter` builds a target chain — by default cloud first (`llm.base_url` + `llm.models`), then local; with `prefer_local: true` — reversed. Empty `llm.models` is allowed if `local` is enabled with non-empty `models`. Without OpenRouter keys the node starts if `local` is fully configured (a placeholder key pool is created internally).
- **Model Aliases:** `llm.local.model_aliases` maps cloud model names (e.g. `meta-llama/llama-3.3-70b-instruct`) to local model names (e.g. `llama-3.3-70b`). This allows the same agent configs to work both online and offline. Aliases are only applied to local targets — cloud targets always use original names.
- **Tests:** `tests/test_router.py` — 13 tests including alias resolution, fallback chain, prefer_local, and auth header behavior. All mocked, no network.

## Configuration examples

### Local-only (no cloud keys)

```yaml
llm:
  keys: []
  models: []
  local:
    enabled: true
    base_url: "http://127.0.0.1:8080/v1"
    models: ["llama-3.3-70b"]
    prefer_local: true
```

### Hybrid with aliases

```yaml
llm:
  keys: ["sk-or-v1-YOUR-KEY"]
  models: ["anthropic/claude-sonnet-4-20250514", "meta-llama/llama-3.3-70b-instruct"]
  local:
    enabled: true
    base_url: "http://127.0.0.1:8080/v1"
    models: ["llama-3.3-70b"]
    prefer_local: false
    model_aliases:
      "meta-llama/llama-3.3-70b-instruct": "llama-3.3-70b"
      "anthropic/claude-sonnet-4-20250514": "llama-3.3-70b"
      "x-ai/grok-3": "llama-3.3-70b"
```

## Server setup (quick reference)

### llama.cpp

```bash
llama-server -m model.gguf --host 127.0.0.1 --port 8080 -c 8192 -ngl 99
```

### Ollama

```bash
ollama pull llama3.3:70b
# auto-starts on port 11434
```

### vLLM

```bash
python -m vllm.entrypoints.openai.api_server \
    --model meta-llama/Llama-3.3-70B-Instruct \
    --host 127.0.0.1 --port 8000
```

## Fallback chain

```
prefer_local=false (default):
  Cloud: openrouter.ai → original-model-name (max_retries attempts)
  Local: 127.0.0.1:8080 → aliased-name (max_retries attempts)

prefer_local=true:
  Local first → Cloud as fallback
```

## Implementation details

- `LLMRouter.__init__` accepts `model_aliases: dict[str, str] | None`
- `_resolve_alias(model)` maps cloud → local names (identity if no alias)
- `_local_targets()` applies alias resolution when `explicit_model` is set
- `_cloud_targets()` never applies aliases (cloud names stay original)
- `LocalLLMConfig` in `swarm/config/llm.py` has `model_aliases: dict[str, str]`
- `_llm_local_router_kwargs()` in `swarm/cli.py` passes aliases to `LLMRouter`
- `usage_snapshot()` includes `model_aliases` for observability

## Future enhancements (optional)

- Per-agent model overrides (different local models for parser vs analyst)
- Auto-detect running local servers (probe common ports)
- Model download helpers (`gemaxi download llama-3.3-70b-q4`)
