#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Octopus Drive → Contacts → Notion Automation

Рекурсивно сканирует заданную папку Google Drive, находит аудиофайлы (.mp3, .m4a),
определяет контекст (имя вложенной папки), сопоставляет с контактом Google People,
создаёт карточку в базе Notion с приоритетом по ключевым словам.

Сохраняет обработанные файлы в processed_files.json, чтобы не обрабатывать повторно.
"""

import os
import re
import sys
import json
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, asdict

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
]

AUDIO_EXTENSIONS = {".mp3", ".m4a"}

CRITICAL_KEYWORDS = ["ВСП", "задержание", "адвокат"]

DEFAULT_FOLDER_ID = "1zAKjmh0Yh92SkJ-erYy4Xafhv19VY-yN"

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("drive_notion_sync")


# ---------------------------------------------------------------------------
# Модели данных
# ---------------------------------------------------------------------------

@dataclass
class AudioFile:
    file_id: str
    name: str
    mime_type: str
    size: int
    modified_time: str
    folder_path: str  # путь от корневой папки, например "Иванов/разговор.mp3"
    folder_name: str  # непосредственно имя родительской папки
    web_view_link: str
    download_url: Optional[str] = None


@dataclass
class ContactInfo:
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    source: str = "folder_name"  # "google_contacts" или "folder_name"


@dataclass
class NotionTask:
    title: str
    contact: str
    status: str
    priority: str
    context: str
    file_url: str


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def sanitize(text: str) -> str:
    """Очищает строку для логов/Notion."""
    if not text:
        return ""
    return text.strip().replace("\n", " ").replace("\r", "")


def file_hash(file_id: str, modified_time: str) -> str:
    """Уникальный хеш обработанного файла."""
    return hashlib.sha256(f"{file_id}::{modified_time}".encode()).hexdigest()[:16]


def priority_score(filename: str, folder_name: str) -> Tuple[str, List[str]]:
    """
    Определяет приоритет по ключевым словам.
    Возвращает (priority, matched_keywords).
    """
    text = f"{filename} {folder_name}".lower()
    matched = []
    for kw in CRITICAL_KEYWORDS:
        if kw.lower() in text:
            matched.append(kw)
    return ("Критический" if matched else "Обычный", matched)


# ---------------------------------------------------------------------------
# Google OAuth2
# ---------------------------------------------------------------------------

def get_google_credentials(
    credentials_path: str = "credentials.json",
    token_path: str = "token.json",
) -> Credentials:
    """
    Авторизация OAuth2 для Google Drive + People API.
    При первом запуске открывает браузер для подтверждения.
    """
    creds = None
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            log.info("Загружен существующий токен: %s", token_path)
        except Exception as exc:
            log.warning("Не удалось прочитать token.json: %s", exc)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Обновление токена...")
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"Не найден {credentials_path}. Создайте OAuth2 клиент в "
                    "Google Cloud Console и скачайте credentials.json."
                )
            log.info("Запуск OAuth2 flow... Откройте браузер для авторизации.")
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Сохраняем токен
        with open(token_path, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())
        log.info("Токен сохранён: %s", token_path)

    return creds


# ---------------------------------------------------------------------------
# Google Drive: рекурсивный скан
# ---------------------------------------------------------------------------

class DriveScanner:
    def __init__(self, service: build):
        self.service = service

    def _list_page(self, folder_id: str, page_token: Optional[str] = None) -> Tuple[List[Dict], Optional[str]]:
        q = f"'{folder_id}' in parents and trashed = false"
        try:
            resp = (
                self.service.files()
                .list(
                    q=q,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink, fileExtension)",
                    pageToken=page_token,
                    pageSize=100,
                )
                .execute()
            )
            return resp.get("files", []), resp.get("nextPageToken")
        except HttpError as exc:
            log.error("Ошибка Drive API при чтении папки %s: %s", folder_id, exc)
            return [], None

    def scan_recursive(
        self,
        root_folder_id: str,
        path_prefix: str = "",
    ) -> List[AudioFile]:
        """Рекурсивно обходит папку и возвращает аудиофайлы."""
        result: List[AudioFile] = []
        folders_to_scan: List[Tuple[str, str]] = [(root_folder_id, path_prefix)]

        while folders_to_scan:
            folder_id, current_path = folders_to_scan.pop(0)
            log.info("Сканирую папку: %s (id=%s)", current_path or "root", folder_id)

            page_token: Optional[str] = None
            while True:
                items, page_token = self._list_page(folder_id, page_token)
                for item in items:
                    mime = item.get("mimeType", "")
                    name = item.get("name", "")
                    item_id = item.get("id", "")

                    if mime == "application/vnd.google-apps.folder":
                        new_path = f"{current_path}/{name}" if current_path else name
                        folders_to_scan.append((item_id, new_path))
                        continue

                    ext = os.path.splitext(name)[1].lower()
                    if ext not in AUDIO_EXTENSIONS:
                        continue

                    # Для folder_name берём имя непосредственной родительской папки
                    folder_name = current_path.split("/")[-1] if current_path else "(root)"

                    audio = AudioFile(
                        file_id=item_id,
                        name=name,
                        mime_type=mime,
                        size=int(item.get("size") or 0),
                        modified_time=item.get("modifiedTime", ""),
                        folder_path=f"{current_path}/{name}" if current_path else name,
                        folder_name=folder_name,
                        web_view_link=item.get("webViewLink", f"https://drive.google.com/file/d/{item_id}/view"),
                    )
                    result.append(audio)

                if not page_token:
                    break

        log.info("Найдено аудиофайлов: %d", len(result))
        return result


# ---------------------------------------------------------------------------
# Google People API: поиск контакта
# ---------------------------------------------------------------------------

class ContactsResolver:
    def __init__(self, service: build):
        self.service = service

    def _extract_name(self, contact: Dict) -> Optional[str]:
        names = contact.get("names", [])
        if names:
            return names[0].get("displayName")
        return None

    def _extract_phone(self, contact: Dict) -> Optional[str]:
        phones = contact.get("phoneNumbers", [])
        if phones:
            return phones[0].get("value")
        return None

    def _extract_email(self, contact: Dict) -> Optional[str]:
        emails = contact.get("emailAddresses", [])
        if emails:
            return emails[0].get("value")
        return None

    def _digits(self, text: str) -> str:
        return re.sub(r"\D", "", text or "")

    def search_by_name(self, query: str) -> Optional[ContactInfo]:
        """Ищет контакт по имени среди личных контактов."""
        if not query or len(query) < 2:
            return None
        try:
            # people.otherContacts.search — глобальный поиск (может найти не только владельца)
            # people.connections.list — личные контакты
            resp = (
                self.service.people()
                .connections()
                .list(
                    resourceName="people/me",
                    pageSize=1000,
                    personFields="names,phoneNumbers,emailAddresses",
                )
                .execute()
            )
            connections = resp.get("connections", [])
            q_lower = query.lower()
            for person in connections:
                name = self._extract_name(person)
                if name and q_lower in name.lower():
                    return ContactInfo(
                        name=name,
                        phone=self._extract_phone(person),
                        email=self._extract_email(person),
                        source="google_contacts",
                    )
        except HttpError as exc:
            log.warning("Ошибка People API при поиске по имени '%s': %s", query, exc)
        return None

    def search_by_phone(self, phone_query: str) -> Optional[ContactInfo]:
        """Ищет контакт по цифрам номера телефона."""
        digits_query = self._digits(phone_query)
        if not digits_query or len(digits_query) < 5:
            return None
        try:
            resp = (
                self.service.people()
                .connections()
                .list(
                    resourceName="people/me",
                    pageSize=1000,
                    personFields="names,phoneNumbers,emailAddresses",
                )
                .execute()
            )
            for person in resp.get("connections", []):
                name = self._extract_name(person)
                for phone in person.get("phoneNumbers", []):
                    if digits_query in self._digits(phone.get("value", "")):
                        return ContactInfo(
                            name=name or phone_query,
                            phone=phone.get("value"),
                            email=self._extract_email(person),
                            source="google_contacts",
                        )
        except HttpError as exc:
            log.warning("Ошибка People API при поиске по телефону '%s': %s", phone_query, exc)
        return None

    def resolve(self, folder_name: str) -> ContactInfo:
        """Пытается найти контакт по имени папки или номеру."""
        # 1. Сначала поиск по имени
        contact = self.search_by_name(folder_name)
        if contact:
            log.info("Контакт найден по имени папки '%s': %s", folder_name, contact.name)
            return contact

        # 2. Если имя папки похоже на телефон — ищем по телефону
        if re.fullmatch(r"[\d\s\-+()]{5,}", folder_name):
            contact = self.search_by_phone(folder_name)
            if contact:
                log.info("Контакт найден по телефону '%s': %s", folder_name, contact.name)
                return contact

        # 3. Fallback: используем имя папки как есть
        log.info("Контакт не найден, используем имя папки: %s", folder_name)
        return ContactInfo(name=folder_name, source="folder_name")


# ---------------------------------------------------------------------------
# Notion API
# ---------------------------------------------------------------------------

class NotionClient:
    def __init__(self, token: str, database_id: str):
        self.token = token
        self.database_id = database_id
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }

    def _post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        url = f"{self.base_url}/{endpoint}"
        try:
            resp = requests.post(url, headers=self.headers, json=payload, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            log.error("Ошибка Notion API (%s): %s", endpoint, exc)
            return None

    def create_task(self, task: NotionTask) -> Optional[str]:
        """Создаёт страницу в базе данных Notion."""
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": task.title}}]
                },
                "Contact": {
                    "rich_text": [{"text": {"content": task.contact}}]
                },
                "Status": {
                    "select": {"name": task.status}
                },
                "Priority": {
                    "select": {"name": task.priority}
                },
                "Context": {
                    "rich_text": [{"text": {"content": task.context}}]
                },
                "File": {
                    "url": task.file_url
                },
            },
        }
        result = self._post("pages", payload)
        if result:
            page_id = result.get("id")
            log.info("Создана Notion-запись: %s (id=%s)", task.title, page_id)
            return page_id
        return None

    def database_has_property(self, property_name: str) -> bool:
        """Проверяет, существует ли свойство в базе данных."""
        url = f"{self.base_url}/databases/{self.database_id}"
        try:
            resp = requests.get(url, headers=self.headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return property_name in data.get("properties", {})
        except requests.exceptions.RequestException as exc:
            log.error("Ошибка Notion API при получении БД: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Кэш обработанных файлов
# ---------------------------------------------------------------------------

class ProcessedCache:
    def __init__(self, path: str = "processed_files.json"):
        self.path = path
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {"version": 1, "processed": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {"version": 1, "processed": {}}
                return data
        except Exception as exc:
            log.warning("Не удалось загрузить кэш %s: %s", self.path, exc)
            return {"version": 1, "processed": {}}

    def is_processed(self, file_id: str, modified_time: str) -> bool:
        key = file_hash(file_id, modified_time)
        return key in self._data.get("processed", {})

    def mark_processed(self, file_id: str, modified_time: str, notion_page_id: str) -> None:
        key = file_hash(file_id, modified_time)
        self._data.setdefault("processed", {})[key] = {
            "file_id": file_id,
            "modified_time": modified_time,
            "notion_page_id": notion_page_id,
            "processed_at": datetime.utcnow().isoformat(),
        }
        self._save()

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            log.error("Не удалось сохранить кэш %s: %s", self.path, exc)


# ---------------------------------------------------------------------------
# Основной пайплайн
# ---------------------------------------------------------------------------

class SyncPipeline:
    def __init__(
        self,
        google_creds: Credentials,
        notion_token: str,
        notion_database_id: str,
        cache_path: str = "processed_files.json",
        default_status: str = "Новый",
    ):
        self.drive_service = build("drive", "v3", credentials=google_creds, cache_discovery=False)
        self.people_service = build("people", "v1", credentials=google_creds, cache_discovery=False)
        self.drive_scanner = DriveScanner(self.drive_service)
        self.contacts_resolver = ContactsResolver(self.people_service)
        self.notion = NotionClient(notion_token, notion_database_id)
        self.cache = ProcessedCache(cache_path)
        self.default_status = default_status

    def _build_context(self, audio: AudioFile, contact: ContactInfo, matched_keywords: List[str]) -> str:
        lines = [
            f"Файл: {audio.name}",
            f"Папка: {audio.folder_name}",
            f"Путь: {audio.folder_path}",
            f"Размер: {audio.size} байт",
            f"Контакт: {contact.name}",
        ]
        if contact.phone:
            lines.append(f"Телефон: {contact.phone}")
        if contact.email:
            lines.append(f"Email: {contact.email}")
        if matched_keywords:
            lines.append(f"Ключевые слова: {', '.join(matched_keywords)}")
        return "\n".join(lines)

    def process_one(self, audio: AudioFile) -> bool:
        if self.cache.is_processed(audio.file_id, audio.modified_time):
            log.debug("Пропуск (уже обработан): %s", audio.folder_path)
            return False

        contact = self.contacts_resolver.resolve(audio.folder_name)
        priority, matched_keywords = priority_score(audio.name, audio.folder_name)
        context = self._build_context(audio, contact, matched_keywords)

        task = NotionTask(
            title=f"Анализ разговора: {audio.name}",
            contact=contact.name,
            status=self.default_status,
            priority=priority,
            context=context,
            file_url=audio.web_view_link,
        )

        page_id = self.notion.create_task(task)
        if page_id:
            self.cache.mark_processed(audio.file_id, audio.modified_time, page_id)
            return True
        return False

    def run(self, folder_id: Optional[str] = None) -> Dict[str, int]:
        folder_id = folder_id or DEFAULT_FOLDER_ID
        log.info("=== Запуск синхронизации Drive → Notion ===")

        audio_files = self.drive_scanner.scan_recursive(folder_id)
        created = 0
        skipped = 0
        failed = 0

        for audio in audio_files:
            if self.cache.is_processed(audio.file_id, audio.modified_time):
                skipped += 1
                continue
            try:
                ok = self.process_one(audio)
                created += int(ok)
                failed += int(not ok)
            except Exception as exc:
                log.exception("Неожиданная ошибка при обработке %s: %s", audio.folder_path, exc)
                failed += 1

        log.info("=== Итоги ===")
        log.info("Найдено аудио:      %d", len(audio_files))
        log.info("Пропущено (кэш):    %d", skipped)
        log.info("Создано в Notion:   %d", created)
        log.info("Ошибок:             %d", failed)

        return {
            "found": len(audio_files),
            "skipped": skipped,
            "created": created,
            "failed": failed,
        }


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def load_env_config() -> Dict[str, str]:
    """Загружает настройки из переменных окружения (предпочтительно) или .env."""
    config = {}
    # Попытка загрузить .env если есть
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))

    config["NOTION_TOKEN"] = os.environ.get("NOTION_TOKEN", "")
    config["NOTION_DATABASE_ID"] = os.environ.get("NOTION_DATABASE_ID", "")
    config["DRIVE_FOLDER_ID"] = os.environ.get("DRIVE_FOLDER_ID", DEFAULT_FOLDER_ID)
    config["CREDENTIALS_PATH"] = os.environ.get("CREDENTIALS_PATH", "credentials.json")
    config["TOKEN_PATH"] = os.environ.get("TOKEN_PATH", "token.json")
    config["CACHE_PATH"] = os.environ.get("CACHE_PATH", "processed_files.json")
    return config


def main() -> int:
    config = load_env_config()

    missing = []
    if not config["NOTION_TOKEN"]:
        missing.append("NOTION_TOKEN")
    if not config["NOTION_DATABASE_ID"]:
        missing.append("NOTION_DATABASE_ID")
    if missing:
        log.error("Не заданы переменные окружения: %s", ", ".join(missing))
        log.error("Создайте .env файл или экспортируйте переменные перед запуском.")
        return 1

    try:
        google_creds = get_google_credentials(
            config["CREDENTIALS_PATH"], config["TOKEN_PATH"]
        )
    except Exception as exc:
        log.error("Ошибка Google-авторизации: %s", exc)
        return 1

    pipeline = SyncPipeline(
        google_creds=google_creds,
        notion_token=config["NOTION_TOKEN"],
        notion_database_id=config["NOTION_DATABASE_ID"],
        cache_path=config["CACHE_PATH"],
    )

    pipeline.run(config["DRIVE_FOLDER_ID"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
