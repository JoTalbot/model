#!/usr/bin/env python3
"""
Octopus Eternal Snapshot & Multi-Cloud Publisher
Создает компактный автономный снимок всей системы (инструкции агентов,
конфиги, базы, код) и публикует его в распределенные офф-грид хранилища:
1. HuggingFace Hub (JoTalbot/octopus-eternal)
2. Telegram Chat (частный канал пользователя)
3. AWS S3 (резервный бакет)

Автоматически обновляет dr_manifest.json для 1-строчного запуска на новых серверах.
"""

import os
import sys
import json
import re
import time
import shutil
import hashlib
import fcntl
import subprocess
import urllib.request
from pathlib import Path

# Подключаем HuggingFace Hub из локального venv
sys.path.append("/var/lib/octopus/clip-venv/lib/python3.10/site-packages")
from huggingface_hub import HfApi


def load_env_file(path="/etc/octopus/secrets.env"):
    """Load simple KEY=VALUE secrets without printing them."""
    try:
        p = Path(path)
        if not p.exists():
            return
        for raw in p.read_text(errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass

load_env_file()

CONFIG = {
    "HF_REPO_ID": os.environ.get("HF_REPO_ID", "JoTalbot/octopus-eternal"),
    "HF_TOKEN": os.environ.get("HF_TOKEN", ""),
    "TG_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN", os.environ.get("TG_BOT_TOKEN", "")),
    "TG_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID", os.environ.get("TG_CHAT_ID", "")),
    "S3_BUCKET": os.environ.get("OCTOPUS_ETERNAL_S3_BUCKET", "octopus-packstore-archive-2026"),
    "SNAPSHOT_DIR": os.environ.get("OCTOPUS_ETERNAL_SNAPSHOT_DIR", "/var/lib/octopus/snapshots/eternal"),
    "SNAPSHOT_ARCHIVE": "octopus-eternal-master.tar.zst",
    "DR_MANIFEST": "dr_manifest.json",
    "CHUNK_SIZE_MB": int(os.environ.get("OCTOPUS_ETERNAL_CHUNK_SIZE_MB", "45")),
    "KEEP_LOCAL_ARCHIVE": os.environ.get("OCTOPUS_ETERNAL_KEEP_LOCAL_ARCHIVE", "0") == "1",
}

REQUIRED_SECRET_KEYS = ("HF_TOKEN", "TG_BOT_TOKEN", "TG_CHAT_ID")

def redact(text):
    text = str(text)
    text = re.sub(r"hf_[A-Za-z0-9]+", "hf_[REDACTED]", text)
    text = re.sub(r"bot[0-9]+:[A-Za-z0-9_-]+", "bot[REDACTED]", text)
    text = re.sub(r"(AWS_SECRET_ACCESS_KEY=)[^\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(AWS_ACCESS_KEY_ID=)[^\s]+", r"\1[REDACTED]", text)
    return text

def acquire_lock():
    lock_path = "/run/octopus-eternal-snapshot.lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        return fh
    except BlockingIOError:
        raise RuntimeError("another octopus-eternal-snapshot process is already running")

def validate_config(verbose=False, fatal=False):
    missing = [k for k in REQUIRED_SECRET_KEYS if not CONFIG.get(k)]
    if verbose:
        if missing:
            log("CONFIG CHECK: missing required secret keys: " + ",".join(missing))
        else:
            log("CONFIG CHECK: required secret keys are present; values are not printed")
    if missing and fatal:
        raise RuntimeError("Missing required secret keys: " + ",".join(missing))
    return not missing


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] 🐙 ETERNAL: {msg}")
    # Пишем также в системный лог событий Octopus
    try:
        with open("/var/lib/octopus/event_log.jsonl", "a") as f:
            f.write(json.dumps({"timestamp": time.time(), "event": "eternal_snapshot", "message": msg}) + "\n")
    except Exception:
        pass

def run_cmd(cmd):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        log(f"⚠️ Ошибка команды: {redact(cmd)}\nSTDERR: {redact(res.stderr)}")
    return res

def compute_sha256(filepath):
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192 * 1024):
            sha.update(chunk)
    return sha.hexdigest()

def cleanup_snapshot_artifacts(archive_path):
    """Remove transient local chunks and, by default, the local archive after publish.

    Eternal durability is provided by HF/TG/S3 sources in the DR manifest; keeping
    a ~1GB archive on the same small root/Garage disk causes disk alerts. Set
    OCTOPUS_ETERNAL_KEEP_LOCAL_ARCHIVE=1 only for manual restore drills.
    """
    log("Очистка локальных временных чанков...")
    run_cmd(f"rm -f {os.path.join(CONFIG['SNAPSHOT_DIR'], 'chunk_')}*")
    if not CONFIG.get("KEEP_LOCAL_ARCHIVE") and os.path.exists(archive_path):
        try:
            os.remove(archive_path)
            log(f"Локальный archive удалён после publish/local run для экономии диска: {archive_path}")
        except Exception as e:
            log(f"⚠️ Не удалось удалить локальный archive {archive_path}: {e}")

def prepare_snapshot():
    log("Начало подготовки мастер-снимка системы...")
    os.makedirs(CONFIG["SNAPSHOT_DIR"], exist_ok=True)
    
    archive_path = os.path.join(CONFIG["SNAPSHOT_DIR"], CONFIG["SNAPSHOT_ARCHIVE"])
    if os.path.exists(archive_path):
        os.remove(archive_path)
        
    # Исключаем тяжелые кэши, старые бэкапы, venv и скомпилированные бинарники
    # Код, инструкции, логи, опыт и важные базы сохраняются полностью.
    excludes = [
        "--exclude='var/lib/octopus/backups'",
        "--exclude='var/lib/octopus/snapshots/eternal'",
        "--exclude='var/lib/octopus/memory_pool'",
        "--exclude='var/lib/octopus/quarantine'",
        "--exclude='var/lib/octopus/load_history.jsonl'",
        "--exclude='opt/whisper.cpp'",
        "--exclude='*venv*'",
        "--exclude='node_modules'",
        "--exclude='.next'",
        "--exclude='.cache'",
        "--exclude='__pycache__'",
        "--exclude='*.socket'",
        "--exclude='*.sock'",
        "--exclude='*tmp*'",
    ]
    
    cmd = f"tar --warning=no-file-changed {' '.join(excludes)} -I 'zstd -10 -T0' -cf {archive_path} /root/agents /etc/octopus /var/lib/octopus /opt"
    log(f"Архивация директорий: {cmd}")
    res = run_cmd(cmd)
    # rc=1 допустим: tar так сообщает о "file changed as we read it" (активные проекты)
    if res.returncode > 1:
        raise RuntimeError("snapshot tar failed; see previous log")
    
    archive_size = os.path.getsize(archive_path)
    archive_sha = compute_sha256(archive_path)
    log(f"Снимок создан: {archive_path} (Размер: {archive_size / (1024*1024):.2f} MB, SHA256: {archive_sha})")
    
    # Сплитим архив для загрузки в Telegram (лимит 50MB) и на HF
    split_prefix = os.path.join(CONFIG["SNAPSHOT_DIR"], "chunk_")
    run_cmd(f"rm -f {split_prefix}*")
    res = run_cmd(f"split -b {CONFIG['CHUNK_SIZE_MB']}m {archive_path} {split_prefix}")
    if res.returncode != 0:
        raise RuntimeError("snapshot split failed; see previous log")
    
    chunks = sorted([f for f in os.listdir(CONFIG["SNAPSHOT_DIR"]) if f.startswith("chunk_")])
    log(f"Архив разделен на {len(chunks)} частей: {chunks}")
    # Архив больше не нужен (данные уже в чанках, SHA посчитан) — удаляем сразу,
    # чтобы пик дискового потребления был ~3G, а не ~6G (архив+чанки весь цикл).
    try:
        os.remove(archive_path)
        log(f"Локальный archive удалён сразу после split для экономии диска: {archive_path}")
    except Exception as e:
        log(f"⚠️ Не удалось удалить archive после split: {e}")
    return archive_path, archive_sha, archive_size, chunks

def upload_to_telegram(chunks):
    log("Загрузка частей архива в Telegram (Бессмертная шина данных)...")
    tg_file_ids = {}
    
    for chunk in chunks:
        chunk_path = os.path.join(CONFIG["SNAPSHOT_DIR"], chunk)
        log(f"Отправка {chunk} в Telegram...")
        
        cmd = (
            f"curl -s -F document=@{chunk_path} "
            f"\"https://api.telegram.org/bot{CONFIG['TG_BOT_TOKEN']}/sendDocument?chat_id={CONFIG['TG_CHAT_ID']}\""
        )
        res = run_cmd(cmd)
        try:
            data = json.loads(res.stdout)
            file_id = data["result"]["document"]["file_id"]
            tg_file_ids[chunk] = file_id
            log(f"Успешно отправлен {chunk}, File ID: {file_id[:20]}...")
        except Exception as e:
            for attempt in range(3):
                log(f"⚠️ Telegram для {chunk}: {str(e)[:80]} — retry {attempt+1}/3")
                time.sleep(10)
                res = run_cmd(cmd)
                try:
                    data = json.loads(res.stdout)
                    file_id = data["result"]["document"]["file_id"]
                    tg_file_ids[chunk] = file_id
                    log(f"Успешно отправлен {chunk} (retry), File ID: {file_id[:20]}...")
                    break
                except Exception:
                    continue
        time.sleep(1.5)
            
    return tg_file_ids

def upload_to_huggingface(archive_path, chunks):
    log("Загрузка частей архива на HuggingFace Hub одним commit (Immortal CDN)...")
    api = HfApi(token=CONFIG["HF_TOKEN"])
    hf_urls = {chunk: f"https://huggingface.co/datasets/{CONFIG['HF_REPO_ID']}/resolve/main/snapshots/{chunk}" for chunk in chunks}
    try:
        # Важно: upload_file по одному chunk создаёт много commits и может упереться
        # в HF commit rate-limit. upload_folder с allow_patterns=chunk_* делает один commit.
        api.upload_folder(
            folder_path=CONFIG["SNAPSHOT_DIR"],
            path_in_repo="snapshots",
            repo_id=CONFIG["HF_REPO_ID"],
            repo_type="dataset",
            allow_patterns="chunk_*",
            commit_message=f"Octopus eternal snapshot chunks {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        )
        log(f"HF chunks uploaded in one commit: {len(chunks)} files")
    except Exception as e:
        log(f"⚠️ Ошибка upload_folder chunks на HF: {redact(e)}")
        # URLs детерминированы; оставляем их в manifest только как желаемые источники,
        # но фактическое наличие проверяется DR/read probes.
    return hf_urls

def s3_keys_valid():
    cmd = "export $(grep -v ^# /etc/octopus/secrets.env | xargs) && aws sts get-caller-identity >/dev/null 2>&1"
    return run_cmd(cmd).returncode == 0

def upload_to_s3(archive_path, chunks):
    if not s3_keys_valid():
        log("⚠️ S3 SKIPPED: AWS-ключи невалидны (aws sts failed) — канал пропущен")
        return {}
    log("Загрузка снимка в AWS S3...")
    # Экспортируем переменные AWS
    aws_env = "export $(grep -v '^#' /etc/octopus/secrets.env | xargs)"
    s3_urls = {}
    
    for chunk in chunks:
        chunk_path = os.path.join(CONFIG["SNAPSHOT_DIR"], chunk)
        remote_path = f"s3://{CONFIG['S3_BUCKET']}/eternal_snapshot/{chunk}"
        log(f"Копирование {chunk} в S3: {remote_path}...")
        run_cmd(f"{aws_env} && aws s3 cp {chunk_path} {remote_path}")
        s3_urls[chunk] = remote_path
        
    return s3_urls

def write_local_manifest(archive_sha, archive_size, chunks):
    manifest_path = os.path.join(CONFIG["SNAPSHOT_DIR"], CONFIG["DR_MANIFEST"])
    manifest = {
        "timestamp": int(time.time()),
        "date": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "archive_name": CONFIG["SNAPSHOT_ARCHIVE"],
        "archive_sha256": archive_sha,
        "archive_size_bytes": archive_size,
        "chunks": chunks,
        "sources": {"local_only": True},
        "note": "Local-only manifest after safe prepare; next scheduled full publish should refresh remote sources.",
        "bootstrap_cmd": "curl -sSL https://huggingface.co/datasets/JoTalbot/octopus-eternal/raw/main/octopus-bootstrap.sh | bash"
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest

def update_dr_manifest(archive_sha, archive_size, chunks, tg_file_ids, hf_urls, s3_urls):
    log("Генерация Disaster Recovery Манифеста...")
    
    # Собираем список активных серверов и их IP
    res = run_cmd("hostname -I")
    local_ips = res.stdout.strip().split()
    public_ip_res = run_cmd("curl -4 -s ifconfig.me")
    public_ip = public_ip_res.stdout.strip()
    
    manifest = {
        "timestamp": int(time.time()),
        "date": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "archive_name": CONFIG["SNAPSHOT_ARCHIVE"],
        "archive_sha256": archive_sha,
        "archive_size_bytes": archive_size,
        "chunks": chunks,
        "nodes": {
            "master_public_ip": public_ip,
            "local_ips": local_ips,
        },
        "sources": {
            "huggingface": hf_urls,
            "telegram": tg_file_ids,
            "s3": s3_urls,
        },
        "bootstrap_cmd": "curl -sSL https://huggingface.co/datasets/JoTalbot/octopus-eternal/raw/main/octopus-bootstrap.sh | bash"
    }
    
    manifest_path = os.path.join(CONFIG["SNAPSHOT_DIR"], CONFIG["DR_MANIFEST"])
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        
    log("Публикация dr_manifest.json и octopus-bootstrap.sh на HuggingFace Hub...")
    try:
        api = HfApi(token=CONFIG["HF_TOKEN"])
        api.upload_file(
            path_or_fileobj=manifest_path,
            path_in_repo="dr_manifest.json",
            repo_id=CONFIG["HF_REPO_ID"],
            repo_type="dataset",
        )
        bootstrap_path = "/opt/octopus/octopus-bootstrap.sh"
        if os.path.exists(bootstrap_path):
            api.upload_file(
                path_or_fileobj=bootstrap_path,
                path_in_repo="octopus-bootstrap.sh",
                repo_id=CONFIG["HF_REPO_ID"],
                repo_type="dataset",
            )
        else:
            log(f"ℹ️ Bootstrap script not present locally, skipped HF upload: {bootstrap_path}")
    except Exception as e:
        log(f"⚠️ Ошибка загрузки файлов на HF: {e}")
        
    return manifest

def main():
    if "--check-config" in sys.argv:
        ok = validate_config(verbose=True, fatal=False)
        sys.exit(0 if ok else 2)
    lock_fh = acquire_lock()
    validate_config(verbose=True, fatal=True)
    local_only = ("--local-only" in sys.argv) or ("--prepare-only" in sys.argv)
    log("=== ЗАПУСК ЦИКЛА ВЕЧНОГО СОХРАНЕНИЯ (ETERNAL SNAPSHOT) ===")
    start_t = time.time()
    
    archive_path, archive_sha, archive_size, chunks = prepare_snapshot()
    if local_only:
        write_local_manifest(archive_sha, archive_size, chunks)
        log("LOCAL-ONLY: archive and local manifest prepared; remote upload skipped by flag")
        cleanup_snapshot_artifacts(archive_path)
        elapsed = time.time() - start_t
        log(f"=== LOCAL-ONLY ЦИКЛ УСПЕШНО ЗАВЕРШЕН ЗА {elapsed:.1f} сек ===")
        return
    
    # Параллельно или последовательно отправляем во все каналы
    try:
        hf_urls = upload_to_huggingface(archive_path, chunks)
        tg_ids = upload_to_telegram(chunks)
        s3_urls = upload_to_s3(archive_path, chunks)
        
        manifest = update_dr_manifest(archive_sha, archive_size, chunks, tg_ids, hf_urls, s3_urls)
    finally:
        # Гарантированная очистка локальных артефактов (даже при ошибке публикации)
        cleanup_snapshot_artifacts(archive_path)
    
    elapsed = time.time() - start_t
    log(f"=== ЦИКЛ УСПЕШНО ЗАВЕРШЕН ЗА {elapsed:.1f} сек ===")
    
if __name__ == "__main__":
    main()
