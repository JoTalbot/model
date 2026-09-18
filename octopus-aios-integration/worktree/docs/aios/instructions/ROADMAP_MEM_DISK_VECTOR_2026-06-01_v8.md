# Roadmap: Память / Диск / Векторизация / Зависимости данных (v8) — 2026-06-01
Приоритеты #11: ПАМЯТЬ > ЖИТЬ > УПРОЩЕНИЕ > СОСУЩЕСТВОВАНИЕ. #13: ограниченный проверяемый набор.

## Текущее состояние (baseline)
- Диск 76% (8.9G free). docker 5.6G, whisper.cpp 2.1G, ingest-venv 1.5G, octopus 1.3G.
- CAS: loose 20336 = pack 20332 (4 only-loose). GC может освободить ~115MB.
- Векторы: 127 (мало!), pgvector 0.8.2 УСТАНОВЛЕН но extension не CREATE'нут в app_db, НЕТ ANN-индекса.
- Зависимости: ingest topics=6 tasks=2 transcr=6 — слабая связность.

## 4 НЕЗАВИСИМЫХ ПОТОКА (параллельно)

### ПОТОК A — ДИСК (УПРОЩЕНИЕ/coexistence)
A1. Safe GC loose (pack+S3+EC2+offhost подтверждены) → ~115MB, поэтапно с проверкой чтения
A2. docker image prune (dangling), journal vacuum, pip/apt cache
A3. whisper.cpp: убрать build-артефакты/лишние модели если есть дубли
A4. Отчёт экономии

### ПОТОК B — ВЕКТОРИЗАЦИЯ (ПАМЯТЬ, главный upside)
B1. CREATE EXTENSION vector в app_db (idempotent)
B2. ANN-индекс (HNSW) на octopus_vectors.embedding → быстрый семантический поиск
B3. Бэкфилл векторов: проиндексировать НЕохваченные CAS-объекты/agent_memory (расширить со 127)
B4. Self-test векторного поиска (latency до/после индекса)

### ПОТОК C — ПАМЯТЬ/CAS DURABILITY
C1. Догнать pack: 4 only-loose объекта запаковать (all_in_pack → true)
C2. pack-read guard расширенный прогон
C3. После GC — повторная проверка off-host/DR/coverage

### ПОТОК D — ЗАВИСИМОСТИ ДАННЫХ (новое)
D1. Граф зависимостей: связать transcriptions↔topics↔tasks↔people (foreign refs audit)
D2. Найти orphan-записи (transcr без upload, task без topic, vector без source)
D3. Индексы на FK-колонки для скорости join
D4. Отчёт целостности связей

## Метрики успеха
- Диск: освободить >100MB · Векторы: ANN-индекс + рост покрытия · pgvector extension active
- octopus test 16/16 · SLO green · 0 orphan-записей критичных · все потоки проверены

## Безопасность (#13)
Каждый шаг: бэкап→правка→проверка→лог. GC только после подтверждения 3+ копий чтением.
Без удаления данных без верификации. Без новых трат/нод.
