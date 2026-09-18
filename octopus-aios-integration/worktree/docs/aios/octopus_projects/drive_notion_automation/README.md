# Octopus Drive → Contacts → Notion Automation

Python-скрипт для автоматизации мониторинга аудиофайлов на Google Диске и создания задач в Notion.

## Что делает

1. Рекурсивно сканирует папку Google Drive (по умолчанию `1zAKjmh0Yh92SkJ-erYy4Xafhv19VY-yN`) и все подпапки.
2. Ищет аудиофайлы `.mp3` и `.m4a`.
3. Определяет контекст по имени родительской папки.
4. Сопоставляет имя папки или номер телефона с контактами Google через People API.
5. Создаёт карточку в базе Notion:
   - **Name**: `Анализ разговора: [имя файла]`
   - **Contact**: найденное имя контакта
   - **Status**: `Новый` (можно изменить в `.env`)
   - **Priority**: `Критический`, если в имени файла/папки есть слова `ВСП`, `задержание`, `адвокат`, иначе `Обычный`
   - **Context**: путь, размер, телефон/email, ключевые слова
   - **File**: ссылка на файл в Google Drive
6. Ведёт `processed_files.json`, чтобы не обрабатывать файлы повторно.

## Установка

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Настройка Google OAuth2

1. Откройте [Google Cloud Console](https://console.cloud.google.com/).
2. Создайте новый проект (или используйте существующий).
3. Включите API:
   - Google Drive API
   - Google People API (Contacts API)
4. Перейдите в **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
5. Тип приложения: **Desktop app**.
6. Скачайте JSON и сохраните как `credentials.json` в папку со скриптом.
7. При первом запуске скрипт откроет браузер для авторизации и создаст `token.json`.

## Настройка Notion

1. Создайте интеграцию: [Notion Integrations](https://www.notion.so/my-integrations).
2. Скопируйте **Internal Integration Token**.
3. Создайте базу данных Notion со свойствами:
   - `Name` (title)
   - `Contact` (rich text)
   - `Status` (select)
   - `Priority` (select)
   - `Context` (rich text)
   - `File` (URL)
4. Подключите интеграцию к базе (**Share → Add connections → ваша интеграция**).
5. Скопируйте ID базы из URL: `https://www.notion.so/...?v=...`**`&p=`**`database_id`.

## Конфигурация

Создайте файл `.env`:

```env
NOTION_TOKEN=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DRIVE_FOLDER_ID=1zAKjmh0Yh92SkJ-erYy4Xafhv19VY-yN
```

## Запуск

```bash
source .venv/bin/activate
python octopus_drive_notion_sync.py
```

## Запуск по расписанию

### Linux / Cron

Откройте crontab:

```bash
crontab -e
```

Добавьте строку (каждые 15 минут):

```cron
*/15 * * * * cd /путь/к/drive_notion_automation && /путь/к/drive_notion_automation/.venv/bin/python octopus_drive_notion_sync.py >> /var/log/drive_notion_sync.log 2>&1
```

### Windows Task Scheduler

1. Откройте **Планировщик заданий**.
2. Создайте простую задачу: **Создать простую задачу**.
3. Триггер: **Ежедневно**, повторять каждые 15 минут.
4. Действие: **Запуск программы**.
5. Программа: `C:\путь\к\.venv\Scripts\python.exe`
6. Аргументы: `octopus_drive_notion_sync.py`
7. Рабочая папка: `C:\путь\к\drive_notion_automation`

## Логи

Скрипт пишет в консоль в формате:

```text
2026-06-19 10:55:01 | INFO     | Создана Notion-запись: Анализ разговора: call_01.m4a (id=...)
```

При запуске через Cron/Task Scheduler перенаправьте вывод в файл (см. примеры выше).

## Безопасность

- `credentials.json` и `token.json` содержат секреты — никогда не коммитьте их.
- Права доступа: `chmod 600 credentials.json token.json .env`.
- Добавьте в `.gitignore`:

```gitignore
.venv/
credentials.json
token.json
.env
processed_files.json
__pycache__/
```
