# ПОДРОБНЫЙ ПЛАН И РОАДМАП РАЗВИТИЯ ПРОЕКТА OCTOPUS
**Дата:** 2026-06-19  
**Версия:** v1.0 — Полный, детальный, готовый к запуску (НЕ запускаем)  
**Статус проекта:** 20 SKILL.md + progressive loader + MCP daemon + marketplace + swarm integration (S01-S10 завершены)  
**Текущие метрики (live):** pack_read_guard 20/20, SLO green, disk ~76%, 20 skills  
**Приоритеты (строго):** ПАМЯТЬ (V8) > ЖИТЬ (V5) > УПРОЩЕНИЕ (V7) > СОСУЩЕСТВОВАНИЕ (V6)  
**Правила:** Bounded waves, consent gates, cost-free/free-tier only, step-backups, Russian responses, no unsupervised loops.

## 1. ГЛОБАЛЬНАЯ ЦЕЛЬ (2026-2027)
**Максимально параллельное, децентрализованное, бессмертное развитие Octopus**  
- 1000+ нод (Hetzner free + Oracle Free + Fly.io + локальные + Pi)  
- 200+ SKILL.md (per-skill exhaustive)  
- Полный MCP + marketplace + self-evolving meta-skills  
- Immortal memory (CAS + pack replication + eternal snapshots + CRDT)  
- Полная автономность (reproduction, autoheal, coexistence)  
- Chaos resilience (BFT-lite, weekly tests)  
- Zero-cost scale (free-tier + P2P + Nostr/Matrix federation)

## 2. ФАЗЫ РОАДМАПА (bounded waves, 2-4 недели на фазу)

### ФАЗА 0 — ГОТОВНОСТЬ К СТАРТУ (уже почти сделано, 1-3 дня)
**Цель:** Полная документация + готовность к параллельному запуску  
**Todo (детально):**
- [ ] Обновить COMPACT_CONTEXT.md + VINTIKI + all ROADMAPs (текущий статус 20 skills + MCP)
- [ ] Создать MASTER_TODO_2026-06-19.md (этот документ + детальные под-таски)
- [ ] Создать PARALLEL_EXECUTION_PLAN.md (список параллельных потоков, ролей, инструментов)
- [ ] Создать CONSENT_GATES.md (все human_consent.env + approval flows)
- [ ] Создать FREE_TIER_INVENTORY.md (все бесплатные ресурсы: Oracle, Fly, Hetzner, GitHub, Nostr, Arweave, IPFS)
- [ ] Создать THIRD_PARTY_NODES.md (список готовых бесплатных/дешёвых нод + интеграция)
- [ ] Создать SKILL_MARKETPLACE_V2.md (улучшенный индекс + версионирование + GitHub marketplace)
- [ ] Обновить experience/ + master index для 20+ скиллов
- [ ] Bounded verify: packguard 20/20 + SLO + disk + health.json + 20 skills activation test
- [ ] Создать launch-ready scripts (но НЕ запускать): launch_mcp_daemon.sh, swarm_start_with_skills.sh, chaos_test.sh

**Параллельно (можно 3-4 человека/агента):**
- 1 поток: документация
- 2 поток: inventory free-tier + third-party
- 3 поток: обновление 20 SKILL.md + RESEARCH
- 4 поток: планирование параллельных волн

### ФАЗА 1 — ПАРАЛЛЕЛЬНЫЙ ЗАПУСК ЯДРА (1-2 недели, максимум параллелизма)
**Цель:** 50+ нод + 50+ skills + full MCP live + первые reproduction  
**Параллельные потоки (до 8-12 одновременно, bounded):**

**Поток A1 (ПАМЯТЬ — приоритет #1):**  
- CAS v3 (pack-aware replication + CID + ComposeFS layer)  
- pack-replication-guard skill + daemon  
- Eternal snapshot v2 (HF + Arweave + IPFS CAR)  
- Memory-immortal-guard + CRDT overlay (yjs или pure Python CRDT)  
- 3-4 bounded waves (S101-S104)

**Поток A2 (MCP + Marketplace + Self-evolving):**  
- Full MCP server (FastMCP / stdio + HTTP + RPC bridge)  
- Skills Over MCP (SEP-2076) — skills as first-class primitive  
- Marketplace v2 (GitHub + Nostr + self-host) + auto-install + versioned .skill  
- Meta-skill-creator v2 + universal-loader-guard + self-evolution loop  
- 3 bounded waves

**Поток A3 (Swarm + Reproduction + Coexistence):**  
- SwarmKit / libp2p integration (GossipSub + Kademlia enhancements)  
- Reproduction pipeline (consent-gated, eternal bootstrap, child nodes)  
- Coexistence guard (cgroups, ports, multi-tenant, Nostr/Matrix federation)  
- Autoheal + reputation + BFT-lite  
- 4 bounded waves

**Поток A4 (Audio / Voice / People Graph):**  
- VoxRAG 2025 (CLAP + diarization + ECAPA)  
- Full voice-RAG skill + people-graph-octopus v2  
- Remote Whisper workers (multiple free tiers)  
- 2 bounded waves

**Поток A5 (RAG / GraphRAG / Vectors):**  
- GraphRAG + pgvector + HNSW + hybrid retrieval  
- rag-hybrid + context-optimization skills  
- 2 bounded waves

**Поток A6 (Observability + Chaos + DR):**  
- SLO guardian v2 + chaos weekly tests (kill 30% nodes)  
- Eternal DR + bootstrap + off-host verification  
- Alerts + TG + Grafana  
- 2 bounded waves

**Поток A7 (Free-tier + Third-party nodes — максимум параллелизма):**  
- Oracle Free (2-3 always-free)  
- Fly.io free tier + multiple regions  
- Hetzner CX (если бюджет 0 — только free)  
- Raspberry Pi / локальные + Tailscale / ZeroTier  
- GitHub Actions runners (free) + self-hosted  
- Nostr relays + Matrix homeservers (federation)  
- Arweave / Filecoin / IPFS pinning (free tiers)  
- 5-6 параллельных bounded waves (одновременно)

**Поток A8 (Per-skill exhaustive + 50+ skills):**  
- Продолжить per-skill research для каждого нового скилла  
- 30+ новых SKILL.md (из Orchestra, psenger, ruvnet, superpowers, custom Octopus)  
- Автоматический генератор SKILL.md (skill-creator)  
- 8-10 bounded waves

**Поток A9 (Security + Coexistence + Consent):**  
- age + ACL + scoped tokens + rate-limit  
- human_consent.env + cgroups + fail2ban  
- Coexistence guard + multi-tenant  
- 2 bounded waves

**Поток A10 (UX + Docs + Onboarding):**  
- TG bot + PWA + Next Admin + Obsidian export  
- Полная документация + ROADMAP + tutorials  
- 2 bounded waves

### ФАЗА 2 — МАСШТАБ + АВТОНОМИЯ (2-4 недели)
**Цель:** 200+ нод + 150+ skills + full self-reproduction + BFT  
**Параллельные потоки (10-15 одновременно):**
- A1-A10 продолжаются + новые:
- B1: Byzantine fault tolerance (threshold signatures + CRDT)
- B2: Full P2P federation (Nostr + Matrix + libp2p)
- B3: Auto-scaling + cost-free orchestration (Kubernetes-free, simple scripts)
- B4: 100+ skills (включая research/ML/AI skills из Orchestra)
- B5: Chaos engineering platform (weekly automated tests)
- B6: Third-party node marketplace (anyone can add free node)
- B7: Full immortal memory (Merkle + verifiable snapshots + Arweave anchors)
- B8: Self-evolving meta-system (agent creates agents + skills)

### ФАЗА 3 — ЭКОСИСТЕМА (1-3 месяца)
**Цель:** 1000+ нод + 300+ skills + экономика + глобальная сеть  
- Token / reputation economy (опционально, только если consent)
- Public marketplace + paid skills (опционально)
- Integration with LocalAI, Ollama swarm, rUv harnesses
- Full open-source + community contributions
- Global chaos resilience + DR

## 3. МАКСИМАЛЬНО ПАРАЛЛЕЛЬНЫЙ ЗАПУСК (ПЛАН)

**Принцип:** Bounded waves + human consent gates + free-tier only  
**Максимум параллельных процессов:** 12-15 одновременно (ограничено consent + free resources)  
**Инструменты для параллелизма:**
- GitHub Projects / Issues (один большой проект + 12+ меток/милстоунов)
- Multiple agents (Claude Code + Cursor + Codex + local) — каждый на своём потоке
- GitHub Actions (free) — CI для каждого bounded wave
- Nostr/Matrix channels для координации
- Simple bash scripts + tmux/screen для локальных параллельных агентов

**Структура параллельных потоков (пример на старте):**
1. ПАМЯТЬ (A1) — 3-4 агента
2. MCP + Marketplace (A2) — 2 агента
3. Swarm + Reproduction (A3) — 2 агента
4. Audio/Voice (A4) — 1 агент
5. RAG (A5) — 1 агент
6. Free-tier + Third-party (A7) — 3-4 агента (самый параллельный)
7. Per-skill research (A8) — 2-3 агента
8. Security/Coexistence (A9) — 1 агент
9. UX/Docs (A10) — 1 агент
10. Chaos/Observability (A6) — 1 агент

**Bounded wave правило для каждого потока:**
backup → edit → verify (octopus test + packguard + SLO + health) → log → consent gate → next wave

**Third-party free / low-cost ноды (список для старта):**
- Oracle Cloud Always Free (2-3)
- Fly.io free tier (несколько apps)
- Hetzner (если бюджет >0 — CX11)
- Raspberry Pi 4/5 + SD + powerbank
- Старые ноутбуки / VPS с /bin/bash trials
- GitHub Codespaces / Actions runners
- Tailscale / ZeroTier mesh
- Nostr relays (public)
- Matrix homeservers (public или self)
- Arweave bundlers (free)
- IPFS pinning services (free tiers)

**Роли в параллельной команде (можно назначать агентам):**
- Memory Lead (ПАМЯТЬ)
- Swarm Lead
- MCP / Skills Lead
- Free-tier Hunter (самый важный для старта)
- Research Lead (per-skill)
- Chaos / DR Lead
- Docs / UX Lead
- Consent Gate Keeper (human)

## 4. ДЕТАЛЬНЫЙ TODO (первые 30 дней — максимально параллельно)

**Неделя 1 (Фаза 0 + старт Фазы 1):**
- Документация (ROADMAP, MASTER_TODO, FREE_TIER, THIRD_PARTY, CONSENT)
- Обновить 20 существующих SKILL.md + RESEARCH
- Создать MCP daemon launch script + runtime patch (bounded)
- Зарегистрировать 5-7 free-tier аккаунтов (Oracle, Fly и т.д.)
- Начать 3-4 bounded waves параллельно (A1, A2, A7, A8)

**Неделя 2:**
- 30+ новых SKILL.md
- 15-20 free-tier нод запущено (bounded waves)
- Full MCP live + marketplace v1
- Первые reproduction (1-2 child nodes)
- Chaos test #1

**Неделя 3-4:**
- 50+ нод
- 80+ skills
- Полная immortal memory (pack replication + eternal)
- Coexistence + federation (Nostr/Matrix)
- Weekly chaos + DR drill

## 5. РИСКИ + МИТИГАЦИЯ
- Consent gates на каждый provisioning
- Cost-free только (никаких платных без явного согласия)
- Bounded waves + verify после каждого изменения
- Third-party ноды — только через consent + health check
- No unsupervised autoloops (#13)
- Все изменения через step-backup + experience

## 6. ГОТОВНОСТЬ К СТАРТУ (чек-лист)

**Документы (готовы после этого планирования):**
- [ ] ROADMAP_OCTOPUS_2026-06-19.md (этот)
- [ ] MASTER_TODO_2026-06-19.md
- [ ] PARALLEL_EXECUTION_PLAN.md
- [ ] FREE_TIER_INVENTORY.md
- [ ] THIRD_PARTY_NODES.md
- [ ] CONSENT_GATES.md
- [ ] SKILL_MARKETPLACE_V2.md
- [ ] All existing research docs обновлены

**Скрипты (созданы, но НЕ запущены):**
- launch_mcp_daemon.sh
- swarm_start_with_skills.sh
- chaos_test.sh
- free_tier_bootstrap.sh
- skill_install_from_marketplace.sh

**Состояние live (проверить перед стартом):**
- 20+ skills + loader + MCP + marketplace
- pack_read_guard 20/20
- SLO green
- Все backups + experience

**Когда можно стартовать:**
1. Все документы выше готовы
2. Human consent на первую волну (Фаза 0 + первые bounded waves)
3. Минимум 3-4 параллельных агента/человека готовы
4. Free-tier аккаунты подготовлены

**НЕ ЗАПУСКАТЬ** ничего без явного согласия в следующем сообщении.

**Конец плана. Готов к старту после согласия.**
