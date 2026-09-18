# Octopus Voice Free Colab Pipeline

Статус: замена предыдущего Google Drive + Contacts + Notion модуля. Notion выключен/убран.

Цель: бесплатно обрабатывать аудио из Google Drive папки `/MyDrive/Calls` и получать структуру как в `!voice`:

- `!voice/Voice_DB/voiceN.wav` — база голосовых слепков;
- `!voice/transcripts/<исходный путь>/*_ai_diarized.txt` — расшифровки диалогов;
- `!voice/voice_names.txt` — ручная карта `voiceN: Имя`;
- `!voice/voice_links.txt` — где какой voiceN встретился;
- `!voice/contacts_cache.json`, `contacts_index.txt`, `voice_contact_suggestions.txt` — бесплатные подсказки из Google Contacts через People API.

## Как запускать бесплатно

1. Открыть Google Colab Free.
2. Runtime → Change runtime type → GPU/T4.
3. Загрузить/открыть `Octopus_Voice_Free_Colab.ipynb`.
4. Выполнить ячейки, разрешить доступ к Google Drive и Contacts.
5. Проверить результат в Google Drive: `/MyDrive/Calls/!voice/`.

## Важное ограничение

Автоматически присваивать `voiceN` конкретному контакту нельзя без подтверждения человека: в записи обычно есть владелец и собеседник, порядок/голос могут быть неоднозначны. Поэтому Contacts используются как подсказки по имени/телефону из папки/файла. После проверки человек правит `voice_names.txt`.

## Настройки

В notebook/script можно менять:

- `TARGET_DIR = "/content/drive/MyDrive/Calls"`
- `WHISPER_MODEL = "small"`
- `CLUSTER_THRESHOLD = 0.50`
- `SIMILARITY_THRESHOLD = 0.42`
- `SKIP_DONE = True`

## DEPRECATED

Пользователь попросил вариант без Colab. Основной pipeline теперь: `/opt/octopus/voice_selfhost/`. Порог clustering синхронизирован: `0.75`.
