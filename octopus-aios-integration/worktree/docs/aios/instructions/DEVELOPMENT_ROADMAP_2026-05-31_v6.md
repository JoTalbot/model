# Octopus Development Roadmap v6 — 2026-05-31

Контекст: система в идеале (SMOKE 40/0/0, SLO green, Coverage 1.0, NRestarts=0,
14/14 tests, parallel-50 50/0). Ошибок нет. Развитие идёт по приоритетам инструкции #11:
**ПАМЯТЬ > ЖИТЬ > УПРОЩЕНИЕ > СОСУЩЕСТВОВАНИЕ > безопасность > остальные векторы**.
Соблюдается #13: никаких внешних/платных нод, никаких неконтролируемых автопетель,
каждый шаг = бэкап → правка → проверка → лог.

## Независимые потоки (можно вести параллельно)

### ПОТОК A — ПАМЯТЬ / Durability (приоритет №1)
- A1. Plain-text ops summary endpoint `/cas/ops/summary.txt` + `octopus summary`  ✅ (этот сеанс)
- A2. Packstore GC loose (safe, dry-run + manual confirm, pack+3 копии) — backlog
- A3. Pack-aware replicator (репликация pack, не только loose) — backlog
- A4. Backup-restore drill на чистом контейнере + weekly timer — частично есть, расширить
- A5. Manifest equality across S3/EC2/Garage — мониторинг активен

### ПОТОК B — ЖИТЬ / Observability & SLO
- B1. machine-readable `/run/octopus/slo_status.json` — есть
- B2. Свежий parallel-50 прогон при каждом крупном изменении  ✅ (этот сеанс)
- B3. Контроль orphan/NRestarts/портов (#07) каждую итерацию  ✅
- B4. Alерты в TG при SLO red / coverage<1.0 — активны

### ПОТОК C — УПРОЩЕНИЕ
- C1. Единая точка входа `octopus` CLI — расширена командой `summary`  ✅
- C2. Сократить legacy-скрипты, объединять дубли — постоянный фон
- C3. Один путь запуска детей через systemd — выполнено ранее

### ПОТОК D — СОСУЩЕСТВОВАНИЕ
- D1. CPU/RAM лимиты на сервисах, loopback-only кроме туннеля — выполнено
- D2. Нет конфликтов портов — проверяется (#07)
- D3. Кооперация с чужими нодами через реестр — backlog

### ПОТОК E — БЕЗОПАСНОСТЬ / ДОСТУП
- E1. ACL groups (`X-Acl-Allow-Group`) — backlog
- E2. Запрет streaming+encrypt footgun — выполнено
- E3. Секреты mode 600, токены без утечек — проверяется

### ПОТОК F — UI/UX и мобильный доступ
- F1. TG bot: команда `/summary` (plain-text ops)  → этот сеанс
- F2. XHR progress upload, audit browser — backlog
- F3. PWA/Termux QR polish — выполнено ранее

## Пошаговый план ближайшей волны (WAVE-19.x, выполнено в этом сеансе)
1. ✅ Бэкап CAS API
2. ✅ Добавить endpoint `/cas/ops/summary.txt` (read scope), py_compile, restart, smoke
3. ✅ Добавить `octopus summary` в мастер-CLI, bash -n
4. ✅ Прогнать `octopus test` (14/14)
5. → Добавить `/summary` в TG-бота
6. → Свежий parallel-50, фиксация
7. → Логи + experience + COMPACT_CONTEXT update

## Backlog (следующие волны, требуют подтверждения по рискам)
- Pack algorithm benchmark zstd/brotli — только dry-run, без переключения prod
- GC loose — manual confirmation required (удаление данных = риск)
- ACL groups UI
- Named Cloudflare Tunnel — только после предоставления CF домена пользователем
- Любое расширение на внешнюю инфраструктуру (#08/#09/#13) — ТОЛЬКО по явной команде
