"""Small Fernet wrapper for Telegram queues stored on local disk."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class QueueCipher:
    """Encrypt queue payloads with a root-only key outside the SQLite file."""

    def __init__(self, key_path: str | Path) -> None:
        self.key_path = Path(key_path)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        env_key = os.environ.get("TELEGRAM_QUEUE_ENCRYPTION_KEY", "").strip()
        if env_key:
            key = env_key.encode("ascii")
        elif self.key_path.exists():
            key = self.key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            self._atomic_key(key)
        self._fernet = Fernet(key)

    def _atomic_key(self, key: bytes) -> None:
        fd, name = tempfile.mkstemp(
            prefix=self.key_path.name + ".", dir=str(self.key_path.parent)
        )
        tmp = Path(name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(key + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.key_path)
        finally:
            tmp.unlink(missing_ok=True)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str, *, encrypted: bool = True) -> str:
        if not encrypted:
            return value
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError("queue payload cannot be decrypted") from exc
