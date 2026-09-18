#!/usr/bin/env python3
"""
Octopus Voice Selfhost Pipeline — без Colab, без Notion.

Вход: локальная папка с аудио (по умолчанию /mnt/swarm/google_drive_calls/Calls).
Опционально умеет скачать public Google Drive folder через gdown (--drive-url / --drive-folder-id).
Выход: структура !voice как в старом Colab-скрипте.

Транскрипция: whisper.cpp (CPU, ggml-small/base).
Diarization: SpeechBrain ECAPA + sklearn AgglomerativeClustering.
Контакты: локальные файлы !voice/contacts.csv, !voice/contacts.vcf, !voice/contacts_cache.json
как бесплатная альтернатива Google Contacts OAuth. Автопривязка voiceN->контакт НЕ делается.
"""

import argparse
import hashlib
import csv
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from scipy.io import wavfile
from scipy.spatial.distance import cosine
from sklearn.cluster import AgglomerativeClustering
from speechbrain.inference.speaker import EncoderClassifier

AUDIO_EXTENSIONS = ('.m4a', '.mp3', '.mp4', '.wav', '.mpeg', '.aac', '.ogg', '.opus', '.flac', '.webm', '.3gp', '.amr')
DEFAULT_TARGET_DIR = '/mnt/swarm/google_drive_calls/Calls'
DEFAULT_DRIVE_URL = 'https://drive.google.com/drive/folders/1zAKjmh0Yh92SkJ-erYy4Xafhv19VY-yN?usp=sharing'
WHISPER_BIN = '/opt/whisper.cpp/build/bin/whisper-cli'
WHISPER_MODELS_DIR = '/opt/whisper.cpp/models'
ECAPA_MODEL_DIR = '/opt/octopus-models/ecapa'

# Запрошено пользователем 2026-06-19
DEFAULT_CLUSTER_THRESHOLD = 0.75


def run(cmd, timeout=None, check=False):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed {cmd}: {r.stderr[-1000:]}")
    return r


def normalize_digits(s: str) -> str:
    return re.sub(r'\D+', '', s or '')


def ensure_dirs(target_dir: Path):
    voice_root = target_dir / '!voice'
    dirs = {
        'voice_root': voice_root,
        'voice_db': voice_root / 'Voice_DB',
        'transcripts': voice_root / 'transcripts',
        'cache': voice_root / '.cache',
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    names_path = voice_root / 'voice_names.txt'
    links_path = voice_root / 'voice_links.txt'
    if not names_path.exists():
        names_path.write_text('=== БАЗА СООТНОШЕНИЯ ОБРАЗЦОВ И КОНТАКТОВ ===\n# Формат: voice1: Имя Контакта\n', encoding='utf-8')
    if not links_path.exists():
        links_path.write_text('=== ГЛОБАЛЬНАЯ БАЗА ССЫЛОК И ОБНАРУЖЕНИЙ ===\nОбразец (Имя из контактов) | Путь к папке | Файл созвона | Роль в расшифровке\n' + '-'*85 + '\n', encoding='utf-8')
    return dirs




def stable_cache_key(file_path: Path, target_dir: Path) -> str:
    """Stable cache key across Python processes/runs.

    Built-in hash() is intentionally randomized per process and caused repeated
    ffmpeg conversions/cache growth. Include relative path + size + mtime so
    changed files get a fresh cache while unchanged files reuse WAV.
    """
    try:
        rel = str(file_path.resolve().relative_to(target_dir.resolve()))
    except Exception:
        rel = str(file_path.resolve())
    try:
        st = file_path.stat()
        raw = f'{rel}|{st.st_size}|{int(st.st_mtime)}'
    except Exception:
        raw = rel
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', file_path.stem)[:80] or 'audio'
    return hashlib.sha256(raw.encode('utf-8', errors='ignore')).hexdigest()[:16] + '_' + safe

def maybe_download_drive(url: str, out_dir: Path):
    if not url:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f'Синхронизирую public Google Drive folder через gdown -> {out_dir}')
    try:
        import gdown
        # remaining_ok=True позволяет продолжить, если часть файлов уже есть.
        gdown.download_folder(url=url, output=str(out_dir), quiet=False, use_cookies=False)
    except Exception as e:
        print(f'WARN: gdown download_folder не сработал: {e}', file=sys.stderr)
        print('Продолжаю с тем, что уже есть локально.', file=sys.stderr)


def load_name_mapping(names_path: Path):
    mapping = {}
    if names_path.exists():
        for line in names_path.read_text(encoding='utf-8', errors='ignore').splitlines():
            if ':' in line and not line.startswith('===') and not line.startswith('#'):
                k, v = line.split(':', 1)
                mapping[k.strip()] = v.strip()
    return mapping


def append_unknown_voice(names_path: Path, name: str):
    mapping = load_name_mapping(names_path)
    if name not in mapping:
        with names_path.open('a', encoding='utf-8') as f:
            f.write(f'{name}: Неизвестный\n')


def parse_vcf(path: Path):
    contacts = []
    cur = {}
    for raw in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = raw.strip()
        if line == 'BEGIN:VCARD':
            cur = {}
        elif line == 'END:VCARD':
            if cur.get('name') or cur.get('phones'):
                contacts.append({'name': cur.get('name', ''), 'phones': cur.get('phones', []), 'emails': cur.get('emails', [])})
            cur = {}
        elif line.startswith('FN:'):
            cur['name'] = line[3:].strip()
        elif line.startswith('TEL') and ':' in line:
            cur.setdefault('phones', []).append(line.split(':', 1)[1].strip())
        elif line.startswith('EMAIL') and ':' in line:
            cur.setdefault('emails', []).append(line.split(':', 1)[1].strip())
    return contacts


def load_contacts(voice_root: Path):
    contacts = []
    cache = voice_root / 'contacts_cache.json'
    csvp = voice_root / 'contacts.csv'
    vcfp = voice_root / 'contacts.vcf'
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding='utf-8'))
            if isinstance(data, list):
                contacts.extend(data)
        except Exception:
            pass
    if csvp.exists():
        with csvp.open(newline='', encoding='utf-8', errors='ignore') as f:
            for row in csv.DictReader(f):
                name = row.get('name') or row.get('Name') or row.get('displayName') or row.get('Display Name') or ''
                phones = [row.get(k, '') for k in row.keys() if 'phone' in k.lower() and row.get(k)]
                emails = [row.get(k, '') for k in row.keys() if 'email' in k.lower() and row.get(k)]
                if name or phones:
                    contacts.append({'name': name, 'phones': phones, 'emails': emails})
    if vcfp.exists():
        contacts.extend(parse_vcf(vcfp))
    # normalize/dedupe
    out, seen = [], set()
    for c in contacts:
        name = (c.get('name') or '').strip()
        phones = [p for p in (c.get('phones') or []) if p]
        emails = [e for e in (c.get('emails') or []) if e]
        key = (name.lower(), tuple(sorted(normalize_digits(p) for p in phones)))
        if key in seen:
            continue
        seen.add(key)
        out.append({'name': name, 'phones': phones, 'phone_digits': [normalize_digits(p) for p in phones], 'emails': emails})
    (voice_root / 'contacts_index.txt').write_text('\n'.join([f"{c['name']} | {', '.join(c['phones'])} | {', '.join(c['emails'])}" for c in out]) + ('\n' if out else ''), encoding='utf-8')
    return out


def contact_hints(rel_path: str, file_name: str, contacts):
    text = f'{rel_path} {file_name}'.lower()
    digits = normalize_digits(text)
    matches = []
    for c in contacts:
        score, reasons = 0, []
        for pd in c.get('phone_digits') or []:
            if len(pd) >= 7 and (pd[-7:] in digits or (len(pd) >= 10 and pd[-10:] in digits)):
                score += 100; reasons.append('phone'); break
        name = c.get('name') or ''
        tokens = [t for t in re.split(r'\s+', name.lower()) if len(t) >= 3]
        hits = sum(1 for t in tokens if t in text)
        if hits:
            score += hits * 10; reasons.append('name')
        if score:
            matches.append({'name': name, 'phones': c.get('phones') or [], 'emails': c.get('emails') or [], 'score': score, 'reason': '+'.join(reasons)})
    return sorted(matches, key=lambda x: x['score'], reverse=True)[:5]


def model_path(name: str) -> str:
    return f'{WHISPER_MODELS_DIR}/ggml-{name}.bin'


def convert_to_wav(src: Path, dst: Path):
    if dst.exists() and dst.stat().st_size > 1000:
        return
    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(src), '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(dst)]
    run(cmd, timeout=1800, check=True)


def transcribe_whispercpp(wav_path: Path, segments_cache: Path, model='small', lang='ru', threads='4'):
    if segments_cache.exists():
        try:
            return json.loads(segments_cache.read_text(encoding='utf-8'))
        except Exception:
            pass
    m = model if Path(model_path(model)).exists() else 'base'
    out_prefix = str(segments_cache.with_suffix(''))
    cmd = [WHISPER_BIN, '-m', model_path(m), '-f', str(wav_path), '-t', str(threads), '-nt', '-oj', '-otxt', '-of', out_prefix, '-l', lang]
    print('Whisper:', ' '.join(cmd))
    r = run(cmd, timeout=7200)
    if r.returncode != 0:
        raise RuntimeError(f'whisper.cpp failed: {r.stderr[-1000:]}')
    jpath = Path(out_prefix + '.json')
    if not jpath.exists():
        raise RuntimeError('whisper.cpp did not produce json')
    j = json.loads(jpath.read_text(encoding='utf-8', errors='ignore'))
    segs = []
    for s in j.get('transcription', []):
        off = s.get('offsets') or {}
        segs.append({'start': float(off.get('from', 0))/1000.0, 'end': float(off.get('to', 0))/1000.0, 'text': (s.get('text') or '').strip()})
    segments_cache.write_text(json.dumps(segs, ensure_ascii=False, indent=2), encoding='utf-8')
    # Clean raw txt/json copies; keep normalized cache.
    for p in [jpath, Path(out_prefix + '.txt')]:
        try: p.unlink()
        except Exception: pass
    return segs


def load_voice_db(voice_db: Path, classifier, device):
    known, durations, max_idx = {}, {}, 0
    for file in sorted(voice_db.glob('voice*.wav')):
        name = file.stem
        try:
            max_idx = max(max_idx, int(name.replace('voice', '')))
        except Exception:
            pass
        try:
            sr, audio = wavfile.read(str(file))
            dur = len(audio)/float(sr)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            audio = audio.astype(np.float32)
            if np.max(np.abs(audio)) > 1.5:
                audio = audio / 32767.0
            with torch.no_grad():
                emb = classifier.encode_batch(torch.tensor(audio).unsqueeze(0).to(device)).squeeze().cpu().numpy()
            known[name] = emb; durations[name] = dur
        except Exception as e:
            print(f'WARN: cannot load voice sample {file}: {e}', file=sys.stderr)
    return known, durations, max_idx


def clusterer(threshold):
    try:
        return AgglomerativeClustering(n_clusters=None, distance_threshold=threshold, metric='cosine', linkage='average')
    except TypeError:
        return AgglomerativeClustering(n_clusters=None, distance_threshold=threshold, affinity='cosine', linkage='average')


def fmt_ts(sec):
    sec = int(sec or 0)
    return f'{sec//60:02d}:{sec%60:02d}'


def process(args):
    target_dir = Path(args.target_dir).resolve()
    if args.drive_url:
        maybe_download_drive(args.drive_url, target_dir)
    dirs = ensure_dirs(target_dir)
    names_path = dirs['voice_root'] / 'voice_names.txt'
    links_path = dirs['voice_root'] / 'voice_links.txt'
    suggestions_path = dirs['voice_root'] / 'voice_contact_suggestions.txt'
    contacts = load_contacts(dirs['voice_root'])
    print(f'Контактов локально: {len(contacts)}')

    audio_files = []
    for root, _, files in os.walk(target_dir):
        rootp = Path(root)
        if str(rootp.resolve()).startswith(str(dirs['voice_root'].resolve())):
            continue
        for fn in files:
            if fn.lower().endswith(AUDIO_EXTENSIONS):
                audio_files.append(rootp / fn)
    audio_files.sort()
    if args.limit:
        audio_files = audio_files[:args.limit]
    print(f'Аудиофайлов к проверке: {len(audio_files)}')

    all_links = {}
    processed, errors = [], []
    if not audio_files:
        run_log = {
            'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
            'target_dir': str(target_dir),
            'cluster_threshold': args.cluster_threshold,
            'processed': processed,
            'errors': errors,
            'note': 'no audio files; ECAPA/Whisper not loaded'
        }
        (dirs['voice_root'] / 'last_run_log.json').write_text(json.dumps(run_log, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\nИтог: processed=0, errors=0, output={dirs['voice_root']} (no audio files; heavy models skipped)")
        return

    device = 'cpu'
    print(f'Загружаю ECAPA на {device}; CLUSTER_THRESHOLD={args.cluster_threshold}')
    classifier = EncoderClassifier.from_hparams(source='speechbrain/spkrec-ecapa-voxceleb', savedir=ECAPA_MODEL_DIR, run_opts={'device': device})
    known_voices, voice_durations, max_voice_index = load_voice_db(dirs['voice_db'], classifier, device)
    print(f'Voice DB: {len(known_voices)} profiles, last voice{max_voice_index}')

    for file_path in audio_files:
        rel_path = os.path.relpath(file_path.parent, target_dir)
        file_name = file_path.name
        out_dir = dirs['transcripts'] / rel_path
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_base = file_path.stem
        txt_path = out_dir / f'{safe_base}_ai_diarized.txt'
        cache_json = out_dir / f'{safe_base}_whisper_cache.json'
        cache_wav = dirs['cache'] / f'{stable_cache_key(file_path, target_dir)}.wav'

        if args.skip_done and txt_path.exists() and cache_json.exists():
            print(f'SKIP done: {rel_path}/{file_name}')
            continue
        print(f'\n=== {rel_path}/{file_name} ===')
        try:
            convert_to_wav(file_path, cache_wav)
            segments = transcribe_whispercpp(cache_wav, cache_json, model=args.whisper_model, lang=args.lang, threads=str(args.threads))
            if not segments:
                print('Нет whisper segments')
                continue
            audio_np, sr = sf.read(str(cache_wav), dtype='float32')
            if audio_np.ndim > 1:
                audio_np = audio_np.mean(axis=1)
            file_embeddings, valid_segments = [], []
            for seg in segments:
                dur = float(seg.get('end', 0)) - float(seg.get('start', 0))
                if dur < args.min_speech_duration:
                    continue
                start_idx = int(float(seg['start']) * sr)
                end_idx = int(float(seg['end']) * sr)
                seg_audio = audio_np[start_idx:end_idx]
                if len(seg_audio) < int(sr * 0.25):
                    continue
                with torch.no_grad():
                    emb = classifier.encode_batch(torch.tensor(seg_audio).unsqueeze(0).to(device)).squeeze().cpu().numpy()
                file_embeddings.append(emb)
                valid_segments.append({'seg': seg, 'audio': seg_audio, 'duration': dur})
            if not file_embeddings:
                print('Нет валидных сегментов для voice-id')
                continue

            if len(file_embeddings) > 1:
                local_labels = clusterer(args.cluster_threshold).fit(file_embeddings).labels_
            else:
                local_labels = [0]
            unique = set(int(x) for x in local_labels)
            cluster_durations = {l: 0.0 for l in unique}
            cluster_embs = {l: [] for l in unique}
            for idx, l in enumerate(local_labels):
                l = int(l); cluster_durations[l] += valid_segments[idx]['duration']; cluster_embs[l].append(file_embeddings[idx])
            centroids = {l: np.mean(cluster_embs[l], axis=0) for l in unique}
            major = [l for l, dur in cluster_durations.items() if dur >= args.min_total_cluster_duration]
            if not major:
                major = [max(cluster_durations, key=cluster_durations.get)]
            cleared = []
            for idx, l in enumerate(local_labels):
                l = int(l)
                if l in major:
                    cleared.append(l)
                else:
                    cleared.append(min(major, key=lambda ml: cosine(file_embeddings[idx], centroids[ml])))

            local_to_global = {}
            for local_spk in major:
                idxs = [i for i, label in enumerate(cleared) if label == local_spk]
                longest_idx = max(idxs, key=lambda i: valid_segments[i]['duration'])
                best_emb = file_embeddings[longest_idx]
                best_audio = valid_segments[longest_idx]['audio']
                best_duration = valid_segments[longest_idx]['duration']
                global_name, min_dist = None, float('inf')
                for name, ref_emb in known_voices.items():
                    dist = cosine(best_emb, ref_emb)
                    if dist < min_dist and dist < args.similarity_threshold:
                        min_dist = dist; global_name = name
                if global_name:
                    if best_duration > voice_durations.get(global_name, 0):
                        wavfile.write(str(dirs['voice_db'] / f'{global_name}.wav'), int(sr), (best_audio * 32767).astype(np.int16))
                        voice_durations[global_name] = best_duration
                        print(f' -> обновлён слепок {global_name}')
                else:
                    max_voice_index += 1
                    global_name = f'voice{max_voice_index}'
                    known_voices[global_name] = best_emb
                    voice_durations[global_name] = best_duration
                    wavfile.write(str(dirs['voice_db'] / f'{global_name}.wav'), int(sr), (best_audio * 32767).astype(np.int16))
                    append_unknown_voice(names_path, global_name)
                    print(f' -> новый голос {global_name}')
                local_to_global[local_spk] = global_name

            global_to_role, counter = {}, 1
            for idx in range(len(valid_segments)):
                g = local_to_global[cleared[idx]]
                if g not in global_to_role:
                    global_to_role[g] = f'СОБЕСЕДНИК_{counter}'; counter += 1
            all_links[(rel_path, file_name)] = [(g, role) for g, role in global_to_role.items()]
            name_mapping = load_name_mapping(names_path)
            hints = contact_hints(rel_path, file_name, contacts)

            lines = []
            for idx, data in enumerate(valid_segments):
                g = local_to_global[cleared[idx]]
                role = global_to_role[g]
                seg = data['seg']
                lines.append(f"[{fmt_ts(seg.get('start', 0))}] {role}: {(seg.get('text') or '').strip()}")
            with txt_path.open('w', encoding='utf-8') as f:
                f.write('=== СИНХРОННЫЙ РАЗБОР ЗВОНКА ===\n')
                f.write(f'Источник звука: {file_name}\n')
                f.write(f'Папка: {rel_path}\n')
                f.write(f'CLUSTER_THRESHOLD: {args.cluster_threshold}\n')
                f.write('КОНТАКТНЫЙ КОНТЕКСТ ПО ПАПКЕ/ФАЙЛУ:\n')
                if hints:
                    for h in hints:
                        f.write(f"  -> возможно: {h['name']} | {', '.join(h.get('phones') or [])} | score={h['score']} ({h['reason']})\n")
                else:
                    f.write('  -> локальные контакты не найдены по имени/телефону в пути/файле\n')
                f.write('КАРТА НАСТОЯЩИХ УЧАСТНИКОВ:\n')
                for g, role in global_to_role.items():
                    f.write(f"  -> {role} это: {g} ({name_mapping.get(g, 'Неизвестный')})\n")
                f.write('-'*50 + '\n\n')
                f.write('\n'.join(lines) + '\n')

            if hints:
                with suggestions_path.open('a', encoding='utf-8') as sfp:
                    sfp.write(f'\n=== {rel_path}/{file_name} ===\n')
                    sfp.write('Участники: ' + ', '.join([f'{g}->{r}' for g, r in all_links[(rel_path, file_name)]]) + '\n')
                    for h in hints:
                        sfp.write(f"подсказка: {h['name']} | {', '.join(h.get('phones') or [])} | score={h['score']} | {h['reason']}\n")
                    sfp.write('Если уверенно: вручную вписать в voice_names.txt строку `voiceN: Имя Контакта`.\n')
            print(f'Готово: {txt_path}; участников: {len(global_to_role)}')
            processed.append({'file': str(file_path), 'txt': str(txt_path), 'speakers': len(global_to_role)})
        except Exception as e:
            print(f'ERROR {file_path}: {e}', file=sys.stderr)
            traceback.print_exc()
            errors.append({'file': str(file_path), 'error': str(e)})

    if all_links:
        name_mapping = load_name_mapping(names_path)
        with links_path.open('w', encoding='utf-8') as lf:
            lf.write('=== ГЛОБАЛЬНАЯ БАЗА ССЫЛОК И ОБНАРУЖЕНИЙ ===\n')
            lf.write('Образец (Имя из контактов) | Путь к папке | Файл созвона | Роль в расшифровке\n')
            lf.write('-'*85 + '\n')
            for (rp, fn), rows in sorted(all_links.items()):
                for vid, role in rows:
                    lf.write(f"{vid} ({name_mapping.get(vid, 'Неизвестный')}) | {rp} | {fn} | {role}\n")
    run_log = {'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'target_dir': str(target_dir), 'cluster_threshold': args.cluster_threshold, 'processed': processed, 'errors': errors}
    (dirs['voice_root'] / 'last_run_log.json').write_text(json.dumps(run_log, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nИтог: processed={len(processed)}, errors={len(errors)}, output={dirs['voice_root']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target-dir', default=os.environ.get('OCTOPUS_VOICE_TARGET_DIR', DEFAULT_TARGET_DIR))
    ap.add_argument('--drive-url', default=os.environ.get('OCTOPUS_VOICE_DRIVE_URL', ''))
    ap.add_argument('--download-default-drive', action='store_true', help='скачать public folder пользователя в target-dir через gdown')
    ap.add_argument('--cluster-threshold', type=float, default=float(os.environ.get('CLUSTER_THRESHOLD', DEFAULT_CLUSTER_THRESHOLD)))
    ap.add_argument('--similarity-threshold', type=float, default=float(os.environ.get('SIMILARITY_THRESHOLD', '0.42')))
    ap.add_argument('--min-speech-duration', type=float, default=float(os.environ.get('MIN_SPEECH_DURATION', '0.8')))
    ap.add_argument('--min-total-cluster-duration', type=float, default=float(os.environ.get('MIN_TOTAL_CLUSTER_DURATION', '1.5')))
    ap.add_argument('--whisper-model', default=os.environ.get('WHISPER_MODEL', 'small'))
    ap.add_argument('--lang', default=os.environ.get('WHISPER_LANG', 'ru'))
    ap.add_argument('--threads', type=int, default=int(os.environ.get('WHISPER_THREADS', '4')))
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--no-skip-done', dest='skip_done', action='store_false')
    ap.set_defaults(skip_done=True)
    args = ap.parse_args()
    if args.download_default_drive and not args.drive_url:
        args.drive_url = DEFAULT_DRIVE_URL
    process(args)

if __name__ == '__main__':
    main()
