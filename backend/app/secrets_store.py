"""API anahtarlarını şifreli saklar.

Anahtarlar `data/api_keys.enc` dosyasında, panel şifresinden türetilen bir anahtarla
(scrypt + Fernet/AES) şifrelenir. Tarayıcıya asla geri gönderilmez; arayüzde yalnızca
anahtarın maskelenmiş hali görünür. Bu sürümde yalnızca TESTNET anahtarı kabul edilir.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class KeyStore:
    def __init__(self, directory: str, password: str):
        self.path = Path(directory) / "api_keys.enc"
        self.password = password

    def _fernet(self, salt: bytes) -> Fernet:
        raw = hashlib.scrypt(self.password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return Fernet(base64.urlsafe_b64encode(raw))

    def save(self, environment: str, api_key: str, api_secret: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(16)
        payload = json.dumps({"environment": environment, "api_key": api_key,
                              "api_secret": api_secret, "saved_at": time.time()}).encode()
        self.path.write_bytes(salt + self._fernet(salt).encrypt(payload))
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        blob = self.path.read_bytes()
        try:
            return json.loads(self._fernet(blob[:16]).decrypt(blob[16:]))
        except (InvalidToken, ValueError):
            return None  # şifre değişmiş olabilir

    def exists(self) -> bool:
        return self.path.exists()

    def delete(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def public_info(self) -> dict:
        if not self.exists():
            return {"configured": False}
        d = self.load()
        if d is None:
            return {"configured": True, "readable": False,
                    "note": "Kayıtlı anahtar okunamadı (panel şifresi değişmiş olabilir). Silip yeniden girin."}
        k = d["api_key"]
        return {"configured": True, "readable": True, "environment": d["environment"],
                "api_key_masked": k[:4] + "…" + k[-4:], "saved_at": d["saved_at"]}
