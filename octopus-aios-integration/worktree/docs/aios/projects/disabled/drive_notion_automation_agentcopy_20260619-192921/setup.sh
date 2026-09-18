#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ОШИБКА: файл .env не найден. Скопируйте .env.example в .env и заполните."
  exit 1
fi

if [ ! -f credentials.json ]; then
  echo "ОШИБКА: credentials.json не найден."
  echo "Скачайте его из Google Cloud Console (OAuth2 Desktop app) и положите в текущую папку."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Создаю venv..."
  python3 -m venv .venv
fi

echo "Устанавливаю зависимости..."
.venv/bin/pip install --quiet -r requirements.txt

echo "Проверяю компиляцию..."
.venv/bin/python -m py_compile octopus_drive_notion_sync.py

echo "Первый интерактивный запуск для получения token.json..."
echo "Откроется браузер (или вы получите URL). Авторизуйтесь и вернитесь в терминал."
.venv/bin/python octopus_drive_notion_sync.py

echo "Готово. token.json создан."
