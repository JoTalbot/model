# Transport Privacy (Tor / I2P / SOCKS) — План

## Статус: ✅ Реализовано (V2)

## Цель

Маршрутизировать весь исходящий трафик роя через прокси (Tor, SOCKS, HTTP) для приватности и обхода блокировок.

## Реализовано

### V1 (ранее)

- `network.outbound_proxy` в `config.yaml` — один URL для всех исходящих `httpx`:
  - Memory facade (cloud paste, http_links)
  - LLMRouter (OpenRouter, local LLM)
  - Web Parser Pipeline (fetcher, resolver)
- Схемы: `http://`, `https://`, `socks4://`, `socks5://`, `socks5h://`
- Реализация: `swarm/network/outbound_http.py`
- Зависимость: `httpx[socks]` (socksio)

### V2 (текущая сессия)

- **RPCClient** — поддержка SOCKS-прокси для P2P TCP-соединений между нодами
  - `RPCClient(proxy="socks5://127.0.0.1:9050")` маршрутизирует RPC через Tor
  - Использует `python-socks[asyncio]` (входит в `httpx[socks]`)
  - Graceful fallback на прямое соединение если `python-socks` не установлен

### Покрытие

| Компонент | Прокси | Реализовано |
|-----------|--------|-------------|
| LLMRouter (OpenRouter, local) | ✅ httpx proxy | V1 |
| Memory facade (cloud paste) | ✅ httpx proxy | V1 |
| HTTP link fetcher | ✅ httpx proxy | V1 |
| Web Parser Pipeline | ✅ httpx proxy | V1 |
| **RPCClient (P2P)** | ✅ SOCKS | **V2** |
| Kademlia DHT | ❌ UDP, нет прокси | — |
| Gossip Protocol | ❌ UDP, нет прокси | — |

### Конфигурация

```yaml
network:
  outbound_proxy: "socks5://127.0.0.1:9050"  # Tor
```

### Использование с Tor

```bash
# 1. Запустить Tor
tor &  # SOCKS на 9050

# 2. Запустить Gemaxi с прокси
# Весь HTTP + RPC трафик идёт через Tor
python3 node.py start --port 8000
```

## Ограничения

- **Kademlia и Gossip** — UDP-протоколы, не поддерживают SOCKS/Tor. Для полной анонимности P2P нужен I2P или overlay-сеть (отдельная задача).
- **python-socks** — опциональная зависимость; без неё RPC работает напрямую.

## Будущее

- I2P transport для Kademlia/Gossip (требуется SAM bridge)
- WebRTC data channels для browser-to-browser P2P
- Per-component proxy overrides (разные прокси для LLM и P2P)
