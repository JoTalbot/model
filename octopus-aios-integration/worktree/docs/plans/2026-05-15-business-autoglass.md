# Business: Автостёкла — MVP

## Статус: ✅ Реализовано (MVP)

## Цель

Бизнес-логика для магазина автостёкол на Ивана Олинского 66. Отделена от ядра P2P/памяти в `swarm/business/`.

## Реализованные компоненты

### 1. VIN-декодер (`decode_vin`)

Офлайн-декодер по WMI-таблице (30+ производителей) + 10-й символ VIN для года выпуска.

```bash
python3 node.py glass vin-decode WBA5B31070GP12345
# → BMW, Германия

python3 node.py glass vin-decode XTA219070R0000001
# → Lada, Россия, 2024
```

Поддерживаемые марки: Lada, BMW, Mercedes-Benz, Toyota, Honda, Nissan, Hyundai, Kia, Volkswagen, Audi, Ford, Tesla, Chevrolet, Land Rover, Jaguar, Fiat, Alfa Romeo, Renault, Changan и др.

### 2. Каталог стёкол (`GlassCatalog`)

CRUD через `MemoryRepository` — наследует все слои резервирования (local, swarm, cloud).

```bash
# Добавить позицию
python3 node.py glass add --name "Лобовое Lada Granta" --type лобовое \
    --make Lada --model Granta --year 2020 --year 2021 \
    --price 5500 --supplier "БОР" --oem "21190-5206010"

# Список с фильтрами
python3 node.py glass list --make Lada --type лобовое --in-stock

# Поиск по VIN
python3 node.py glass vin XTA219070R0000001
```

### 3. Мониторинг цен конкурентов

Интеграция с Web Parser Pipeline — парсинг цен и сохранение истории.

```bash
# Парсить и сохранить
python3 node.py glass parse-prices "лобовое стекло lada granta цена" --save

# История снимков
python3 node.py glass price-history --limit 10
```

## CLI-команды (`glass`)

| Команда | Описание |
|---------|----------|
| `glass add` | Добавить стекло в каталог |
| `glass list` | Список с фильтрами (марка, тип, наличие) |
| `glass vin <VIN>` | Поиск совместимых стёкол по VIN |
| `glass vin-decode <VIN>` | Декодировать VIN (без каталога) |
| `glass parse-prices <запрос>` | Парсинг цен конкурентов |
| `glass price-history` | История снимков цен |

## Хранение данных

| Таблица | Содержимое |
|---------|-----------|
| `autoglass_catalog` | Позиции каталога (GlassItem) |
| `autoglass_price_history` | Снимки цен конкурентов |

Обе таблицы живут в `MemoryRepository` → `.swarm_scratch/` (локально) или любой из 22+ схем хранения.

## Следующие шаги (опционально)

1. OCR чеков и накладных → автоимпорт в каталог
2. Расширение WMI-таблицы (полная база ISO 3780)
3. Модель авто по VDS (символы 4-8)
4. Telegram-бот для быстрого поиска по VIN от клиента
5. Аналитика: сравнение своих цен с конкурентами
