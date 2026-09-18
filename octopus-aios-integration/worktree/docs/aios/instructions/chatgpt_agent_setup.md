# Инструкция: ChatGPT Agent Octopus (v2, с авторизацией)
# Дата обновления: 2026-07-02
# Приоритет: ВЫСОКИЙ

## Описание
Агент ChatGPT выполняет диагностические команды на Railway-ноде через защищённый API.

## Endpoint
URL: https://octopus-production-71fe.up.railway.app/g?cmd=[URL_ENCODED_CMD]&nonce=[RANDOM]&token=[TOKEN]

## Авторизация
Token stored: /root/.octopus_railway_token
Token value: [REDACTED — load from /etc/octopus secrets]

Способы передачи:
- Query param: ?token=[TOKEN_FROM_SECRET_STORE]
- Header: Authorization: Bearer [TOKEN_FROM_SECRET_STORE]

## Формат ответа (JSON)
{
  "cmd": "выполненная команда",
  "nonce": "123",
  "exit_code": 0,
  "stdout": "вывод",
  "stderr": "ошибки",
  "node": "octopus-railway-1"
}

## Техническая реализация
- server.py на GitHub: JoTalbot/octopus/server.py
- Railway env: OCTOPUS_API_TOKEN
- Auth: hmac.compare_digest (timing-safe)
- Timeout: 30 секунд
- Платформа: Alpine Linux v3.24, Python 3.11, aiohttp

## Безопасность
- Token required для /g (401 без него)
- /health и /heartbeat — без auth (мониторинг)
- Railway-контейнер изолирован
- Token можно сменить через Railway API variableUpsert
