# Сессия: freqtrade-валидация порта T2 + скаффолд исполнителя (2026-08-16)

## Контекст
Продолжение сессии 20260815T154510Z (T2 стратегия, meta-labeling, Riskfolio).
Ветка: `agent/20260815-quant-oos-profit`. Цель: снять блокер TA-Lib для
freqtrade-порта T2, провалидировать порт, подготовить авто-исполнение для
реальных денег.

## Процесс (обязательный: локально → прод)
Всё разрабатывалось и тестировалось в песочнице `/home/user/test_env/freqtrade`,
затем перенесено на сервер base64 через SSH и провалидировано повторно.

## Что сделано

### 1. Найдены и исправлены ДВА бага в порте freqtrade_t2.py
- вход по «пересечению» вместо «уровня» (расходится после выхода по гистерезису);
- выход сигнальным столбцом блокируется freqtrade при одновременном сигнале
  входа (`exit_ and not enter`) в зоне между SMA40 и SMA50.
  Исправлено: уровневый вход + выход через `custom_exit()` (только закрытые
  свечи, без выхода в свече входа).

### 2. Валидация порта (close-fill / open-fill эталоны / freqtrade)
- Локально (Yahoo): все 5 пар OK, dev 0.2–4.1%, сделки день-в-день.
- На сервере (Binance): все 5 пар OK, dev 0.1–3.9%.
- Тесты: 4/4 локально, 4/4 на сервере.
- Ключевая находка: продовые цифры T2 включают сделки первых 200 баров
  истории (freqtrade требует 200 свечей разогрева) — для NEAR/SOL это
  существенно (ралли 2020-2021); модель исполнения (close vs next open)
  в крипте эквивалентна (гэпы ~0.01%).

### 3. Инфраструктура на сервере
- `/root/freqtrade-venv` (Python 3.11, freqtrade 2026.7; TA-Lib 0.7.1 — wheel).
- Данные: `data/freqtrade/data/binance/` (скрипт download_binance.py, публичный API).
- Патч ccxt (spot-only, документирован) — без него freqtrade требует ключи даже для backtest.
- Dry-run бот: systemd `aios-freqtrade-t2-dry` — запущен, позиции совпали с paper
  (ETH LONG @1884.25, BNB LONG @606.69; BTC/SOL/NEAR CASH).

### 4. Скаффолд исполнителя реальных денег
- `scripts/run_t2_executor.py` (--dry по умолчанию, --live с ключами),
  `config_executor.example.json`, тесты 5/5 (локально и на сервере).
- НЕ активирован; ключи не вводились.

## Файлы (мои пути)
- scripts/freqtrade_t2.py (перезаписан), scripts/freqtrade_config_t2.json (перезаписан)
- scripts/freqtrade_validation/{run_validation.py, reference_t2.py, download_binance.py, test_freqtrade_t2.py} (новые)
- scripts/run_t2_executor.py, scripts/config_executor.example.json, scripts/test_executor.py (новые)
- docs/FREQTRADE_VALIDATION.md (новый)
- coordination/sessions/20260816T030000Z-freqtrade-validation.md (этот файл)
- coordination/claims/20260816-freqtrade.md (claim)

## Проверки
- pytest: test_freqtrade_t2.py 4/4 (loc+server), test_executor.py 5/5 (loc+server)
- systemctl is-active aios-freqtrade-t2-dry → active
- Чужую работу (M catboost_info/*, M tests/test_news_pipeline.py, ?? backups/ и др.) не трогал.

## Блокеры / следующий шаг
- Реальные деньги: ключи Binance (spot-only), неделя в --dry, затем systemd-timer.
- Гипероптимизация/сравнение с NostalgiaForInfinity — теперь возможно.
- Hummingbot MM — ждёт накопления ws-данных (в orderbooks.sqlite ~1-2 дня).
