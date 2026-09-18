#!/bin/bash
# Быстрая проверка качества кода: ruff + pytest
# Запуск: bash scripts/lint.sh

set -e

echo "=== Ruff check ==="
ruff check swarm/ tests/

echo ""
echo "=== Pytest ==="
python3 -m pytest -q

echo ""
echo "✅ Всё чисто!"
