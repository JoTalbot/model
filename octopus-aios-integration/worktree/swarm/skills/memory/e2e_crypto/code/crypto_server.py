#!/usr/bin/env python3
"""
Octopus E2E Crypto Server — серверная часть для расшифровки файлов.
Файлы передаются зашифрованными, расшифровываются на лету.
"""
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

class OctopusCryptoServer:
    """Серверное E2E шифрование."""

    SALT_LENGTH = 16
    IV_LENGTH = 12
    KEY_LENGTH = 32  # 256 bits

    def __init__(self):
        if not HAS_CRYPTOGRAPHY:
            # Fallback на PyCryptodome
            try:
                from Crypto.Cipher import AES
                self.AES = AES
                self._use_pycryptodome = True
            except ImportError:
                print("WARNING: Установите cryptography или pycryptodome для E2E шифрования")
                self._use_pycryptodome = False
        else:
            self._use_pycryptodome = False

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """PBKDF2 key derivation."""
        return hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            100000,
            dklen=self.KEY_LENGTH
        )

    def encrypt(self, data: bytes, password: str) -> bytes:
        """Шифрование данных (для сервера не используется, клиент шифрует)."""
        raise NotImplementedError("Сервер не шифрует — только клиент может шифровать")

    def decrypt(self, encrypted_data: bytes, password: str) -> bytes:
        """Расшифровка данных."""
        if not self._use_pycryptodome and not HAS_CRYPTOGRAPHY:
            raise RuntimeError("Требуется cryptography или pycryptodome")

        # Разбор: salt (16) + iv (12) + ciphertext
        salt = encrypted_data[:self.SALT_LENGTH]
        iv = encrypted_data[self.SALT_LENGTH:self.SALT_LENGTH + self.IV_LENGTH]
        ciphertext = encrypted_data[self.SALT_LENGTH + self.IV_LENGTH:]

        key = self._derive_key(password, salt)

        if HAS_CRYPTOGRAPHY:
            aesgcm = AESGCM(key)
            return aesgcm.decrypt(iv, ciphertext, None)
        else:
            cipher = self.AES.new(key, self.AES.MODE_GCM, nonce=iv)
            return cipher.decrypt(ciphertext)

    def decrypt_file(self, filepath: str, password: str) -> bytes:
        """Расшифровка файла."""
        with open(filepath, 'rb') as f:
            encrypted = f.read()
        return self.decrypt(encrypted, password)

    def encrypt_to_file(self, data: bytes, password: str, filepath: str):
        """Шифрование и сохранение в файл."""
        import hmac
        import struct

        salt = os.urandom(self.SALT_LENGTH)
        iv = os.urandom(self.IV_LENGTH)
        key = self._derive_key(password, salt)

        if HAS_CRYPTOGRAPHY:
            aesgcm = AESGCM(key)
            ciphertext = aesgcm.encrypt(iv, data, None)
        else:
            from Crypto.Cipher import AES
            cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
            ciphertext, tag = cipher.encrypt_and_digest(data)
            ciphertext = ciphertext + tag

        with open(filepath, 'wb') as f:
            f.write(salt + iv + ciphertext)

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Octopus E2E Crypto Server")
    parser.add_argument("--decrypt", type=str, help="Файл для расшифровки")
    parser.add_argument("--encrypt", type=str, help="Данные для шифрования (hex)")
    parser.add_argument("--password", type=str, required=True, help="Пароль")
    parser.add_argument("--output", type=str, help="Выходной файл")
    args = parser.parse_args()

    crypto = OctopusCryptoServer()

    if args.decrypt:
        try:
            result = crypto.decrypt_file(args.decrypt, args.password)
            if args.output:
                Path(args.output).write_bytes(result)
                print(f"✅ Расшифровано в {args.output}")
            else:
                print(result.decode('utf-8'))
        except Exception as e:
            print(f"❌ Ошибка расшифровки: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.encrypt:
        import binascii
        data = binascii.unhexlify(args.encrypt)
        crypto.encrypt_to_file(data, args.password, args.output)
        print(f"✅ Зашифровано в {args.output}")

    else:
        print("Использование:")
        print("  crypto_server.py --decrypt FILE --password PASS [--output OUT]")
        print("  crypto_server.py --encrypt HEX --password PASS --output FILE")

if __name__ == "__main__":
    main()
