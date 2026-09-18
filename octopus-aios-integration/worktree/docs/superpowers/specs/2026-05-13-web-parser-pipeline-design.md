# Web Parser Pipeline — Design Spec

## Overview

Production-oriented web parsing for the Immortal Swarm: a **pipeline** that resolves URLs (direct or via search), fetches HTML, extracts text with `selectolax`, and structures offers (name, price, shop, URL, stock) via LLM into JSON plus a human-readable summary. Integrates as a **CLI command** and as a **real tool** for the parser agent in multi-agent chat. Optional persistence to distributed memory is **opt-in** via `--save`.

## Goals

- Support **direct URL** input and **free-text query** input (search → top-N URLs).
- Return **combo output**: structured `ParsedItem` list (JSON) + readable table/summary.
- **Resilient** to timeouts, blocks, empty pages, and LLM parse failures (never crash the CLI; degrade gracefully).
- **Do not** hardcode per-site CSS templates in v1 (YAGNI); pipeline stays generic.

## Non-goals (v1)

- CAPTCHA solving, authenticated sessions, or headless browser rendering (JS-heavy SPAs may fail).
- Legal/compliance review of target sites; operators obey robots.txt and local law (document in README only).

## Architecture

```
Input (URL | query)
    → Resolver (optional search: Yandex → DuckDuckGo HTML fallback)
    → list[url]
    → Fetcher (httpx, UA rotation, limits)
    → Extractor (selectolax text → truncate → LLM → JSON)
    → ParseResult (per URL) + merged CLI view
```

### Data models (`swarm/parser/models.py`)

- `ParsedItem`: `name: str`, `price: str | None`, `currency: str | None`, `shop: str | None`, `url: str | None`, `in_stock: bool | None`
- `ParseResult`: `source_url: str`, `items: list[ParsedItem]`, `raw_text_excerpt: str`, `errors: list[str]`, `fetched_at: float` (epoch)

### Resolver (`swarm/parser/resolver.py`)

- **Primary:** `https://yandex.ru/search/?text={query}` — parse organic result links with `selectolax`; filter to `http(s)`; skip yandex/google/ddg internal links; dedupe; return first `limit` URLs (default 3).
- **Fallback:** `https://html.duckduckgo.com/html/?q={query}` — parse result links similarly if primary yields zero links or repeated HTTP errors (403/captcha patterns logged, no throw).
- **User-Agent:** rotate across a small static list of browser-like strings per request.

### Fetcher (`swarm/parser/fetcher.py`)

- `httpx.AsyncClient` with `follow_redirects=True`, per-URL timeout **15s**, max response body **500 KB** (truncate read if needed).
- On non-2xx: record error string on `ParseResult.errors`, skip body.
- **Polite delay:** `await asyncio.sleep(1)` between sequential fetches in a batch.

### Extractor (`swarm/parser/extractor.py`)

- Input: `html`, `source_url`, `llm: LLMRouter`.
- `selectolax` body text; truncate to **4000 characters** for LLM input (same order of magnitude as current `WebParserSkill`).
- Prompt instructs model to return **only JSON** matching:

```json
{
  "items": [
    {
      "name": "string",
      "price": "string or null",
      "currency": "string or null",
      "shop": "string or null",
      "url": "string or null",
      "in_stock": true | false | null
    }
  ]
}
```

- If JSON invalid: `items=[]`, append `"llm_json_parse_failed"` to `errors`, keep `raw_text_excerpt`.

### Orchestrator (`swarm/parser/pipeline.py`)

- `WebParserPipeline(llm, resolver, fetcher, extractor)`.
- `async def run(input: str, *, search: bool, limit: int) -> list[ParseResult]`:
  - If `search` false and `input` looks like URL (scheme `http`/`https`) → single URL list.
  - If `search` false and not URL → `click.ClickException` with hint to pass `--search` or a full URL.
  - If `search` true → resolver returns up to `limit` URLs.
- For each URL: fetch → extract; collect `ParseResult` list.
- Never raise on single-URL failure; aggregate errors in each result.

## CLI (`node.py`)

New command:

```text
python node.py parse <input> [--search] [--limit N] [--json] [--save]
```

- `--search`: treat `<input>` as query string; otherwise expect URL unless input parses as URL.
- `--limit`: default **3**, max **10** (hard cap to avoid abuse).
- `--json`: print machine-readable JSON (list of `ParseResult` serialized to dicts).
- `--save` (optional persistence): store a **single** `MemoryBlock` per invocation (msgpack metadata + JSON bytes) with tags `["parse", "autoglass", "<slug-from-input>"]` using an **ephemeral** in-process `KademliaNode` on a random localhost port (start → store → stop), reusing existing `DistributedMemory` + `ErasureCoder` from config defaults. If storage fails, print warning and still print parse output (do not fail CLI).

Human-readable default output: header per `source_url`, ASCII table (no emoji required for Windows), summary line with item counts.

## Chat integration

- Extend `WebParserSkill` to delegate to `WebParserPipeline` with `search=False` when message contains explicit URL(s), and `search=True` when the agent’s user message is a product query without URL (heuristic: presence of `http` substring → URL mode).
- Parser agent `system_prompt` in `config.yaml` should state: use only data returned by the tool; if pipeline returns empty items, say so honestly.
- Optional `tools: ["web_parser"]` in agent YAML is **documentation only** in v1 unless we add explicit tool-calling; implementation v1: **hard-wire** parser participant name `"parser"` to call pipeline before LLM reply when user message matches price-finding intent **or** always for parser agent (simplest): **always** run pipeline once per parser turn with the **latest user goal string** from chat history (last user message in room). Document this behavior in spec to avoid surprise latency.

**Refinement (explicit):** For v1 chat wiring, when `ChatRoom` selects agent `parser`, before `AgentParticipant.respond`, prepend a **synthetic user message** or inject into prompt: results of `WebParserPipeline.run(last_user_text, search=not _looks_like_url(last_user_text), limit=3)` serialized to compact bullet text. If pipeline returns all errors, inject `"[PARSE] No usable results: ..."` so the LLM does not hallucinate prices.

## Configuration (`config.yaml`)

New optional section:

```yaml
parser:
  fetch_timeout_seconds: 15
  max_response_bytes: 524288
  max_urls_per_query: 10
  llm_text_max_chars: 4000
  polite_delay_seconds: 1
```

Defaults apply if section missing.

## Security and ops

- **Secrets:** never commit real API keys; prefer env substitution in a later iteration; for now keep keys only in local `config.yaml` gitignored or user-managed.
- **Rate:** cap `--limit` at 10; sequential fetch with delay.

## Testing

- Unit tests: resolver HTML fixtures (saved minimal HTML snippets) → extracted URLs; fetcher with `httpx.MockTransport`; extractor with mocked LLM JSON good/bad; pipeline merges errors.
- Integration test (optional, network off): pipeline with resolver stub returning one `file://` or raw HTML string path **not** used — instead mock resolver returning `https://example.com` + mock fetcher returning static HTML fixture.

## Future

- Per-site extractor templates; Playwright for JS pages; robots.txt guard; caching layer.
