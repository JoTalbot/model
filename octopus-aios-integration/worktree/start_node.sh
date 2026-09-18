#!/bin/bash
# 🐙 IMMORTAL SWARM BOOTSTRAPPER
# Этот файл превращает любой Linux-сервер в бессмертный узел P2P-сети.

echo "=== OCTOPUS GHOST LOADER STARTING ==="

# 1. Проверка прав
if [ "$EUID" -ne 0 ]; then 
  echo "Пожалуйста, запустите от имени sudo"
  exit
fi

# 2. Очистка и подготовка
apt-get update && apt-get install -y curl python3 python3-pip git

# 3. Скачивание и запуск загрузчика
curl -sSL https://raw.githubusercontent.com/JoTalbot/octopus/main/scripts/ghost_loader.py -o ghost_loader.py
python3 ghost_loader.py install

echo "=== INSTALLATION INITIATED ==="
echo "Дождитесь генерации .onion адреса и сохраните его!"
