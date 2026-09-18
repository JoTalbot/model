# Diarization (распознавание спикеров) — план интеграции

## Текущее состояние
- transcriptions.segments хранит JSON [{t0, t1, text}] от whisper.cpp
- Поле speaker сейчас не заполняется
- V2 имеет авточередование спикеров (Я/Собеседник) на основе индекса — это
  эвристика, не реальная диаризация

## Варианты диаризации

### Вариант 1: pyannote.audio (рекомендуется)
- Качество: state-of-the-art
- Лицензия: MIT, но модели требуют принятия пользовательского соглашения
  на huggingface (бесплатно).
- RAM: ~1-2 GB на 10-минутный файл
- CPU: ~3-5× realtime (без GPU)

```bash
pip install pyannote.audio
# huggingface CLI login + accept terms на
#   https://hf.co/pyannote/speaker-diarization-3.1
#   https://hf.co/pyannote/segmentation-3.0
```

```python
from pyannote.audio import Pipeline
pipeline = Pipeline.from_pretrained(
    'pyannote/speaker-diarization-3.1',
    use_auth_token=os.environ['HF_TOKEN'])
diarization = pipeline('audio.wav')
for turn, _, speaker in diarization.itertracks(yield_label=True):
    print(f'{turn.start:.1f}-{turn.end:.1f}: {speaker}')
```

### Вариант 2: simple-diarizer (быстро, без HF token)
- pip install simple-diarizer
- Лицензия MIT, использует SpeechBrain + предобученные модели

### Вариант 3: whisperX (whisper + pyannote, объединено)
- pip install whisperx
- Уже включает diarization pipeline
- Заменяет whisper.cpp полностью

## Интеграция в Octopus
1. Создать /opt/octopus-diarize.py worker, polling transcriptions.status='transcribed'
2. Брать swarm_path, вытащить WAV, прогнать через pyannote
3. Mатчить speaker labels к whisper segments по time-overlap
4. UPDATE segments в JSON со speaker полем
5. Помечать status='done' после форварда

## ENV-точка готова в whisper_worker.py
- DIARIZATION_ENABLED=true   → активировать
- DIARIZATION_BACKEND=pyannote|simple|whisperx
- HF_TOKEN=...                → для pyannote

## Бесплатная альтернатива: VAD-based speaker turn detection
Считаем «переход спикера» там, где silence > 1.5 сек. Грубо, но 0 dependencies.
