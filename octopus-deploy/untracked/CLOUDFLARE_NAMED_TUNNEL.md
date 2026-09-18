# Named Cloudflare Tunnel — постоянные URL для Octopus

## Зачем
Сейчас сервисы используют quick-tunnel (`trycloudflare.com`), URL меняются при
рестарте. Named tunnel даёт постоянный CNAME-домен.

## Требования
1. Cloudflare аккаунт (бесплатный)
2. Свой домен, зарегистрированный в CF (или nameservers переключены на CF)

## Быстрая настройка (5 минут, 1 раз)

### 1) Авторизация
```bash
cloudflared tunnel login
# Откроется браузер → авторизуйтесь → выберите домен
```
Сохранится `~/.cloudflared/cert.pem`.

### 2) Создание tunnel
```bash
cloudflared tunnel create octopus-main
# Создаст UUID-токен в ~/.cloudflared/<UUID>.json
```

### 3) Создаём config.yml
```bash
mkdir -p /etc/cloudflared
cat > /etc/cloudflared/config.yml << YAML
tunnel: octopus-main
credentials-file: /root/.cloudflared/<UUID>.json
ingress:
  - hostname: ingest.example.com
    service: http://127.0.0.1:9571
  - hostname: audio-v1.example.com
    service: http://127.0.0.1:9560
  - hostname: audio-v2.example.com
    service: http://127.0.0.1:9561
  - hostname: uploader.example.com
    service: http://127.0.0.1:80   # nginx уже отдаёт PWA
    originRequest:
      httpHostHeader: uploader.178.105.142.113.sslip.io
  - hostname: hub.example.com
    service: http://127.0.0.1:80
    originRequest:
      httpHostHeader: hub.178.105.142.113.sslip.io
  - hostname: grafana.example.com
    service: http://127.0.0.1:3000
  - service: http_status:404
YAML
```

### 4) DNS routing (автоматически)
```bash
cloudflared tunnel route dns octopus-main ingest.example.com
cloudflared tunnel route dns octopus-main audio-v1.example.com
cloudflared tunnel route dns octopus-main audio-v2.example.com
cloudflared tunnel route dns octopus-main uploader.example.com
cloudflared tunnel route dns octopus-main hub.example.com
cloudflared tunnel route dns octopus-main grafana.example.com
```

### 5) Запуск как systemd service
```bash
# Заменим quick-tunnel сервисы одним named-tunnel
systemctl disable --now octopus-ingest-tunnel.service
systemctl disable --now octopus-audio-tunnel.service
systemctl disable --now octopus-audio-v2-tunnel.service
systemctl disable --now octopus-devpanel-tunnel.service

# Установим named tunnel
cloudflared service install <TUNNEL_TOKEN>
# или вручную:
cat > /etc/systemd/system/octopus-named-tunnel.service << 'UNIT'
[Unit]
Description=Cloudflare Named Tunnel (octopus-main)
After=network.target
[Service]
Type=simple
ExecStart=/usr/bin/cloudflared tunnel --config /etc/cloudflared/config.yml run
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now octopus-named-tunnel.service
```

## Преимущества
- ✅ Постоянные URL (HTTPS из коробки)
- ✅ Cloudflare WAF, DDoS защита
- ✅ Access policies (Zero Trust) — Email/SSO auth
- ✅ Один процесс вместо 4-х quick-tunnel
- ✅ Не теряются URL при рестарте

## Безопасность
- Access policy: `cloudflared access` → требовать email auth на ingest/grafana
- Service tokens для CI/CD
