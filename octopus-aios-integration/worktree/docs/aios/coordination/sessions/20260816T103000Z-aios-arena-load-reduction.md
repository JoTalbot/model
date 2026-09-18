---
session_id: "20260816T103000Z-aios-arena-load-reduction"
status: "DONE"
agent: "arena-agent (Arena.ai Agent Mode, внешний, SSH root@<PUBLIC_IP_REDACTED>)"
machine: "aios"
started_utc: "2026-08-16T10:30:00Z"
updated_utc: "2026-08-16T10:47:36Z"
branch: "agent/20260815-quant-oos-profit"
base_commit: "a819a4eb"
claim: "none (ops-задача без изменения кода)"
---

## Цель

Снизить хроническую перегрузку сервера (load 75–105 на 4 ядрах, SSH-обрывы) —
запрос владельца «Уменьшить нагрузку сервера», выбор сценария **D** в меню.

## Диагноз (на старте)

- Корневая причина — **memory thrash**: RAM 7.7 ГБ занята (available 39 МБ),
  swap 4032/4095 МБ, `kswapd0` накопил 7.4 часа CPU; LA считает R+D-стейты (10+10).
- Найден главный пожиратель: **9 осиротевших joblib-loky воркеров** hyperopt'а
  (PPID=1, от убитых OOM волн 04:59–05:56 UTC) держали **~1.65 ГБ** RSS.

## Действия

1. Убиты осиротевшие loky-воркеры (SIGTERM×9, PPID=1, родители-hyperopt мертвы)
   → −1.65 ГБ RSS мгновенно (available 39МБ→1.15ГБ).
2. `renice +10` фоновым демонам: run_market_data_collector, run_commercial_daemon
   (в контейнере), run_quant_trading ×2, mm_signal_emitter.
3. Stop+disable GUI-стек (снапшоты юнитов: `backups/systemd_20260815/*.loadreduction.bak`):
   `aios-viber-autoreply`, `aios-viber-desktop`, `aios-vnc-keepawake`,
   `aios-chrome-vnc`, `aios-signal-desktop` (все rc=0); + сессия GUI (session-961.scope
   terminated) и добит оставшийся `Xtigervnc :1`; `reset-failed` выполнен.
4. `docker stop aios-commercial aios-grafana aios-prometheus aios-alertmanager` (rc=0).

## Результат

- **Load: 75–105 → 0.8** (1-мин), 5-мин ~12 и падает.
- **Mem available: 39 МБ → 2363 МБ**; swap used 4032→3672 МБ (decay через kswapd,
  swapoff не делался сознательно — негативный RAM-запрос).
- Проверки: GUI/чроумиум-следы чисты; `is-enabled`=disabled, `is-active`=inactive ×5;
  9 docker-контейнеров остались лёгкими (<70 МБ каждый).

## Что теперь ВЫКЛЮЧЕНО (функциональные последствия — принято владельцем)

- Viber Desktop + viber-autoreply: автоответы Viber стоят.
- Signal Desktop: не работает.
- Chrome Google-Messages (9222/9223) + VNC-дисплей: SMS/Messages-автоматика стоит
  (run_sms_alerts будет фейлить проверки до возврата Chrome).
- aios-commercial (контейнер-демон, ~590 МБ совокупно): commercial-контур стоит.
- grafana+prometheus+alertmanager: дашборды и Prom-алерты недоступны; exporters
  (aios-exporter, telegram-exporter, canary) оставлены и лёгкие.

## Rollback (обратимо)

```
systemctl enable --now aios-viber-desktop aios-viber-autoreply \
  aios-vnc-keepawake aios-chrome-vnc aios-signal-desktop
docker start aios-commercial aios-grafana aios-prometheus aios-alertmanager
# X/VNC-дисплей поднимется при старте сервисов или новой GUI-сессии
```

## Побочные эффекты для quant-очереди

Guarded hyperopt (`data/freqtrade/hyperopt_run_guarded.log`) получает тихие окна
(load1≤14 теперь выполняется) — ожидается реальное выполнение 300-эпохочных прогонов.
Dry-бот T2 active; его ранний рестарт (~10:23) — следствие OOM-периода до чистки.

## Git

- Коммиты: b22d1e1a docs(ops): load reduction (journal + PROJECT_CONTEXT)
- Незакоммиченные изменения: `M catboost_info/*`, `?? backups/systemd_20260815/`
  (снапшоты юнитов внутри — намеренно вне git, по местной традиции ops-бэкапов).
