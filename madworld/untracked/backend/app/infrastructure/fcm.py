"""Firebase Cloud Messaging HTTP v1 sender.

Credentials stay outside Git. The server must provide GOOGLE_APPLICATION_CREDENTIALS
and MADWORLD_FCM_PROJECT_ID. No device token or credential is logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from time import sleep

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
RETRYABLE = frozenset({429, 500, 502, 503, 504})


class FCMConfigurationError(RuntimeError):
    pass


class FCMDeliveryError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, invalid_token: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.invalid_token = invalid_token


@dataclass(frozen=True, slots=True)
class PushMessage:
    title: str
    body: str
    data: dict[str, str]


class FCMClient:
    def __init__(self, project_id: str | None = None, credentials_path: str | None = None, timeout: float = 10.0) -> None:
        self.project_id = project_id or os.getenv("MADWORLD_FCM_PROJECT_ID")
        self.credentials_path = credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.timeout = timeout
        self._credentials = None

    def _load_credentials(self):
        if not self.project_id or not self.credentials_path:
            raise FCMConfigurationError("MADWORLD_FCM_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS are required")
        if self._credentials is None:
            self._credentials = service_account.Credentials.from_service_account_file(self.credentials_path, scopes=[FCM_SCOPE])
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        return self._credentials

    def send(self, token: str, message: PushMessage, *, max_attempts: int = 3) -> str:
        if not token.strip():
            raise ValueError("FCM token must not be empty")
        credentials = self._load_credentials()
        url = f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send"
        payload = {"message": {"token": token, "notification": {"title": message.title, "body": message.body}, "data": message.data}}
        last_status: int | None = None
        for attempt in range(max_attempts):
            try:
                if not credentials.valid:
                    credentials.refresh(Request())
                response = httpx.post(url, headers={"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"}, json=payload, timeout=self.timeout)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt + 1 == max_attempts:
                    raise FCMDeliveryError("FCM transport failed after retries") from exc
                sleep(2**attempt)
                continue
            last_status = response.status_code
            if response.is_success:
                name = response.json().get("name")
                if not name:
                    raise FCMDeliveryError("FCM returned success without message name", status_code=response.status_code)
                return str(name)
            if response.status_code in RETRYABLE and attempt + 1 < max_attempts:
                sleep(2**attempt)
                continue
            body = response.text.lower()
            invalid = response.status_code == 404 or "unregistered" in body or "registration-token-not-registered" in body
            raise FCMDeliveryError(f"FCM delivery failed with HTTP {response.status_code}", status_code=response.status_code, invalid_token=invalid)
        raise FCMDeliveryError("FCM delivery exhausted retries", status_code=last_status)
