# UPGRADE: CX22 → CX32 (Hetzner Cloud)
Дата: 2026-05-29
Инициатор: пользователь (явная команда «улучшить в 2 раза»)
Соответствие инструкции №08: ✅ есть явная команда пользователя

## Текущая конфигурация
- Server ID: 130599342
- Hostname: autosklo-prod
- IP: 178.105.142.113
- Регион: nbg1-dc3 (Nuremberg)
- Тип: CX22 (2 vCPU Intel / 3.7 GiB RAM / 38 GB SSD)

## Целевая конфигурация
- Тип: **CX32** (4 vCPU Intel / 8 GiB RAM / 80 GB SSD)
- Стоимость: ~€6.49/мес (вместо €4.49)
- Disk upgrade: **НЕТ** (флаг --keep-disk), диск остаётся 38 GB → можно даунгрейднуть назад при необходимости

## План выполнения

### Фаза 1: подготовка (5 мин, без downtime)
1. Сохранить токен HCloud в /etc/octopus/secrets.env (chmod 600)
2. Установить hcloud CLI если нет
3. Проверить: hcloud server describe 130599342
4. Снять snapshot всего важного:
   - DB dump: pg_dumpall → /var/lib/octopus/backups/pre_upgrade_$(date).sql.gz
   - Tarball /var/lib/octopus/memory_pool/
   - Tarball /etc/octopus/, /opt/octopus*
   - hcloud server create-image (опционально, ~5 мин, но НЕ обязательно — это просто snapshot)
5. Записать состояние перед апгрейдом (free, ps, docker ps, smoke)

### Фаза 2: остановка сервисов (1-2 мин)
1. systemctl stop octopus-watchdog (чтобы не пытался рестартить)
2. systemctl stop octopus-* (все октопусовские)
3. docker stop octopus octopus-child-83{00,01,02,04} ipfs-node octopus-grafana octopus-prometheus octopus-blackbox octopus-next-admin
4. systemctl stop docker
5. sync; sync

### Фаза 3: апгрейд (5-10 мин downtime)
1. hcloud server shutdown 130599342 (graceful)
2. Ждём status = off (до 60 сек)
3. hcloud server change-type 130599342 cx32 --keep-disk
4. hcloud server poweron 130599342
5. Ждём статус running + ping ОК

### Фаза 4: восстановление (5 мин)
1. SSH check
2. nproc → 4, free -h → 8GB
3. systemctl start docker (auto starts containers)
4. systemctl start octopus.service (parent)
5. systemctl start octopus-child@{8300,8301,8302,8304}
6. systemctl start octopus-{watchdog,sync,alerting,alerts-tg,task-worker,task-reaper,tg-bot,...}
7. Поднять memory limits в /opt/octopus-start-wrapper-patched.sh:
   - parent: 1800m → 3500m (теперь можем себе позволить)
   - child: 768m → 1200m
   - IPFS: 320m → 512m
8. Перезапустить контейнеры с новыми лимитами

### Фаза 5: проверка (5 мин)
1. bash /opt/octopus-smoke.sh — должно быть 37/0/0
2. curl status, alerts, targets
3. Запись в memory_records, agent_memory
4. Telegram уведомление: «Server upgraded CX22→CX32»
5. Лог в ~/agents/-Octopus/logs/

### Откат (если что-то пошло не так)
1. hcloud server shutdown 130599342
2. hcloud server change-type 130599342 cx22 --keep-disk (только если НЕ был сделан --upgrade-disk — у нас именно так)
3. hcloud server poweron 130599342

## Контрольные точки
- [ ] Токен получен и сохранён
- [ ] Бэкап БД создан
- [ ] Бэкап memory_pool создан
- [ ] Snapshot состояния системы записан
- [ ] Сервисы остановлены корректно
- [ ] change-type выполнен
- [ ] Сервер поднялся с новыми ресурсами
- [ ] Все сервисы запущены
- [ ] Memory limits увеличены
- [ ] Smoke 37/0/0
- [ ] Telegram уведомление
- [ ] Лог итерации создан
- [ ] Experience создан
