# Octopus Voice Selfhost — без Colab, без Notion

Статус: основной вариант вместо Colab. Работает на существующем сервере/ресурсах Octopus, без Google Colab и без Notion.

## Где лежит

- Production: `/opt/octopus/voice_selfhost/`
- Agent copy: `/root/agents/-Octopus/projects/voice_selfhost/`

## Параметры

- `CLUSTER_THRESHOLD=0.75` — задано пользователем 2026-06-19.
- Whisper: `/opt/whisper.cpp/build/bin/whisper-cli`, модель `ggml-small.bin` или fallback `base`.
- Diarization: SpeechBrain ECAPA + sklearn clustering через `/opt/octopus-ingest-venv`.
- Default target: `/mnt/swarm/google_drive_calls/Calls`.

## Запуск без скачивания

Сначала положить аудио в `/mnt/swarm/google_drive_calls/Calls`, затем:

```bash
/opt/octopus/voice_selfhost/run_once.sh
```

Пробный запуск только на 1 файл:

```bash
/opt/octopus/voice_selfhost/run_once.sh --limit 1
```

## Скачивание public Google Drive folder без Colab

```bash
/opt/octopus/voice_selfhost/run_once.sh --download-default-drive --limit 1
```

Это использует `gdown` и public folder link пользователя. Большие скачивания делать осторожно: parent `/` заполнен на ~88%, но target лежит на `/mnt/swarm`.

## Выход

```text
/mnt/swarm/google_drive_calls/Calls/!voice/
  Voice_DB/voiceN.wav
  transcripts/.../*_ai_diarized.txt
  voice_names.txt
  voice_links.txt
  contacts.csv или contacts.vcf можно положить вручную
  contacts_index.txt
  voice_contact_suggestions.txt
  last_run_log.json
```

## Контакты

Без Colab прямой Google Contacts OAuth не используется. Бесплатные варианты:

1. Положить экспорт контактов в `!voice/contacts.csv` или `!voice/contacts.vcf`.
2. Или положить `!voice/contacts_cache.json` формата `[{"name":"...","phones":["..."],"emails":["..."]}]`.

Контакты используются только как подсказки. Привязку `voiceN: Имя` человек подтверждает вручную в `voice_names.txt`.

## Обновление 2026-06-19 20:00 EEST

- Cache WAV теперь имеет стабильный SHA-ключ по относительному пути/размеру/mtime; больше нет повторной конвертации из-за randomized Python `hash()`.
- Если в target folder нет аудио, pipeline быстро завершает run log и не грузит тяжёлые ECAPA/Whisper модели.
- Для больших прогонов по-прежнему использовать `--limit N` и хранить входные аудио на `/mnt/swarm`, не на root `/`.

