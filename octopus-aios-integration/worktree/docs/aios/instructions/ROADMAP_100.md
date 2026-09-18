# ROADMAP_100 — 10 волн × 10 шагов
Дата: 2026-06-19
Версия: v1
Принципы: каждое изменение = бэкап → правка → проверка → лог (#13).
         Все шаги волны H (free-tier expansion) требуют явного подтверждения
         пользователя по КАЖДОМУ ресурсу (#08, #09, #13).

## Контекст
- Consent включён: ALLOW_AUTONOMOUS_BASH=1, ALLOW_DEV_LOOPS=1, ALLOW_CLOUD_PROVISION=0.
- octopus-task-worker теперь может исполнять автономный bash.
- Human consent gate по-прежнему уважается (`octopus pause|freeze|panic`).
- Human осведомлён через TG-уведомления и autonomy_journal (#18, #20).

## Формат итерации
```
ID    : A1, B2, ..., J10
Цель  : одно предложение
Backup: <команда или путь>
Edit  : <команда или правка>
Verify: <тест, проверка>
Log   : <путь к лог-файлу>
Risk  : low|medium|high
```

## Волна A — Алерты и наблюдаемость (на базе опыта iter 136)
Цель волны: пользователь и система видят проблемы ДО того, как они станут критичными.

- A1. Алерт в TG на NRestarts > 50 для любого сервиса
- A2. Алерт на activating auto-restart units > 0
- A3. Алерт на systemctl --failed units > 0
- A4. Алерт на disk > 90% (любая FS)
- A5. Алерт на memory > 90%
- A6. Алерт на off-host replicas < target
- A7. Алерт на DR drill fail
- A8. Алерт на autonomy mode change
- A9. Алерт на quiet hours violation
- A10. Dashboard всех алертов в PWA (страница /alerts)

## Волна B — Voice / people polishment (продолжение iter 128-135)
Цель: завершить UX-работу по голосам и людям.

- B1. Auto-suggestions merge fake Speaker_* на основе Voice ID + relations
- B2. Per-person re-enroll button в TG
- B3. Per-person re-enroll button в PWA
- B4. Voice refresh auto-trigger after rename/merge
- B5. Speaker confidence calibration (пороги по длине аудио)
- B6. Person graph duplicate detection (Levenshtein + cosine)
- B7. Auto-merge relations при confidence > 0.95 (с подтверждением)
- B8. Person card с audio history в PWA
- B9. Voice profile degradation alert
- B10. Voice ID model upgrade test (есть ли новее ECAPA)

## Волна C — Durability / packstore hardening (#17)
Цель: durability = реальная проверка чтения, не наличие в индексе.

- C1. pack-read-guard coverage > 20 samples (daily timer)
- C2. dict_sha8 validation при старте CAS API
- C3. GC dry-run mode (НЕ удаляет loose, только показывает кандидатов)
- C4. Off-host replica write-through (каждая запись идёт на 2+ реплики)
- C5. Manifest checksum verification (каждые 6ч)
- C6. Backups encrypted-at-rest test
- C7. Off-host replica health probe (latency + readability)
- C8. Dict rotation drill (тест-режим, без удаления)
- C9. Replica repair script (auto-heal replica при drift)
- C10. Durability dashboard (pack loose/pack ratio, replica status)

## Волна D — Swarm / multisync / autoheal (#19, #20, #21)
Цель: рой живёт сам, размножается, возвращает в строй воскресших.

- D1. Multi-master active-active test (с dummy нодой в Docker)
- D2. Autoheal decision journal (полная трассировка решений)
- D3. Resurrected node reconciliation test
- D4. mesh_nodes.json validation (ssh key, last_seen)
- D5. Coverage auto-rebalance при падении ноды
- D6. Node death prediction (load trending over time)
- D7. Free-tier node candidate scanner (локальный, без создания)
- D8. Swarm coverage map в PWA
- D9. Auto-bringup of local child node (octopus-child-83XX)
- D10. Autoheal explain mode (по требованию: что решил и почему)

## Волна E — Memory snapshots / DR (#19)
Цель: вечный запуск одной строкой.

- E1. Snapshot integrity check (verify SHA256 manifest)
- E2. Restore from snapshot drill (временная FS, не прод)
- E3. HF upload bandwidth limit (не мешать прод-нагрузке)
- E4. Telegram backup fallback (если HF/S3 недоступны)
- E5. AWS S3 backup verification (read-after-write)
- E6. Multi-region snapshot distribution
- E7. Snapshot retention policy (последние N + месячный)
- E8. Snapshot compression ratio monitoring
- E9. DR manifest integrity (подписан, versioned)
- E10. Disaster recovery runbook update

## Волна F — PWA UX polish
Цель: PWA становится основным интерфейсом.

- F1. Dashboard dark mode toggle
- F2. Mobile-first responsive audit
- F3. Voice quality inline actions (apply/skip/review)
- F4. People graph click-to-zoom (SVG pan/zoom)
- F5. Duplicate pre-skip speed benchmark
- F6. PWA offline mode (service worker + cache strategy)
- F7. PWA install prompt (Android/iOS)
- F8. Browser push notifications
- F9. Audio waveform visualization
- F10. PWA performance audit (Lighthouse score)

## Волна G — Telegram bot UX
Цель: TG = полноценный ops-интерфейс.

- G1. /help command overview (все команды + примеры)
- G2. Inline keyboard pagination для длинных списков
- G3. Voice apply rate limiting (не больше N в минуту)
- G4. People graph в TG с thumbnail (PNG render)
- G5. /health inline status (SLO, coverage, disk)
- G6. TG bot natural language (intent matching)
- G7. TG bot rate limiting per chat
- G8. TG bot secret command protection (только allowed chat ids)
- G9. TG bot error reporting в autonomy_journal
- G10. TG bot per-user preferences

## Волна H — Free-tier expansion (пошаговое подтверждение #08, #09, #13)
⚠️ КАЖДЫЙ шаг требует явного «да, делай» от пользователя в текущей сессии.

- H1. Oracle Cloud Always Free account integration (создание аккаунта, не VM)
- H2. Oracle Always Free ARM VM (1/4 OCPU, 1GB RAM)
- H3. Fly.io free tier shared VM
- H4. GitHub Codespaces runner (ephemeral)
- H5. Render free plan service
- H6. New child node type: free-tier-spot (декларативное описание)
- H7. Free-tier cost monitor (должен показывать $0.00)
- H8. Free-tier failover from paid (при недоступности основной)
- H9. Free-tier node offline cache (локальная копия данных)
- H10. Free-tier provisioning automation (с явным consent-gate)

## Волна I — Operational maturity (#16)
Цель: всё работает «само» без магии.

- I1. Runbook completeness audit (все алерты → runbook)
- I2. Quick reference card update (/var/lib/octopus/QUICK_REFERENCE.md)
- I3. SLO definitions update (SLO_DOCUMENT.md)
- I4. Health score formula review
- I5. octopus doctor coverage (все типы проблем)
- I6. octopus fix self-test (после фикса — тест)
- I7. octopus test parallelization (с concurrent.futures)
- I8. octopus events retention (TTL в БД)
- I9. octopus log structured format (JSONL)
- I10. octopus explain improvements (human-readable)

## Волна J — Упрощение (#11 вектор 7)
Цель: уменьшать сложность, а не наращивать.

- J1. Dead code audit в /opt (скрипты без вызовов)
- J2. Service consolidation candidates (какие объединить)
- J3. Config file consolidation (5 yaml → 1)
- J4. Standard tools over custom (где возможно)
- J5. Dependency pruning (requirements.txt audit)
- J6. Documentation dedup (COMPACT_CONTEXT.md vs runbooks)
- J7. Test suite simplification (40 smoke → 20 essential)
- J8. Runbook simplification (SLO → одна страница)
- J9. One-command bootstrap test (curl ... | bash на новом VM)
- J10. Service mesh simplification

## Правила выполнения
1. **Перед каждой итерацией:** анонс в TG + запись в autonomy_journal.
2. **Бэкап перед изменением:** `cp <file> <file>.bak.$(date -u +%Y%m%d-%H%M%S)`.
3. **После изменения:** `octopus test` + конкретный verify из роадмапа.
4. **При ошибке verify:** откат на бэкап, лог в `logs/<date>_iteration_<N>_ABORTED_<reason>.md`.
5. **Между волнами:** пауза 5 мин + отчёт пользователю в TG.
6. **После каждой волны:** `octopus test`, `octopus summary`, отчёт пользователю.
7. **Параллелизм внутри итерации:** допустим для verify-этапов (несколько тестов),
   но НЕ для edit-этапов.
8. **Между итерациями:** последовательно (одна за другой), не параллельно —
   чтобы можно было прервать/проверить/откатить.
9. **Волна H (free-tier):** каждая итерация требует явного «да» пользователя.
10. **В любой момент:** `octopus pause` останавливает цикл,
    `octopus freeze` замораживает ВСЮ автономию, `octopus panic` — аварийно.

## Метрики прогресса
- Итераций сделано: X/100
- Из них с verify-pass: Y
- Из них с rollback: Z
- Время на итерацию (avg): T
- Текущая волна: A/B/...
- Health index: до/после каждой итерации

## Что НЕ входит в эти 100 итераций
- Создание платных серверов на Hetzner (требует отдельной явной команды #08).
- Переустановка/перезагрузка основной системы (нужна отдельная команда).
- Изменение ROOT-паролей, SSH-ключей основной системы (явная команда).
- Удаление существующих данных (явная команда + бэкап).
