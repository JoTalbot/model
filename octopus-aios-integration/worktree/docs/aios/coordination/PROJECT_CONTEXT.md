# Оперативный контекст проекта AIOS

**Последняя верификация:** 2026-08-14T11:23:03Z
**Машина:** `aios`
**Рабочий каталог:** `/root/AIOS`
**Базовый commit аудита:** `356bd628` (`main`, на старте совпадал с `origin/main`)
**Каноническая версия в `VERSION`/`pyproject.toml`:** `19.9.0`

> Репозиторий изменяется с разных машин и разными ИИ-агентами, иногда параллельно. Перед любой работой обязательно прочитать `AGENTS.md`, `coordination/README.md`, этот файл, активные claims и `git status`.

## Где закончили

**2026-08-19 (Arena.ai, режимный движок по рекомендациям):** (1) исправлена
freqtrade-ловушка stoploss=-0.99 (−99%! стоп=1% от входа) → страховочный −15%,
бот пересчитал открытые сделки, регрессия-тест; (2) Market Regime Engine:
7 режимов из совокупности индикаторов + риск-уровни + роутер стратегий +
триггеры; ежедневный таймер 04:50 UTC, история в
market_regime_history.jsonl; сейчас BEAR (dd90 −16.3%); (3) CRASH/PANIC
kill-guard в политике Directional v2 (включён в обоих демонах, fail-open);
(4) T2-метрики симуляции (PF/Sharpe/Sortino/Calmar/expectancy) с пометкой
«не заработок»; (5) отчёт получил блок «Режим рынка и защита», LLM —
вероятностные сценарии + раздел «насколько доверять»; (6) seam
pre_treasury_intents.py вернул accounts.py в бюджет. Коммит `3f687afe`,
ветка `agent/20260819-regime-engine`.
Журнал: `coordination/sessions/20260819T020000Z-aios-arena-regime-engine.md`.

## Где закончили

**2026-08-19 (Arena.ai, инвесторский отчёт + одна кнопка):** по решению
владельца — ежедневный утренний трейдинг-отчёт чату 839699134 (таймер
aios-tg-trading-report, 05:30 UTC; sender --chat); бот упрощён до одной
кнопки «📈 Трейдинг» (обе клавиатуры); доверенные чаты через
telegram_extra_chat_ids. ВАЖНО: доставка начнётся после первого /start от
839699134 (Telegram не даёт ботам писать первыми). Коммит на ветке
`agent/20260819-investor-report`. Журнал: sessions/20260819T010000Z-...trading-report.md.

## Где закончили

**2026-08-19 (Arena.ai, честность T2 в отчёте):** владелец спросил про +167%
моментум-роботов — выяснено: это историческая симуляция с окт.2023 (не
заработок), живой daily-цикл стартовал 16-18.08 (BTC −0.5%); баг отчёта
(нога BTC читала legacy-реплей) исправлен; секция T2 честно разделяет живой
тест и симуляцию; LLM-промпт помечает реплей. Коммит на ветке
`agent/20260819-t2-honest`. Журнал: sessions/20260819T010000Z-...trading-report.md.

## Где закончили

**2026-08-19 (Arena.ai, фикс кнопки «Трейдинг»):** текстовая кнопка «📈 Трейдинг»
вела на старый treasury-отчёт (ключевое слово «трейдинг» в treasury-intent).
Исправлено: единый хелпер send_full_report; перехват текста «трейдинг» ДО
treasury в tg_bot/accounts.py; inline nav_trading на том же хелпере. Живая
симуляция текстового пути подтверждена; отчёт отправлен владельцу (3/3).
Коммит на ветке `agent/20260819-trading-button-fix`.
Журнал: `coordination/sessions/20260819T010000Z-aios-arena-tg-trading-report.md`.

## Где закончили

**2026-08-19 (Arena.ai, отчёт «по-человечески»):** кнопка «Трейдинг» теперь
выдаёт отчёт на языке обывателя: «Главное за 30 секунд», «Что это» к каждому
портфелю, человеческие названия причин сделок, блок «Простыми словами» и
словарик; LLM-аналитика переведена на тот же язык (жаргон с пояснениями,
дисклеймер о виртуальных деньгах). Отправлен владельцу в TG (3 сообщения).
Коммит `216f5dd1`, ветка `agent/20260819-human-report`.
Журнал: `coordination/sessions/20260819T010000Z-aios-arena-tg-trading-report.md`.

## Где закончили

**2026-08-19 (Arena.ai, кнопка «Трейдинг» — детальный отчёт):** tg_bot/trading_report.py —
полный снапшот всех портфелей (A/B с trade_log, DCA VA+control, корзина
vol-targeting, T2 5 ног + портфель, freqtrade dry, MM/ws/очередь, scoreboard,
сервисы) + LLM-аналитика и сценарии-прогнозы через LLMBalancer (структура
риски/анализ/сценарии с вероятностями, дисклеймер «не финансовый совет»;
системный промпт заземляет модель на известные результаты исследований).
Кнопка nav_trading: данные мгновенно, LLM в фоновом потоке (бот не блокируется).
Живая проверка: groq 404 → fallback mistral, корректный ответ. Тесты 7/7.
PR #198 (`b2362aa2`). Журнал:
`coordination/sessions/20260819T010000Z-aios-arena-tg-trading-report.md`.

## Где закончили

**2026-08-18 (Arena.ai, TG-команды и брифинг):** /basket, /ab, /scoreboard в
Telegram-боте (обёртки в protected run_telegram_bot.py — selfguard-snapshot
обновлён); строки корзины и scoreboard в утренний брифинг; фикс стартовой
комиссии корзины (кэш заканчивается ровно 0). Текущий A/B: 4 vs 3 сделки.
Коммит `1c2da1c3`, ветка `agent/20260818-tg-quant-commands`.
Журнал: `coordination/sessions/20260818T010000Z-aios-arena-tg-quant-commands.md`.

## Где закончили

**2026-08-18 (Arena.ai, «делай как лучше» — рекомендации применены):**
(1) live-корзина переведена на vol-targeting (веса ∝ 1/σ30d; TON — kraken,
делистнутые серии отсеиваются фильтром свежести; честный кэш-поток;
бенчмарк-история сброшена — правило сменилось); (2) медвежий режим
(BTC<SMA200) — уведомление в утренний брифинг (сейчас bear: 64.8k vs 69.1k);
(3) DCA не менялся. Коммит `a05af8c4`, ветка `agent/20260818-best-move`.
Журнал: `coordination/sessions/20260818T001000Z-aios-arena-best-move.md`.

## Где закончили

**2026-08-17 (Arena.ai, вариации корзины/DCA):** честный бэктест 12 мес (BTC
−44.2%) + чистое под-окно 7 мес (SMA200 прогрета): частота ребаланса не
влияет (−32…−33%); vol-targeting — лучший всегда-в-рынке (−12.0% vs −33.2%,
DD −27.3 vs −39.1); DCA бьёт lump-sum в 7 раз в медвежьем годе (−4.7%);
тренд-фильтр BTC>SMA200 честно держал 100% кэш весь год (BTC ни дня выше
SMA200). Рекомендации владельцу: vol-targeting в live-корзину, тренд-фильтр
как уведомление в брифинг, DCA не менять. Отчёт:
`docs/BASKET_VARIANTS_2026-08-17_RU.md`; инструмент
`scripts/quant_basket_variants.py` (6 тестов). PR #194 (`e0898a3d`).
Журнал: `coordination/sessions/20260817T235000Z-aios-arena-basket-variants.md`.

## Где закончили

**2026-08-17 (Arena.ai, внешние данные для сигнала):** карта внешних источников
полностью закрыта/автоматизирована: lead-lag BTC→альты ОТКЛОНЁН (lag1 corr
0.001 vs lag0 0.654 — рынок синхронный на 1h; правило: 0/31 альтов в плюсе net
of cost); 1h-микроструктура из ws-стрима — пайплайн scripts/mm_hourly_features.py
+ weekly-таймер aios-mm-hourly-features (1181 symbol-hours, предварительные
корреляции ≈ 0, вердикт после накопления вместе с MM). Полная карта: macro ✗,
on-chain ✗, derivatives ✗, funding ✗, news ✗, lead-lag ✗, микроструктура —
накопление. Отчёт: `docs/EXTERNAL_SIGNALS_2026-08-17_RU.md`. Коммит `d779979e`
(PR #192), ветка закрыта. Журнал:
`coordination/sessions/20260817T230000Z-aios-arena-external-signals.md`.

## Где закончили

**2026-08-17 (Arena.ai, Edge Lab — новый виток):** (1) triple-barrier метки
ОТКЛОНЕНЫ (tb AUC 0.502 vs nb 0.524 на 35 символах, purge-сплит) — метки не
были узким местом, сигнала в технических фичах 1h нет; направление закрыто,
харнесс переиспользуем. (2) Бенчмарк-корзина топ-10 в paper:
scripts/run_basket_paper.py + таймер aios-basket-paper (ежедневно 17:40 UTC,
месячный ребаланс). (3) Power-анализ A/B: эффект 0.2$/сд. требует ~1237
сделок/контур — вердикт по 15-20 сделкам экономический, не строго значимый;
бенчмарк-строка в weekly-отчёте. Коммит `03cd77a9`, ветка
`agent/20260817-edge-lab`. Журнал:
`coordination/sessions/20260817T220000Z-aios-arena-edge-lab.md`.

## Где закончили

**2026-08-17 (Arena.ai, system-sweep 1-5):** health-sweep — 0 failed, OLX жив
(legacy-файл протух by design), Freelancehunt пагинация починена (стоп на 400);
Directional v2 пишет trade_log, weekly A/B-отчёт получил бустрап-вердикт
(≥15 сделок/контур → diff, CI90, significant); WATCH-пороги сигнал-продукта
data-driven (RL-условие убрано — было недостижимо); DeFi-срез здоров
(fail-closed by design, router dry-run); ROADMAP/EXECUTIVE_SUMMARY обновлены.
Коммит `10024d26`, ветка `agent/20260817-system-sweep`.
Журнал: `coordination/sessions/20260817T210000Z-aios-arena-system-sweep.md`.

## Где закончили

**2026-08-17 (Arena.ai, scoreboard стратегий — решение «как лучше»):** M2 в
paper НЕ поставлен (OOS −46%/2г не проходит честный гейт); вместо этого
ежемесячный автоматический бэктест: scripts/quant_strategy_scoreboard.py +
таймер aios-strategy-scoreboard (2-го числа 06:10 UTC). Первая строка 2026-08:
победитель — корзина топ-10 (+2.51%), DV2 −0.38% при рынке −7.35%, M2 +1.7%
(неустойчив). Правила вердикта и история: data/reports/strategy_scoreboard.md,
docs/STRATEGY_SCOREBOARD.md. Коммит `8455f8a9`.
Журнал: `coordination/sessions/20260817T200000Z-aios-arena-strategy-scoreboard.md`.

## Где закончили

**2026-08-17 (Arena.ai, бэктест стратегий за 1 месяц):** окно 17.07→17.08
(рынок −7.59%): M2 CS-момент +1.9% — формальный победитель (но OOS −46%/2г);
DCA топ-10 +1.12%, B&H корзины +1.43%; Directional v2 −0.38% (9 сделок, win
55.6%, +7.2 п.п. к рынку); free-profile −31.34% — цена издержек. Устойчивый
выбор — пассивная корзина мейджоров. Отчёт:
`docs/STRATEGY_MONTH_BACKTEST_2026-08-17_RU.md`; инструменты расширены
(--ml-min-prob/--trail-ratio, --eval-last-days). Коммит `0243e9af`.
Журнал: `coordination/sessions/20260817T190000Z-aios-arena-month-strategy-test.md`.

## Где закончили

**2026-08-17 (Arena.ai, финальные операции с добром владельца):** Docker Build
& Push починен (PR #185: временные trivy-исключения для prom/prometheus v3.13.2,
Go stdlib <1.26.6; убрать при релизе v3.14.0+) — прогон на main SUCCESS.
GHA-бампы применены (PR #186: upload-artifact 7.0.1, download-artifact 8.0.1,
codecov 7.0.0, login-action 4.6.0, action-gh-release 3, SHA-пины). Все 14
dependabot-веток разобраны (4 dev смержены ранее, 10 закрыты как superseded
или конфликтующие), открытых PR 0. Все CI main зелёные (плюс transient
429/503 GitHub, перезапущены). Журнал:
`coordination/sessions/20260817T183000Z-aios-arena-final-ops.md`.

## Где закончили

**2026-08-17 (Arena.ai, PR и зависимости):** PR #182 (trading hardening +
quant research, 139 коммитов) СМЕРЖЕН в main (squash ed054ec8), CI 6/6 зелёный.
Dependabot: 4 dev-бампа смержены ранее; 5 runtime-веток устарели — закрыты,
заменены целевым PR #183 (starlette>=1.6.0, uvicorn>=0.52.3,
python-dotenv>=1.2.2, litellm>=1.96.2,<2; lock перегенерирован, контракт 0,
pip check чистый); websockets>=17 отклонён (web3==7.16.0 требует <16).
5 GHA-бампов dependabot оставлены на решение владельца. Ветка
agent/20260817-dependabot-runtime. Журнал: sessions/20260817T163000Z-...improve-all.md.

## Где закончили

**2026-08-17 (Arena.ai, RL-гигиена A+ по решению владельца):** вето RL сохранено
(страховка), лог моста показывает реальное имя модели (ppo_v9.pt), 5 устаревших
ppo-моделей удалены (оставлены v9 и свежий внешний ppo_multi_24.pt от 17.08),
rl_signals.json теперь обновляется ежечасно внутри сигнал-продукта (был протухший
с 14.08). Коммит `ed7e50e8`, ветка `agent/20260817-trading-improvements`.
Журнал: `coordination/sessions/20260817T163000Z-aios-arena-improve-all.md`
(обновлён: пункт 8 закрыт).

## Где закончили

**2026-08-17 (Arena.ai, пакет улучшений 1-8):** 2 failed-сервиса починены
(canary SKIP при выключенном мониторинге; restore-drill от aios-telegram);
~2.8G мёртвых chrome-профилей удалены (диск 56%); PR #182 открыт в main
(139 коммитов); 4 dev-dependabot PR смержены, 5 runtime оставлены до
перегенерации lock; интроспекция сделок Directional v2 (ml_prob/confidence в
ENTRY + trade-лог); A/B-строка в утренний брифинг; заготовка приоритета
очереди (scripts/mm_queue_priority.py + weekly-таймер, первые цифры τ5с≈11-13%);
RL-статус задокументирован (docs/RL_STATUS_2026-08-17_RU.md) — решение
владельца ожидается. Ветка agent/20260817-trading-improvements (35 коммитов)
синхронизирована с origin. Журнал:
coordination/sessions/20260817T163000Z-aios-arena-improve-all.md.

## Где закончили

**2026-08-17 (Arena.ai, BNB maker-rebate проверка):** сетка комиссий на
gated/naive MM: BNB gated требует ребейт ≥1.27bps/сторону для безубыточности
(лучший в выборке; BTC 2.56bps); при 0% комиссии всё равно отрицателен
(adverse selection + inventory MTM). Доступные тарифы — заряд (spot 7.5-10bps,
futures maker 2bps), ребейты только VIP7+ → гипотеза ОТКЛОНЕНА при доступных
условиях; BNB — первый кандидат при появлении ребейт-площадки. Инструмент
`scripts/mm_maker_fee_sensitivity.py`, отчёт
`docs/MM_BNB_MAKER_REBATE_2026-08-17_RU.md`. Коммит `c15fb01b`.
Журнал: `coordination/sessions/20260817T153000Z-aios-arena-bnb-maker-rebate.md`.

## Где закончили

**2026-08-17 (Arena.ai, модель очереди MM + публикация):** эмпирическая
fill-калибровка хвоста очереди (`scripts/mm_queue_model.py`): мажоры life_med
5.6-11.4с, P(fill)/60с: BTC/ETH ~18%, BNB 30.9% (лучший), тонкие книги 3.8-7.3%;
согласовано с interim-2 (adverse selection съедает спред) — положительного
ожидания нет ни на одной паре выборки. Отчёт: `docs/MM_QUEUE_MODEL_2026-08-17_RU.md`.
Ветка `agent/20260817-trading-improvements` (25 коммитов) ОПУБЛИКОВАНА в origin
(решение владельца 2026-08-17). Полный pytest зелёный, audit --strict: 0 drift.
Журнал: `coordination/sessions/20260817T143000Z-aios-arena-mm-queue-model.md`.

## Где закончили

**2026-08-17 (Arena.ai, BTC long-horizon проверка):** гипотеза сигнала
(180-900с, AUC 0.63-0.66 из interim-2) ОТКЛОНЕНА строгой проверкой: на
purge-сплите AUC 0.49-0.56 — исходная оценка была утечкой лейблов через
перекрывающиеся окна без purge-гэпа; orderbook-фичи не добавляют к моментуму;
long net of 0.5% cost отрицателен на всех горизонтах. Новый чекер
`scripts/mm_signal_long_horizon_check.py` (purge-методика обязательна для
будущих OOS-заявлений). Отчёт: `docs/BTC_LONG_HORIZON_SIGNAL_2026-08-17_RU.md`.
Коммит `57ded2b7`, ветка `agent/20260817-trading-improvements`.
Журнал: `coordination/sessions/20260817T133000Z-aios-arena-btc-long-horizon.md`.

## Где закончили

**2026-08-17 (Arena.ai, MM interim-2):** 4.5x больше ws-данных (1.19M снапшотов,
40ч) укрепили негатив: 30s-сигнал мажоров СХЛОПНУЛСЯ (BTC 0.867→0.578,
ETH 0.795→0.556 при n×20); naive MM убыточен при нулевой комиссии (adverse
selection −0.14…−0.73 $/fill); gated режет убыток 51-81%, знак не переворачивает.
Latency транспортная в порядке (129мс медиана; post-split p90 BTC 245мс).
Новый драйвер `scripts/mm_ws_backtest.py`, отчёт `docs/MM_INTERIM_2026-08-17_RU.md`.
Коммит `843d9f6e`, ветка `agent/20260817-trading-improvements`.
Журнал: `coordination/sessions/20260817T123000Z-aios-arena-mm-interim2.md`.

## Где закончили

**2026-08-17 (Arena.ai, тесты и claims):** полный pytest снова полностью
зелёный (EXIT=0): починены 3 преэкзистинг-провала (tests/macro: gran + helper
test_→eval_; tests/test_v22_api: route count 6), удалены 4 устаревших
DONE-claim, PROJECT_INVENTORY перегенерирован. Коммиты `34ea53cf`, `762a134a`,
`64973996`, `47e89ed9`, `05681cb9`; ветка `agent/20260817-trading-improvements`.

## Где закончили

**2026-08-17 (Arena.ai, ws-стрим-сплит):** depth и aggTrade разнесены по
отдельным соединениям в orderbook-ws (всплески сделок больше не затапливают
поток глубины); измеряемая latency очистилась: p90 3.1с → 0.13-0.16с,
медиана ~123мс, full-стрим BTC/ETH без потерь. Коммит `fbb70a5f`, ветка
`agent/20260817-trading-improvements`.

**2026-08-17 (Arena.ai, пакет улучшений трейдинга по решению владельца):**
(1) orderbook-ws: реальная задержка (latency_ms из aggTrade E, avg ~205ms —
partial-depth стрим не содержит E) и полный 100мс-стрим BTC/ETH
(--full-pairs, ~8.6 сэмпл/с каждая) для микроструктурного анализа; остальные
19 пар — 1Hz. (2) MemoryMax для трейдинг-демонов (market-data 2G,
orderbook-ws/freqtrade 1.5G, quant main/control/ml-inference 1G) + swap 8G
(swapfile2 4G в fstab) — защита от host-OOM. (3) Ретрайн ML теперь деплоит
кандидата только вместе с sane-калибровкой (q90 из его test-window
распределения, band 0.40-0.90); хелперы compute_quantiles/threshold_is_sane в
aios_core/quant/ml_gate_calibration.py. (4) quant_ml_monitor проверяет свежесть
калибровки (mtime модели vs калибровки) и застой A/B paper (>3дн, 0 входов при
enabled); run_health_check подхватывает проблемы → TG. (5) Еженедельный
A/B-отчёт scripts/quant_ab_report.py + aios-quant-ab-report.timer (Sun 16:30Z).
ВАЖНО: после калибровки гейта (0.5061) Directional v2 paper дал ПЕРВЫЕ входы:
1 сделка в каждом контуре (kraken, net −2.06 USD на $10k, fees+exec −1.0,
max DD 0.021%) — A/B-эксперимент начал накапливать статистику.
Полный pytest: 3 преэкзистинг-провала чужих областей (tests/macro gran,
test_v22_api monetization routes, ERROR macro test_feature) — не от правок.
Ветка `agent/20260817-trading-improvements` (5 коммитов, не опубликована).
Журнал: `coordination/sessions/20260817T093000Z-aios-arena-trading-improvements.md`.

## Где закончили

**2026-08-17 (Arena.ai, трейдинг-харденинг по решениям владельца):** (а) Ops:
aios-chrome-colab-secondary (crash-loop 7536 рестартов, X-сервер отсутствует)
остановлен+disable; BrowserMetrics Chrome 29G удалён (диск 94% → 54%).
(б) Orderbook-хранилище: busy_timeout=30s в ws- и research-коллекторах
(устранены database-locked разрывы); новый retention-прореживатель
`scripts/prune_orderbook_ws.py` + таймер `aios-orderbook-ws-prune` (сырые 1Hz
7 дней, старше — 1 сэмпл/минуту до 60 дней, хвост удаляется); юнит
`aios-freqtrade-t2-dry` канонизирован в deploy/systemd; audit --strict: 0 drift.
(в) Directional v2 paper: ML-гейт откалиброван по распределению модели
(решение владельца): эффективный порог = min(0.65, max(0.50, q90)), q90=0.5061
(287K сэмплов, 12 мес, 33 серии); скрипт `scripts/quant_ml_calibrate.py`,
seam `aios_core/quant/ml_gate_calibration.py`, accounting-тесты; A/B main/control
не тронуты (trail 1.0 vs 0.988). (г) Отложенная валидация: guarded hyperopt
(300 эпох × 5 пар) дал 56/87 — ОТКЛОНЁН на OOS (лучше базы только BTC, хуже
4/5); окна остаются 50/40 и 50/50; отчёт
`docs/T2_HYPEROPT_GUARDED_VERDICT_2026-08-17_RU.md`.
Полный pytest: только 3 преэкзистинг-провала чужих областей
(tests/macro gran, test_v22_api monetization routes — ждут владельцев scope).
Ветка `agent/20260817-trading-harden` (6 коммитов, не опубликована).
Журнал: `coordination/sessions/20260817T080000Z-aios-arena-trading-harden.md`.

## Следующий рекомендуемый шаг

1. Directional v2 paper: входы пошли (1 сделка в каждом контуре на 17.08);
   A/B-отчёт еженедельно (вс 16:30Z), алерт застоя в health check; вердикт A/B —
   после ≥30 сделок.
2. MM: interim-2, модель очереди и BNB rebate-проверка (17.08) негативны — см.
   блок «Где закончили»; MM закрыт до появления ребейт-условий или сильного
   сигнала; финальный вердикт после полных 2-4 недель 1Гц (по плану).
2. Через 2-4 недели: переобучить MM-сигнал на ws-данных (1Гц), модель очереди,
   калибровка порогов; вердикт по MM.
3. DCA-трекер: проверить депозиты/PnL, при желании владельца — реальные покупки.

## Где закончили

**2026-08-16 (Arena.ai, MM interim + guarded hyperopt):** промежуточная MM-проверка на
~13ч ws-данных (19 символов): сигнал направления жив на 30с (BTC AUC 0.867 n=1247,
ETH 0.795, NEAR 0.843, ADA 0.826; 15м — затухает), но maker-edge НЕТ: naive убыточен
везде, gated урезает убыток 76-93% не переворачивая знак, консервативная симуляция v2
отрицательна 16/17 пар-бирж. Финальный вердикт — после ≥2-4 недель 1Гц-данных
(+модель очереди, переобучение сигнала). Отчёт: docs/MM_INTERIM_2026-08-16_RU.md.
Запущен `scripts/freqtrade_validation/run_hyperopt_guarded.sh` (ждёт тихих окон по
RAM/swap/load; 300 эпох × 5 пар) — лог `data/freqtrade/hyperopt_run_guarded.log`,
затем `parse_hyperopt.py` → `validate_hyperopt.py` по методике 16.08. Журнал:
`coordination/sessions/20260816T092500Z-aios-arena-mm-and-hyperopt.md`.

## Где закончили

**2026-08-16 (Arena.ai сессия, доводка quant-исследований):** (а) news-sentiment
пайплайн завершён: 1545 исторических новостей оценены (Gemini + локальный лексикон),
event-study к 1h-ценам показал ОТСУТСТВИЕ edge (1781 совпадение; агрегат corr:
1h +0.007 / 24h −0.058 / 3d −0.036 / 7d −0.060; diff pos−neg −0.36…−0.99%) —
сигнал отклонён; герметичные тесты `tests/test_news_pipeline.py` 8/8 (фикс argv
в `run_main`). (б) Гипероптимизация окон T2: все прогоны hyperopt убиты OOM
(память хоста), кандидат 56/56 проверен на OOS — хуже базы на 4/5 пар → окна не
меняются (50/40; BNB/NEAR 50/50). Инструменты: `scripts/freqtrade_t2_hyper.py`,
`scripts/freqtrade_validation/{parse_hyperopt,parse_zips,validate_hyperopt}.py`.
Открытый вопрос: черновики `scripts/test_t2_paper.py`, `test_backtest_2y.py`,
`test_momentum.py` (без журнала) — решение владельца. Журнал:
`coordination/sessions/20260816T072500Z-aios-arena-quant-finish.md`.

## Где закончили

**2026-08-15 (Arena.ai сессия, quant/DCA/MM):** 8 честных экспериментов подтвердили
отсутствие edge в направленной 1h/4h торговле (LONG OOS, SHORT OOS, ML-CS, prod-3m,
tf×universe, MTF, funding, горизонты; PF<1 везде). Направленная торговля заморожена как
исследовательская тема. Запущены: (а) exit-конфиг через env (TP/SL/trail, дефолты legacy),
A/B paper main (trail=1.0) vs control (trail=0.988), allowlist = все 10 бирж;
(б) долгосрочный DCA-портфель paper-трекер (top-10 равные веса, $100/нед, квартальный
ребаланс, aios-dca-paper.timer ежедневно 17:30Z); (в) MM-направление: микроструктурный
сигнал (OBI/microprice) AUC 0.85-0.96 на ликвидных биржах (29ч данных, 18 пар-бирж),
устраняет adverse selection в naive MM; ws-коллектор глубины (aios-orderbook-ws, 1Гц,
Binance BTC/ETH/SOL) копит данные для финального вердикта (2-4 недели).
Ветка: agent/20260815-quant-oos-profit. Журнал: coordination/sessions/20260815T154510Z-aios-arena-session-start.md.

## Где закончили

**2026-08-15 (data estate):** 1h-история quant-универсума (33 актива) добрана до ~12 мес. (8760 баров) по биржам: binance 10005+, kucoin, mexc, bybit, okx (кроме SEI), bitstamp (кроме нелистингованных APT/ATOM/BNB/TON/TRX) — полный год; coinbase 24/31 серии >=7000 (лимит глубины API); bitfinex частично (rate-limit penalty IP — добивка `scripts/quant_backfill_exchanges.py --exchanges bitfinex --sleep 60 --retries 3`); kraken — жёсткий кап API 720 свечей (ограничение биржи). Инструмент: `scripts/quant_backfill_exchanges.py`.

Завершён cost-aware walk-forward Directional v2: 35 активов, OOS average −0.354%, positive 34.3%, PF 0.374. Стратегия не проходит gate; freeze/live ban подтверждены данными. Commit: `276950cd`. Отчёт: `docs/TRADING_WALK_FORWARD_2026-08-14_RU.md`; журнал: `coordination/sessions/20260814T123000Z-aios-arena-quant-walkforward.md`.

Runtime Directional v2: active/paper, `AIOS_QUANT_ENTRY_MODE=enabled` в owner-approved constrained profile (решение 2026-08-14T12:20Z), фактических entries 0. Live запрещён. Базовая реализация: `e7d24414`, `61f70b1b`.

**Проверено 2026-08-15T11:45Z:** за 18ч непрерывной работы trades=0, entry_count=0, портфель нетронут. Доминирующая блокировка — `exchange_not_allowed`=96 на каждом полном скане: allowlist `kucoin,bitstamp,mexc` почти не пересекается с универсумом 33 активов, поэтому кандидаты отсекаются ещё до ML-гейта (`ml_not_confirmed` 4-17). Это конфигурационное сужение, а не отказ модели; расширение allowlist или сужение универсума — решение владельца.

**2026-08-14T16:15Z (paper-fix):** paper-вход структурно разблокирован без изменения owner-профиля. Деградированная ML-модель (prob_up=0.433 const, AUC 0.504, гейт 0.65 недостижим) заменена scale-free CatBoost v2 (AUC 0.533; hit@prob>=0.65 = 81-83% на двух независимых OOS-окнах; avg net +0.6-0.7%/сделка по правилам движка). Журнал: `coordination/sessions/20260814T160500Z-aios-arena-paper-fix.md`; ветка `agent/20260814-paper-fix`, commit `8d668f03`. Live запрещён. Закрыто в 16:35Z (этап 2): RL-мост исправлен (onehot по ASSET_ORDER, vol_ratio вместо vol_chg, clamp; 9 мажоров честно FLAT — модель v8 не видит входов, veto консервативен), мёртвые тикеры MATIC/RNDR исключены из ML-сигналов и RL-универсума (ML 35→33). Закрыто в 17:15Z (этап 3): история дособрана до ~5000-5500 баров по всем 33 живым активам (Binance + Bybit fallback для KAS; TON: binance-серия делистнута 24.06, используются bitstamp/kraken); ML переобучена на полных данных (AUC 0.536, hit@0.65 82.4%, SIM +31.6%); PPO v9 обучена по методологии kg_v8 на локальных данных (sum_rl +96.0% vs BH −114%; v8: +51.4%) и развёрнута (мост читает assets из чекпоинта); сигнальный продукт: NO_DATA 16→0, regime по закрытому бару, выбор самой полной свежей серии. Ветка `agent/20260814-quant-backfill-ppo`, commit `9501cf23`. Живой RL-сигнал остаётся консервативным veto (все FLAT) — входа по RL-активам нет, это by design среды. 17:45Z (этап 4): orderbook-коллектор расширен до 6 бирж (kucoin depth-фикс, okx/bitstamp/coinbase), интервал 15с — скорость набора ~3x; аналитика снапшотов + cross-exchange диспаритеты в `scripts/analyze_orderbook_data.py`; предварительный MM-прогон: naive passive MM убыточен (adverse selection), нужен inventory-aware подход; полный прогон при >=1000 снапшотов/пара (binance/mexc ~250/1000, ~1.5-2ч); DeFi gate fail-closed корректно. Ветка `agent/20260814-quant-backfill-ppo`, commit `bda4d3b7`. 21:10Z (этап 7): WATCH-верификация — WATCH_DOWN precision 59.4% (143 сигнала), WATCH_UP 0 сигналов (правило слишком строгое в медвежьем рынке); ML drift monitor (hourly timer) и автообучение ML (weekly timer, deploy-only-if-better) установлены; feature-эксперимент: расширение 13→21 фич НЕ улучшает (AUC 0.5326 vs 0.5355) — базовый набор остаётся. Ветка `agent/20260814-quant-backfill-ppo`, commit `3171c6b4`. 21:30Z (этап 8, ВАЖНО): обнаружен методологический артефакт — историческая валидация PPO v8/v9 без clamp давала «скрытые шорты» (act<-1.5 → позиция -0.5, невозможная в развёрнутой политике); исторические «прибыли» (+51/+96%) — артефакты. Честная OOS-оценка с clamp: v9 = FLAT (0.0 vs BH -233%) — ценность = избегание убытков. v10 (честный сплит 70/30) не развёрнута. ML горизонты: h1 оптимален (h4/h8/h24 хуже), модель v2 остаётся. Для RL-заработка нужен явный SHORT-экшен (решение владельца). Ветка `agent/20260814-quant-backfill-ppo`, commits `174c3951`, `db27bdb4`.

Предыдущие этапы: test hermeticity `201df1eb`, tracking policy `b75c7c14`, dependency contract `7bd3e1e7`, deployment source `2be18e3a`, version consistency `c4a788cc`.

## Текущий архитектурный срез

AIOS — production-монорепозиторий, объединяющий:

- ядро оркестрации, конституционные политики, память, RAG/ChromaDB и LLM-балансер (`aios_core/`);
- автокодер и self-protection/selfguard;
- FastAPI/Starlette API, MCP, CLI, dashboards и Telegram/desktop-интерфейсы;
- интеграции OLX/social/messenger/Android/phone;
- финансовые, trading, freelance и revenue-пайплайны;
- Octopus-модули и крупную библиотеку skills;
- systemd- и Docker-production-контуры, мониторинг и CI/CD.

На момент аудита:

- 5 879 отслеживаемых файлов, 547 328 строк, 22.1 MiB;
- 3 344 Python-файла / 338 405 строк Python;
- AST-разбор всех отслеживаемых Python-файлов: 0 синтаксических ошибок;
- 36 активных `aios-*` systemd-сервисов, 54 таймера, 13 Docker-контейнеров;
- 0 failed systemd-сервисов AIOS;
- production venv использует Python 3.12.13, проект декларирует `>=3.11`.

## Приоритет продукта

Согласно `ROADMAP_NEXT.md`, главный приоритет — v20 «Activation»: перевод уже созданных возможностей в измеримый безопасный production/revenue-контур. Новые каркасные модули без работающего runner запрещены принципом `No new skeletons`.

Фактические названия активных systemd-сервисов содержат v20/v21, но теперь явно считаются версиями отдельных rollout-контуров. Они не повышают package version автоматически. Канонический источник версии основного продукта — `VERSION`; обязательные зеркала и release checklist описаны в `docs/RELEASE_VERSION_POLICY.md`.

## Текущая параллельная работа

На момент верификации активных claims и незакоммиченных файлов нет. Последняя историческая dirty LLM proxy работа завершена в `39bec522`. Перед новой задачей всё равно проверять `coordination/claims/` и `git status`.

## Runtime operator decisions

- `2026-08-17T08:00:00Z`: трейдинг-харденинг по решениям владельца — см. блок
  «Где закончили» выше. Ключевые решения: (1) ML-гейт Directional v2
  калибруется по q90 распределения модели, эффективный порог min(0.65, max(0.50,
  q90)); (2) ws-снапшоты: retention 7д сырые + 60д минутные; (3)
  aios-chrome-colab-secondary stop+disable, BrowserMetrics удалён.

- `2026-08-16T10:46:00Z`: Снижение нагрузки по решению владельца (сценарий D).
  Убиты 9 осиротевших loky-воркеров hyperopt'а (~1.65 ГБ); renice +10 фоновым
  демонам; stop+disable: `aios-viber-desktop`, `aios-viber-autoreply`,
  `aios-vnc-keepawake`, `aios-chrome-vnc`, `aios-signal-desktop` (Viber/Signal/
  SMS-автоматика выключены); `docker stop` для `aios-commercial`, `aios-grafana`,
  `aios-prometheus`, `aios-alertmanager` (commercial-контур и мониторинг-дашборды
  выключены). Снапшоты юнитов: `backups/systemd_20260815/*.loadreduction.bak`.
  Итог: load 75-105 → ~1, Mem available 39 МБ → 2.3 ГБ. Rollback-команды в журнале
  `coordination/sessions/20260816T103000Z-aios-arena-load-reduction.md`.


- `2026-08-15T13:14:35Z`: Дисковая чистка по решению владельца (75G: 81%→46%, свободно 40G; освобождено ~26G). Удалены: Ollama целиком (~16G; сервис stop/disable/remove, unit-бэкап в `backups/systemd_20260815/`; в `.env` ссылок не было, `llm_balancer` упоминает ollama-провайдера — локальный fallback недоступен до переустановки), android-sdk system-images android-35 (~7.3G; эмулятор не запущен, SDK/бинарники сохранены), прун `backups/` (2.9G→1.0G: sessions 2 свежих, daily 3 набора, messenger_profiles 2, manual 3), безопасное (~1G: apt clean, snap cache, /var/crash, старый /tmp). `data/chrome_twin` (1.9G) НЕ удалён: используется активным Chrome (PID-автоматика Google-аккаунта), удаление = потеря сессии авторизации. Журнал: `coordination/sessions/20260815T123500Z-aios-arena-operator-assist.md`.

- `2026-08-15T12:50:40Z`: `aios-gitcoin-algora-solver.service` остановлен и disabled по решению владельца. Причина: сервис слал Telegram-алерты про бесконкурентные баунти (`aios_core/gitcoin_algora_bounty_solver.py`, radar-алерты, цикл 7200с). Юнит сохранён в `deploy/systemd/`, бэкап в `backups/systemd_20260815/`. Других источников таких алертов нет (таймеров нет; freelance-brain уже остановлен 2026-08-14). Журнал: `coordination/sessions/20260815T123500Z-aios-arena-operator-assist.md`.

- `2026-08-15T11:35:00Z`: `aios-groq-key.service` остановлен, disabled и masked (`/dev/null`). Причина: `ExecStart` ссылался на `groq_key_retry.py`, которого нет ни в ФС, ни в git-истории; unit был в restart-loop (7832 рестарта, ~2833/сутки). Функцию выполняет живой преемник `aios-groq-autopilot.timer` (hourly, 8 ключей, status ok). Base unit сохранён в `backups/systemd_20260815/` и в `deploy/systemd/`. Снапшот masks обновлён. Журнал: `coordination/sessions/20260815T113500Z-aios-arena-ops-fixes.md`.

- `2026-08-14T11:23:03Z`: `aios-freelance-brain.service` намеренно остановлен и отключён владельцем; состояние `inactive`, `disabled`, процессов 0. Не запускать/enable без нового решения. Журнал: `coordination/sessions/20260814-aios-arena-freelance-stop.md`.
- `2026-08-14T12:20:00Z`: `aios-quant-trading.service` active/enabled в owner-approved constrained paper profile: отдельный state, max 1 позиция, ML≥0.65, confidence≥0.88, DD/day kill 0.25%. Первый цикл entries=0; live запрещён. Orderbook, Signal Monitor и DeFi risk timers active.

## Главные риски

1. **✅ Дрейф текущей версии — mitigated:** `VERSION` каноничен, API/docs publication используют его цепочку, статические зеркала проверяются тестом, исторические v9/v16 документы помечены snapshot.
2. **✅ Deployment/systemd drift — mitigated:** canonical Compose закреплён; 159 installed unit names, drop-ins, masks и host overrides представлены; strict runtime drift 0, применение units остаётся отдельной operator-approved операцией.
3. **🟡 Крупные модули — controlled:** quant engine уменьшен до 1 898 строк; budgets блокируют рост dashboard/accounts/account-control/quant, следующий seam описан в `docs/MODULE_DECOMPOSITION_PLAN.md`. Остальные монолиты декомпозируются только по одному seam.
4. **✅ Dependency drift — mitigated:** роли minimal 12 / full direct 47 / exact lock 198 формализованы и проверяются; конфликт WebSockets/Web3 устранён, production lock воспроизводим на Python 3.11.
5. **✅ Tracking/ignore risk — mitigated:** глобальный `*.json` удалён, source build-каталог возвращён в Git, runtime/sensitive paths игнорируются точечно и проверяются тестом.
6. **✅ Устаревающие repository metrics — mitigated:** текущие цифры генерируются в `docs/PROJECT_INVENTORY.md`, CI проверяет exact snapshot; старые audit-документы помечены historical.
7. **✅ Негерметичный test baseline — mitigated:** live LLM/runtime paths заменены mocks/tmp fixtures; полный suite зелёный (0 failed; восстановлено 2026-08-17 после фиксов macro/v22).
8. **✅ Runtime/generated artifacts — mitigated:** logs, CatBoost event и debug capture больше не tracked; физические production files сохранены и игнорируются точечно.
9. **✅ LLM proxy/Kilo unfinished work — completed:** 36-model catalog, tool routing/SSE, Colab guards и atomic sync покрыты тестами и развернуты; runtime healthy.
10. **🟡 Trading expectancy — controlled/frozen:** честный OOS walk-forward отрицательный (average −0.354%, PF 0.374); entries/live запрещены, пока новая гипотеза не пройдёт fresh OOS и 30d/200-close gates.

## Следующий рекомендуемый шаг (см. новый блок выше)

## Следующий рекомендуемый шаг

1. Regime v3 и arbitrage-only OOS отклонены. Arbitrage: 90 folds, 1 trade, net −$0.506, positive 0%. Freeze сохраняется; следующий рациональный путь — monitoring/signal product или отдельные high-frequency orderbook данные.
2. Не включать paper entries и live: текущий Directional v2 gate отрицательный.
3. Следующий architecture seam: `tg_bot/accounts.py` context/router + analytics handler.
4. Любое применение versioned systemd units выполняется отдельно с operator approval; массовые restart/disable/remove запрещены.

## Правило обновления этого файла

Обновлять только после значимой завершённой задачи, смены общего приоритета или подтверждённого изменения runtime. Не превращать файл в подробный лог: детали принадлежат отдельным журналам `coordination/sessions/`.
