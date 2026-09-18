# Octopus SLO (Service Level Objectives)
Версия: 1.0 · Дата: 2026-05-31 · Автор: Arena Agent

## 1. Область действия
SLO применяется к системе Octopus Memory на сервере autosklo-prod (178.105.142.113).
Включает: CAS-API, memory pool, replication, packstore, vector search, monitoring.

## 2. Целевые SLO

### 2.1 Доступность (Availability)
| SLI | Цель | Окно измерения |
|-----|------|---------------|
| CAS-API /healthz отвечает 200 | 99.5% | 30 дней |
| Smoke-тест 0 fail | 99.0% | 30 дней |
| Min 2 независимые копии данных | 100% | всегда |

### 2.2 Целостность данных (Durability)
| SLI | Цель | Окно измерения |
|-----|------|---------------|
| Coverage (3 backends) | 1.0 | непрерывно |
| Manifest SHA256 совпадает между backends | 100% | ежедневно |
| Restore-drill успешен (5 объектов из каждого backend) | 100% | ежедневно |
| Нулевой silent data corruption | 100% | непрерывно |

### 2.3 Производительность (Performance)
| SLI | Цель | Окно измерения |
|-----|------|---------------|
| GET /cas/<sha> (loose) latency p99 | < 50ms | 5 минут |
| GET /cas/<sha> (pack) latency p99 | < 200ms | 5 минут |
| PUT /cas upload (10MB) | < 5s | 5 минут |
| /cas/search (RAG) | < 60s | отдельный запрос |
| /vs/search (vector) | < 2s | отдельный запрос |
| Load average (1m) | < 2× vCPU (8.0) | 5 минут |
| MemAvailable | ≥ 250MB | непрерывно |

### 2.4 Репликация
| SLI | Цель | Окно измерения |
|-----|------|---------------|
| HTTP-репликатор lag | ≤ 15 минут | непрерывно |
| S3 cloud coverage | ≥ 1.0 | ежечасно |
| EC2 node coverage | ≥ 1.0 | ежечасно |
| Pack index sync | 100% | ежедневно |

### 2.5 Безопасность
| SLI | Цель | Окно измерения |
|-----|------|---------------|
| CAS-API: loopback only (кроме tunnel) | 100% | непрерывно |
| Токены не в логах | 100% | непрерывно |
| Encryption (age) доступна | 100% | непрерывно |
| ACL проверяется на каждый read | 100% | непрерывно |

## 3. Error Budget
При 99.5% availability за 30 дней:
- Допустимый downtime: 30д × 24ч × 60мин × 0.005 = 216 минут/месяц
- Если error budget исчерпан > 50%: заморозка деплоев, фокус на стабильности
- Если error budget исчерпан > 80%: инцидент-режим, только hotfix

## 4. Инциденты и Escalation
- **P0 (data loss)**: Немедленно. Проверить restore-drill, восстановить из backup.
- **P1 (service down)**: Автоалерт Telegram. Восстановить < 30 мин.
- **P2 (degraded)**: Smoke warning. Исправить в текущей сессии.
- **P3 (cosmetic)**: Лог, исправить при следующем WAVE.

## 5. Мониторинг
- Smoke: каждые 15 минут (octopus-smoke.timer)
- Coverage alert: каждые 10 минут (octopus-memory-coverage-alert.timer)
- Restore alert: каждые 10 минут (octopus-memory-restore-alert.timer)
- Manifest: ежедневно 05:00 UTC
- Restore drill EC2: ежедневно 04:00 UTC
- Offline snapshot: еженедельно (вторник 06:00 UTC)
- Memory copies audit: каждые 30 минут

## 6. Обновление SLO
SLO пересматривается:
- При изменении архитектуры (новые backends, новый packstore)
- При добавлении новых сервисов
- Ежемесячно — анализ трендов (availability, latency, error rate)

## Дополнение от 2026-05-31 (audio-transcribe сервис)

### Новые SLI
| SLI | Цель | Окно |
|-----|------|------|
| octopus-audio-transcribe.service active | 99.5% | 30 дней |
| /api/health отвечает 200 | 99.5% | 30 дней |
| /api/vsearch (Ollama nomic-embed-text) p99 | < 3s | 5 минут |
| /api/transcribe (Ollama qwen2.5:1.5b) p99 | < 60s | 5 минут |
| pgvector embedding_vec coverage (% непустых) | ≥ 95% | ежедневно |

### Health endpoints (включены в /opt/octopus-health-all.sh)
- http://127.0.0.1:9560/api/health
- http://127.0.0.1:9560/api/vsearch?q=ping&limit=1

### Зависимости
- ollama.service (port 11434)
- postgresql.service (audio_transcribe_db, audio_user)
- pgvector extension 0.8.2

## Дополнение от 2026-05-31 (Ingest + Whisper pipeline)

### Новые SLI
| SLI | Цель | Окно |
|-----|------|------|
| octopus-ingest.service /healthz=200 | 99.5% | 30 дней |
| octopus-whisper-worker.service active | 99.0% | 30 дней |
| CAS coverage (cas_pushed/uploads) | ≥ 0.95 | непрерывно |
| Forwarded coverage (forwarded/uploads) | ≥ 0.90 | непрерывно |
| Whisper failure rate (failed/(done+failed)) | ≤ 0.05 | 24h |
| Whisper avg processing (per audio second) | ≤ 1.5× realtime | 5 мин |
| Inbox watcher lag (file appears → /ingest) | ≤ 90s | непрерывно |

### Зависимости
- whisper.cpp build /opt/whisper.cpp/build/bin/whisper-cli
- model /opt/whisper.cpp/models/ggml-base.bin (140MB)
- ffmpeg для конвертации
- Ollama (для V1/V2 после whisper)
- pgvector в audio_transcribe_db

### Health endpoints
- http://127.0.0.1:9571/healthz
- http://127.0.0.1:9571/metrics
