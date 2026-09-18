"""
Octopus Voice Free Colab Pipeline

Назначение: бесплатная обработка аудио из Google Drive в структуру `!voice`, без Notion и без серверных платных GPU.
Запуск: Google Colab Free GPU -> Runtime -> Change runtime type -> T4/GPU -> выполнить ячейки.

Что делает:
- монтирует Google Drive;
- сканирует TARGET_DIR, пропуская `!voice`;
- транскрибирует openai-whisper;
- делает простую diarization через SpeechBrain ECAPA + AgglomerativeClustering;
- ведёт `!voice/Voice_DB/voiceN.wav`, `voice_names.txt`, `voice_links.txt`;
- опционально читает Google Contacts через People API и пишет подсказки контактов по имени/телефону из пути/имени файла.

Важно: автоматическое сопоставление voiceN -> контакт НЕ делается без подтверждения человека, потому что голос собеседника и голос владельца могут быть перепутаны.
Контакты используются как подсказки в transcript header и `voice_contact_suggestions.txt`.
"""

import os
import re
import json
import time
import traceback
from pathlib import Path

# =========================
# НАСТРОЙКИ
# =========================
TARGET_DIR = os.environ.get("OCTOPUS_TARGET_DIR", "/content/drive/MyDrive/Calls")
VOICE_ROOT = os.path.join(TARGET_DIR, "!voice")
VOICE_DB_DIR = os.path.join(VOICE_ROOT, "Voice_DB")
TRANSCRIPTS_DIR = os.path.join(VOICE_ROOT, "transcripts")
LINKS_PATH = os.path.join(VOICE_ROOT, "voice_links.txt")
NAMES_PATH = os.path.join(VOICE_ROOT, "voice_names.txt")
CONTACTS_CACHE_PATH = os.path.join(VOICE_ROOT, "contacts_cache.json")
CONTACTS_INDEX_PATH = os.path.join(VOICE_ROOT, "contacts_index.txt")
SUGGESTIONS_PATH = os.path.join(VOICE_ROOT, "voice_contact_suggestions.txt")
RUN_LOG_PATH = os.path.join(VOICE_ROOT, "last_run_log.json")

AUDIO_EXTENSIONS = (".m4a", ".mp3", ".mp4", ".wav", ".mpeg", ".aac", ".ogg", ".opus")
WHISPER_MODEL = os.environ.get("OCTOPUS_WHISPER_MODEL", "small")  # tiny/base/small/medium; free Colab: small обычно баланс
LANGUAGE = os.environ.get("OCTOPUS_LANGUAGE", "ru")

MIN_SPEECH_DURATION = float(os.environ.get("OCTOPUS_MIN_SPEECH_DURATION", "0.8"))
MIN_TOTAL_CLUSTER_DURATION = float(os.environ.get("OCTOPUS_MIN_TOTAL_CLUSTER_DURATION", "1.5"))
CLUSTER_THRESHOLD = float(os.environ.get("OCTOPUS_CLUSTER_THRESHOLD", "0.75"))
SIMILARITY_THRESHOLD = float(os.environ.get("OCTOPUS_SIMILARITY_THRESHOLD", "0.42"))
SKIP_DONE = os.environ.get("OCTOPUS_SKIP_DONE", "1") != "0"
USE_GOOGLE_CONTACTS = os.environ.get("OCTOPUS_USE_GOOGLE_CONTACTS", "1") != "0"

# =========================
# COLAB / INSTALL HELPERS
# =========================

def maybe_mount_drive():
    try:
        from google.colab import drive  # type: ignore
        drive.mount("/content/drive")
        return True
    except Exception:
        return False


def ensure_dirs():
    for p in [TARGET_DIR, VOICE_ROOT, VOICE_DB_DIR, TRANSCRIPTS_DIR]:
        os.makedirs(p, exist_ok=True)
    if not os.path.exists(NAMES_PATH):
        with open(NAMES_PATH, "w", encoding="utf-8") as nf:
            nf.write("=== БАЗА СООТНОШЕНИЯ ОБРАЗЦОВ И КОНТАКТОВ ===\n")
            nf.write("# Формат: voice1: Имя Контакта\n")
    if not os.path.exists(LINKS_PATH):
        with open(LINKS_PATH, "w", encoding="utf-8") as lf:
            lf.write("=== ГЛОБАЛЬНАЯ БАЗА ССЫЛОК И ОБНАРУЖЕНИЙ ===\n")
            lf.write("Образец (Имя из контактов) | Путь к папке | Файл созвона | Роль в расшифровке\n")
            lf.write("-" * 85 + "\n")

# =========================
# CONTACTS
# =========================

def normalize_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def load_google_contacts():
    """Бесплатно читает Google Contacts через People API в Colab OAuth. Если не получилось — возвращает []."""
    if not USE_GOOGLE_CONTACTS:
        return []
    try:
        from google.colab import auth  # type: ignore
        auth.authenticate_user()
        from googleapiclient.discovery import build  # type: ignore
        service = build("people", "v1", cache_discovery=False)
        contacts = []
        page_token = None
        while True:
            req = service.people().connections().list(
                resourceName="people/me",
                pageSize=1000,
                personFields="names,phoneNumbers,emailAddresses,organizations",
                pageToken=page_token,
            )
            resp = req.execute()
            for p in resp.get("connections", []):
                names = p.get("names", [])
                phones = p.get("phoneNumbers", [])
                emails = p.get("emailAddresses", [])
                display = ""
                if names:
                    display = names[0].get("displayName") or names[0].get("givenName") or ""
                contacts.append({
                    "name": display,
                    "phones": [x.get("value", "") for x in phones],
                    "phone_digits": [normalize_digits(x.get("value", "")) for x in phones],
                    "emails": [x.get("value", "") for x in emails],
                })
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        with open(CONTACTS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(contacts, f, ensure_ascii=False, indent=2)
        write_contacts_index(contacts)
        print(f"Контакты загружены: {len(contacts)}")
        return contacts
    except Exception as e:
        print(f"Google Contacts недоступны/не разрешены, продолжаю без них: {e}")
        if os.path.exists(CONTACTS_CACHE_PATH):
            try:
                with open(CONTACTS_CACHE_PATH, "r", encoding="utf-8") as f:
                    contacts = json.load(f)
                print(f"Использую contacts_cache.json: {len(contacts)}")
                return contacts
            except Exception:
                pass
        return []


def write_contacts_index(contacts):
    with open(CONTACTS_INDEX_PATH, "w", encoding="utf-8") as f:
        f.write("=== GOOGLE CONTACTS INDEX ДЛЯ OCTOPUS VOICE ===\n")
        for c in contacts:
            phones = ", ".join(c.get("phones") or [])
            emails = ", ".join(c.get("emails") or [])
            f.write(f"{c.get('name','')} | {phones} | {emails}\n")


def contact_hint_for_path(rel_path: str, file_name: str, contacts):
    text = f"{rel_path} {file_name}".lower()
    digits = normalize_digits(text)
    matches = []
    for c in contacts:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        score = 0
        reason = []
        # phone suffix match: последние 7-10 цифр часто достаточно для имени файла/папки
        for pd in c.get("phone_digits") or []:
            if len(pd) >= 7 and (pd[-7:] in digits or (len(pd) >= 10 and pd[-10:] in digits)):
                score += 100
                reason.append("phone")
                break
        # name token match
        tokens = [t for t in re.split(r"\s+", name.lower()) if len(t) >= 3]
        hits = sum(1 for t in tokens if t in text)
        if hits:
            score += hits * 10
            reason.append("name")
        if score:
            matches.append({"name": name, "phones": c.get("phones") or [], "emails": c.get("emails") or [], "score": score, "reason": "+".join(reason)})
    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:5]

# =========================
# VOICE DB / TRANSCRIBE
# =========================

def load_name_mapping():
    mapping = {}
    if os.path.exists(NAMES_PATH):
        with open(NAMES_PATH, "r", encoding="utf-8") as nf:
            for line in nf:
                if ":" in line and not line.startswith("===") and not line.startswith("#"):
                    k, v = line.split(":", 1)
                    mapping[k.strip()] = v.strip()
    return mapping


def append_unknown_voice(name):
    mapping = load_name_mapping()
    if name not in mapping:
        with open(NAMES_PATH, "a", encoding="utf-8") as nf:
            nf.write(f"{name}: Неизвестный\n")


def sklearn_agglomerative(distance_threshold):
    from sklearn.cluster import AgglomerativeClustering
    try:
        return AgglomerativeClustering(n_clusters=None, distance_threshold=distance_threshold, metric="cosine", linkage="average")
    except TypeError:
        return AgglomerativeClustering(n_clusters=None, distance_threshold=distance_threshold, affinity="cosine", linkage="average")


def main():
    maybe_mount_drive()
    ensure_dirs()

    import numpy as np
    import torch
    import whisper
    import scipy.io.wavfile as wavfile
    from scipy.spatial.distance import cosine
    try:
        from speechbrain.inference.speaker import EncoderClassifier
    except Exception:
        from speechbrain.pretrained import EncoderClassifier

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Octopus Voice Free Pipeline: device={device}, whisper={WHISPER_MODEL}, target={TARGET_DIR}")
    whisper_model = whisper.load_model(WHISPER_MODEL, device=device)
    classifier = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": device})

    contacts = load_google_contacts()
    name_mapping = load_name_mapping()

    known_voices = {}
    voice_durations = {}
    max_voice_index = 0
    print("Сканирую Voice_DB...")
    for file in os.listdir(VOICE_DB_DIR):
        if file.lower().endswith(".wav") and file.startswith("voice"):
            name = os.path.splitext(file)[0]
            try:
                max_voice_index = max(max_voice_index, int(name.replace("voice", "")))
            except Exception:
                pass
            ref_path = os.path.join(VOICE_DB_DIR, file)
            try:
                sr, ref_audio = wavfile.read(ref_path)
                duration = len(ref_audio) / float(sr)
                if ref_audio.ndim > 1:
                    ref_audio = ref_audio.mean(axis=1)
                ref_audio_fp = ref_audio.astype(np.float32)
                if np.max(np.abs(ref_audio_fp)) > 1.5:
                    ref_audio_fp = ref_audio_fp / 32767.0
                ref_tensor = torch.tensor(ref_audio_fp).unsqueeze(0).to(device)
                with torch.no_grad():
                    emb = classifier.encode_batch(ref_tensor).squeeze().cpu().numpy()
                known_voices[name] = emb
                voice_durations[name] = duration
            except Exception as e:
                print(f"Не удалось загрузить {file}: {e}")
    print(f"Профилей загружено: {len(known_voices)}; последний индекс voice{max_voice_index}")

    audio_files = []
    for root, dirs, files in os.walk(TARGET_DIR):
        if os.path.abspath(root).startswith(os.path.abspath(VOICE_ROOT)):
            continue
        for file in files:
            if file.lower().endswith(AUDIO_EXTENSIONS):
                audio_files.append(os.path.join(root, file))
    audio_files.sort()
    print(f"Найдено аудио: {len(audio_files)}")

    existing_links = {}
    processed = []
    errors = []

    for file_path in audio_files:
        file_name = os.path.basename(file_path)
        rel_path = os.path.relpath(os.path.dirname(file_path), TARGET_DIR)
        target_output_dir = os.path.join(TRANSCRIPTS_DIR, rel_path)
        os.makedirs(target_output_dir, exist_ok=True)
        base = os.path.splitext(file_name)[0]
        txt_path = os.path.join(target_output_dir, base + "_ai_diarized.txt")
        json_cache_path = os.path.join(target_output_dir, base + "_whisper_cache.json")

        if SKIP_DONE and os.path.exists(txt_path) and os.path.exists(json_cache_path):
            print(f"SKIP готовый: {rel_path}/{file_name}")
            continue

        print(f"\nРазбираем: [{rel_path}] -> {file_name}")
        try:
            contact_hints = contact_hint_for_path(rel_path, file_name, contacts)

            if os.path.exists(json_cache_path):
                with open(json_cache_path, "r", encoding="utf-8") as jf:
                    segments = json.load(jf)
            else:
                audio_np = whisper.load_audio(file_path)
                result = whisper_model.transcribe(audio_np, language=LANGUAGE)
                segments = result.get("segments") or []
                with open(json_cache_path, "w", encoding="utf-8") as jf:
                    json.dump(segments, jf, ensure_ascii=False, indent=2)

            if not segments:
                print("Нет сегментов")
                continue

            audio_np = whisper.load_audio(file_path)
            file_embeddings = []
            valid_segments = []

            for seg in segments:
                duration = float(seg.get("end", 0)) - float(seg.get("start", 0))
                if duration < MIN_SPEECH_DURATION:
                    continue
                start_idx = int(float(seg["start"]) * 16000)
                end_idx = int(float(seg["end"]) * 16000)
                seg_audio = audio_np[start_idx:end_idx]
                if len(seg_audio) < 1600:
                    continue
                seg_tensor = torch.tensor(seg_audio).unsqueeze(0).to(device)
                with torch.no_grad():
                    emb = classifier.encode_batch(seg_tensor).squeeze().cpu().numpy()
                file_embeddings.append(emb)
                valid_segments.append({"seg": seg, "audio": seg_audio, "duration": duration})

            if not file_embeddings:
                print("Нет валидных голосовых сегментов")
                continue

            if len(file_embeddings) > 1:
                local_labels = sklearn_agglomerative(CLUSTER_THRESHOLD).fit(file_embeddings).labels_
            else:
                local_labels = [0]

            unique_labels = set(int(x) for x in local_labels)
            cluster_durations = {l: 0.0 for l in unique_labels}
            cluster_embs = {l: [] for l in unique_labels}
            for idx, l in enumerate(local_labels):
                l = int(l)
                cluster_durations[l] += valid_segments[idx]["duration"]
                cluster_embs[l].append(file_embeddings[idx])
            cluster_centroids = {l: np.mean(cluster_embs[l], axis=0) for l in unique_labels}
            major_clusters = [l for l, dur in cluster_durations.items() if dur >= MIN_TOTAL_CLUSTER_DURATION]
            if not major_clusters and cluster_durations:
                major_clusters = [max(cluster_durations, key=cluster_durations.get)]

            cleared_local_labels = []
            for idx, l in enumerate(local_labels):
                l = int(l)
                if l in major_clusters:
                    cleared_local_labels.append(l)
                else:
                    current_emb = file_embeddings[idx]
                    best_major_l = min(major_clusters, key=lambda ml: cosine(current_emb, cluster_centroids[ml]))
                    cleared_local_labels.append(best_major_l)

            local_to_global_mapping = {}
            for local_spk in major_clusters:
                spk_indices = [idx for idx, label in enumerate(cleared_local_labels) if label == local_spk]
                longest_idx = max(spk_indices, key=lambda idx: valid_segments[idx]["duration"])
                best_audio = valid_segments[longest_idx]["audio"]
                best_emb = file_embeddings[longest_idx]
                best_duration = valid_segments[longest_idx]["duration"]

                global_name = None
                min_dist = float("inf")
                for name, ref_emb in known_voices.items():
                    dist = cosine(best_emb, ref_emb)
                    if dist < min_dist and dist < SIMILARITY_THRESHOLD:
                        min_dist = dist
                        global_name = name

                if global_name:
                    if best_duration > voice_durations.get(global_name, 0):
                        sample_path = os.path.join(VOICE_DB_DIR, f"{global_name}.wav")
                        wavfile.write(sample_path, 16000, (best_audio * 32767).astype(np.int16))
                        voice_durations[global_name] = best_duration
                        print(f" -> Апгрейд слепка {global_name}")
                else:
                    max_voice_index += 1
                    global_name = f"voice{max_voice_index}"
                    known_voices[global_name] = best_emb
                    voice_durations[global_name] = best_duration
                    sample_path = os.path.join(VOICE_DB_DIR, f"{global_name}.wav")
                    wavfile.write(sample_path, 16000, (best_audio * 32767).astype(np.int16))
                    append_unknown_voice(global_name)
                    name_mapping[global_name] = "Неизвестный"
                    print(f" -> Новый голос {global_name}.wav")
                local_to_global_mapping[local_spk] = global_name

            global_to_local_transcript_name = {}
            local_name_counter = 1
            for idx, data in enumerate(valid_segments):
                g_name = local_to_global_mapping[cleared_local_labels[idx]]
                if g_name not in global_to_local_transcript_name:
                    global_to_local_transcript_name[g_name] = f"СОБЕСЕДНИК_{local_name_counter}"
                    local_name_counter += 1

            existing_links[(rel_path, file_name)] = []
            for g_name, transcript_label in global_to_local_transcript_name.items():
                existing_links[(rel_path, file_name)].append((g_name, transcript_label))

            dialogue_lines = []
            for idx, data in enumerate(valid_segments):
                g_name = local_to_global_mapping[cleared_local_labels[idx]]
                transcript_label = global_to_local_transcript_name[g_name]
                seg = data["seg"]
                start_min, start_sec = int(float(seg["start"]) // 60), int(float(seg["start"]) % 60)
                dialogue_lines.append(f"[{start_min:02d}:{start_sec:02d}] {transcript_label}: {seg.get('text','').strip()}")

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("=== СИНХРОННЫЙ РАЗБОР ЗВОНКА ===\n")
                f.write(f"Источник звука: {file_name}\n")
                f.write(f"Папка: {rel_path}\n")
                f.write("КОНТАКТНЫЙ КОНТЕКСТ ПО ПАПКЕ/ФАЙЛУ:\n")
                if contact_hints:
                    for h in contact_hints:
                        f.write(f"  -> возможно: {h['name']} | {', '.join(h.get('phones') or [])} | score={h['score']} ({h['reason']})\n")
                else:
                    f.write("  -> контакты не найдены по имени/телефону в пути/файле\n")
                f.write("КАРТА НАСТОЯЩИХ УЧАСТНИКОВ:\n")
                for g_name, transcript_label in global_to_local_transcript_name.items():
                    current_real_name = name_mapping.get(g_name, "Неизвестный")
                    f.write(f"  -> {transcript_label} это: {g_name} ({current_real_name})\n")
                f.write("-" * 50 + "\n\n")
                f.write("\n".join(dialogue_lines))
                f.write("\n")

            if contact_hints:
                with open(SUGGESTIONS_PATH, "a", encoding="utf-8") as sf:
                    sf.write(f"\n=== {rel_path}/{file_name} ===\n")
                    sf.write("Участники в transcript: " + ", ".join([f"{v}->{r}" for v, r in existing_links[(rel_path, file_name)]]) + "\n")
                    for h in contact_hints:
                        sf.write(f"подсказка: {h['name']} | {', '.join(h.get('phones') or [])} | score={h['score']} | {h['reason']}\n")
                    sf.write("Если уверенно: впиши вручную в voice_names.txt строку вида `voiceN: Имя Контакта`.\n")

            print(f"Готово: {txt_path}; участников: {len(global_to_local_transcript_name)}")
            processed.append({"file": file_path, "txt": txt_path, "speakers": len(global_to_local_transcript_name)})
        except Exception as e:
            print(f"Ошибка обработки {file_name}: {e}")
            traceback.print_exc()
            errors.append({"file": file_path, "error": str(e)})

    if existing_links:
        with open(LINKS_PATH, "w", encoding="utf-8") as lf:
            lf.write("=== ГЛОБАЛЬНАЯ БАЗА ССЫЛОК И ОБНАРУЖЕНИЙ ===\n")
            lf.write("Образец (Имя из контактов) | Путь к папке | Файл созвона | Роль в расшифровке\n")
            lf.write("-" * 85 + "\n")
            for (r_path, f_name), eff_links in sorted(existing_links.items()):
                for v_id, role in eff_links:
                    current_real_name = load_name_mapping().get(v_id, "Неизвестный")
                    lf.write(f"{v_id} ({current_real_name}) | {r_path} | {f_name} | {role}\n")

    run_log = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "target_dir": TARGET_DIR,
        "device": device,
        "whisper_model": WHISPER_MODEL,
        "processed": processed,
        "errors": errors,
    }
    with open(RUN_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(run_log, f, ensure_ascii=False, indent=2)
    print(f"\nГотово. Обработано: {len(processed)}, ошибок: {len(errors)}. Выход: {VOICE_ROOT}")


if __name__ == "__main__":
    main()
