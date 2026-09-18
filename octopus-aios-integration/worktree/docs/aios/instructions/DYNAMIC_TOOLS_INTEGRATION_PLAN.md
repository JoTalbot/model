# ПОДРОБНЫЙ ПЛАН ИНТЕГРАЦИИ DYNAMIC TOOLS (Bounded Waves)

## Текущий статус (2026-06-19)
- 52 SKILL.md (включая все динамические)
- policy-engine + mode-manager + desired-state configs созданы
- development-mode работает по описанию пользователя

## План интеграции (НЕ ЗАПУСКАЕМ — только подготовка)

### Wave D1 (Подготовка runtime)
- Добавить в swarm/runtime.py и plugins загрузку:
  - dynamic-tool-orchestrator
  - capability-registry
  - script-deployer
- Создать /run/octopus/dynamic_state/ директорию
- Сделать tool-desired-state доступным через MCP

### Wave D2 (Development Mode полноценный)
- Реализовать development-mode-guard полностью
- Подключить к mode-manager
- Создать удобный триггер в development-mode
- Протестировать локально (bounded)

### Wave D3 (Script Deployer)
- Реализовать базовый script-deployer (Python + systemd + docker stubs)
- Добавить поддержку install/uninstall/start/stop
- Интеграция с consent-orchestrator

### Wave D4 (Capability + Advertising)
- node-capability-advertiser как периодический процесс
- capability-registry с простым хранилищем
- Синхронизация через dynamic-capability-sync

### Wave D5 (Scheduling)
- load-aware-scheduler (простая версия)
- resource-demand-evaluator (простая версия на основе режимов)
- policy-engine (базовые правила)

### Wave D6 (Полная интеграция + тесты)
- Связать всё вместе через dynamic-tool-orchestrator
- Добавить bounded тесты переключения режимов
- Документация + примеры
- Подготовка к запуску (но не запуск)

### Wave D7 (Chaos + Production readiness)
- Тестирование переключения режимов при падении нод
- Интеграция с self-healing и reproduction
- Полная федерация через p2p-federation

## Порядок запуска (только после явного согласия)
1. D1 → verify
2. D2 (development mode) → verify
3. D3 + D4 → verify
4. D5 + D6 → verify
5. D7 (chaos) → verify
6. Постепенное включение на реальных нодах

Все волны — bounded + verify + consent gate.
