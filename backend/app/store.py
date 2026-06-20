"""設定の暗号化永続化。作品データは扱わず、設定とキューのスナップショットのみを保持する。

暗号化Dockerボリューム上に Fernet で暗号化して保存する。鍵は
MASTER_PASSWORD があればそこから導出し、無ければ自動生成してボリューム内に保管する。
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import threading
from copy import deepcopy
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from . import config


def _derive_key_from_password(password: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=config.KDF_SALT,
        iterations=config.KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _load_or_create_key() -> bytes:
    password = os.environ.get(config.MASTER_PASSWORD_ENV, "").strip()
    if password:
        return _derive_key_from_password(password)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if config.SECRET_KEY_FILE.exists():
        return config.SECRET_KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    config.SECRET_KEY_FILE.write_bytes(key)
    config.SECRET_KEY_FILE.chmod(0o600)
    return key


class SecureStore:
    """設定とキュースナップショットを暗号化して読み書きする。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._fernet = Fernet(_load_or_create_key())
        self._settings = self._read_settings()

    # --- 暗号化I/O ---------------------------------------------------------
    def _read(self, path) -> Any | None:
        if not path.exists():
            return None
        try:
            return json.loads(self._fernet.decrypt(path.read_bytes()).decode("utf-8"))
        except (InvalidToken, ValueError, json.JSONDecodeError):
            return None

    def _write(self, path, payload: Any) -> None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        token = self._fernet.encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(token)
        tmp.replace(path)

    # --- 設定 --------------------------------------------------------------
    def _read_settings(self) -> dict:
        stored = self._read(config.CONFIG_FILE)
        merged = deepcopy(config.DEFAULT_SETTINGS)
        if isinstance(stored, dict):
            _deep_merge(merged, stored)
        if not merged.get("api_token"):
            merged["api_token"] = secrets.token_urlsafe(24)
            self._write(config.CONFIG_FILE, merged)
        return merged

    def get_settings(self) -> dict:
        with self._lock:
            return deepcopy(self._settings)

    def update_settings(self, patch: dict) -> dict:
        with self._lock:
            _deep_merge(self._settings, patch)
            self._write(config.CONFIG_FILE, self._settings)
            return deepcopy(self._settings)

    def set_refresh_token(self, refresh_token: str, user: str = "") -> None:
        self.update_settings({"refresh_token": refresh_token, "pixiv_user": user})

    def rotate_api_token(self) -> str:
        token = secrets.token_urlsafe(24)
        self.update_settings({"api_token": token})
        return token

    # --- キュースナップショット -------------------------------------------
    def save_queue_snapshot(self, items: list[dict]) -> None:
        with self._lock:
            self._write(config.QUEUE_FILE, items)

    def load_queue_snapshot(self) -> list[dict]:
        snapshot = self._read(config.QUEUE_FILE)
        return snapshot if isinstance(snapshot, list) else []


def _deep_merge(base: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


store = SecureStore()
