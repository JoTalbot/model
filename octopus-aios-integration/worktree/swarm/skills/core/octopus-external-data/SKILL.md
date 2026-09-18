---
name: octopus-external-data
version: 1.0
description: Bounded-read-only интеграция с внешними бесплатными API (CoinGecko, Wikipedia, OpenAlex, ip-api, crt.sh, Open-Meteo)
triggers: [external_data, autonomous_cycle, learning]
dependencies: []
llm_required: false
mcp_tools: []
---

# Skill: octopus-external-data

## Описание
Bounded-read-only загрузчик внешних данных для автономного агента Octopus.
Интегрирует бесплатные API без авторизации для enrichment experience и bounded-решений.

## Источники
1. **CoinGecko** — crypto prices (BTC, ETH, SOL и др.)
2. **Wikipedia** — knowledge base, фактчекинг
3. **OpenAlex** — 250M+ academic papers
4. **ip-api.com** — IP geolocation, ASN, провайдер
5. **crt.sh** — SSL certificate transparency log
6. **Open-Meteo** — weather forecast

## Алгоритм
1. Проверить кэш (TTL 1 час) в `logs/external_cache/`
2. Если cache miss — fetch из внешнего API
3. Кэшировать результат
4. Вернуть JSON с score (штраф за недоступные источники)
5. Никогда не писать в систему без explicit bounded команды

## Безопасность
- Read-only по умолчанию
- Нет credential leakage
- Все запросы через HTTPS (кроме ip-api.com — HTTP, только IP)
- User-Agent: `Octopus-Agent/1.0`
- Rate limits уважаются через кэширование

## Контроль и развитие
- Runtime: `code/run.py --json`
- Contract tests: `tests/test_contract.py`
