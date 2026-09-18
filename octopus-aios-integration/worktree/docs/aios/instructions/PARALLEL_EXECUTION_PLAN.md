# PARALLEL_EXECUTION_PLAN — Octopus

## Принципы
1. **Bounded Waves:** Каждое действие ограничено во времени и ресурсах.
2. **Consent First:** Любое изменение инфраструктуры требует подтверждения.
3. **Verify Everything:** Запуск тестов после каждой правки.

## Распределение потоков (Агенты/Роли)
- **Role: Memory Lead** (Поток A1) — Фокус на CAS, Packstore, Durability.
- **Role: MCP Architect** (Поток A2) — Фокус на Skills, MCP, Marketplace.
- **Role: Swarm Master** (Поток A3, A7) — Фокус на узлах, размножении, Free-tier.
- **Role: Intelligence Analyst** (Поток A4, A5) — Фокус на RAG, Audio, People Graph.
- **Role: Ops/Security** (Поток A6, A9) — Фокус на мониторинге, хаос-тестах, защите.

## Инструменты координации
- **Master TODO:** Центральный файл прогресса.
- **Logs:** Каждая роль ведет свой лог итерации в ~/agents/-Octopus/logs/.
- **Experience:** Ключевые выводы в ~/agents/-Octopus/experience/.
