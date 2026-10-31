"""Panel girişi, oturum belirteci ve API anahtarı şifreleme kasası."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field

import jwt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MIN_PASSWORD_LEN = 10


class PasswordGate:
    """Tek kullanıcılı panel şifresi. Şifre bellekte yalnızca scrypt özeti olarak tutulur."""

    def __init__(self, password: str):
        if len(password) < MIN_PASSWORD_LEN:
            raise ValueError(
                f"ADMIN_PASSWORD en az {MIN_PASSWORD_LEN} karakter olmalıdır. "
                ".env dosyanızı kontrol edin."
            )
        self._salt = os.urandom(16)
        self._digest = self._hash(password)
        self._fails: dict[str, tuple[int, float]] = {}

    def _hash(self, password: str) -> bytes:
        return hashlib.scrypt(password.encode(), salt=self._salt, n=2**14, r=8, p=1, dklen=32)

    def verify(self, password: str) -> bool:
        return hmac.compare_digest(self._hash(password), self._digest)

    # --- kaba kuvvet koruması: 5 hatalı denemeden sonra 5 dk kilit ---
    def locked_for(self, client: str) -> int:
        fails, until = self._fails.get(client, (0, 0.0))
        remaining = until - time.time()
        return int(remaining) + 1 if remaining > 0 else 0

    def register_failure(self, client: str) -> None:
        fails, until = self._fails.get(client, (0, 0.0))
        fails += 1
        if fails >= 5:
            self._fails[client] = (0, time.time() + 300)
        else:
            self._fails[client] = (fails, until)

    def register_success(self, client: str) -> None:
        self._fails.pop(client, None)


def create_token(secret: str, hours: int) -> str:
    now = int(time.time())
    return jwt.encode({"sub": "admin", "iat": now, "exp": now + hours * 3600}, secret, algorithm="HS256")


def verify_token(secret: str, token: str) -> bool:
    try:
        jwt.decode(token, secret, algorithms=["HS256"])
        return True
    except jwt.PyJWTError:
        return False


class Vault:
    """API anahtarlarını diskte şifreli saklamak için (Fernet / AES-128-CBC + HMAC)."""

    def __init__(self, secret: str):
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"ai-kripto-trader-vault").derive(
            secret.encode()
        )
        self._f = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, plain: str) -> str:
        return self._f.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._f.decrypt(token.encode()).decode()
        except InvalidToken as e:
            raise ValueError("Kayıtlı anahtar çözülemedi (SECRET_KEY değişmiş olabilir).") from e


def mask(value: str) -> str:
    return f"{value[:4]}…{value[-4:]}" if len(value) > 10 else "****"


@dataclass
class AuthState:
    gate: PasswordGate
    secret: str
    hours: int
    cookie_secure: bool = False
    vault: Vault = field(init=False)

    def __post_init__(self):
        self.vault = Vault(self.secret)
