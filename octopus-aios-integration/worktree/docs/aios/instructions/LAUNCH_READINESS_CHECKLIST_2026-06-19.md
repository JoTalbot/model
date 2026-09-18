# ЧЕК-ЛИСТ ПОЛНОЙ ПОДГОТОВКИ К ЗАПУСКУ (НЕ ЗАПУСКАЕМ)

## 1. Документация и планирование
- [ ] ROADMAP_OCTOPUS_2026-06-19.md актуален
- [ ] MASTER_TODO_2026-06-19.md обновлён
- [ ] DYNAMIC_TOOLS_INTEGRATION_PLAN.md прочитан и понятен
- [ ] LAUNCH_READINESS_CHECKLIST (этот файл) заполняется по мере готовности

## 2. Скиллы
- [ ] Минимум 50 SKILL.md на диске
- [ ] Все критичные скиллы (включая dynamic) имеют RESEARCH
- [ ] development-mode + policy-engine + desired-state configs присутствуют

## 3. Конфиги
- [ ] /root/agents/-Octopus/configs/desired-states/ содержит development, production, minimal, night
- [ ] /root/agents/-Octopus/skills/loader/skills_loader.py работает
- [ ] MCP stub/server файлы присутствуют

## 4. Скрипты (созданы, но не запущены)
- [ ] launch_mcp_daemon.sh
- [ ] swarm_start_with_dynamic_tools.sh
- [ ] switch_mode.sh (development/production)
- [ ] chaos_test.sh
- [ ] free_tier_bootstrap.sh

## 5. Инфраструктура (подготовка)
- [ ] FREE_TIER_INVENTORY_2026-06-19.md заполнен
- [ ] THIRD_PARTY_NODES_2026-06-19.md готов
- [ ] CONSENT_GATES_2026-06-19.md понятен
- [ ] Минимум 3-4 free-tier аккаунта готовы (но не запущены)

## 6. Runtime интеграция (подготовка)
- [ ] runtime.py имеет комментарии/патчи для dynamic tools (но не применены)
- [ ] plugins/ содержит все новые динамические скиллы (как файлы)
- [ ] /run/octopus/dynamic_state/ структура подготовлена

## 7. Проверка перед стартом
- [ ] pack_read_guard 20/20
- [ ] SLO green
- [ ] Все step-backups на месте
- [ ] experience обновлён
- [ ] **Явное согласие человека** на запуск первой bounded wave

## Порядок запуска (только после согласия)
1. Запустить только D1 (подготовка runtime)
2. Verify
3. Запустить D2 (development mode)
4. Verify
5. И так далее по плану
