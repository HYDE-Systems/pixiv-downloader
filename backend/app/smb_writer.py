"""SMB共有への直接ストリーム書込み。ローカルディスクには一切残さない。"""
from __future__ import annotations

import threading
from contextlib import contextmanager

import smbclient

from . import config

_session_lock = threading.Lock()
_current_signature: tuple | None = None


def _unc(server: str, share: str, *parts: str) -> str:
    # フォワードスラッシュをSMBの区切り(バックスラッシュ)へ正規化する。
    cleaned = []
    for part in parts:
        if not part:
            continue
        norm = part.replace("/", "\\").strip("\\")
        if norm:
            cleaned.append(norm)
    suffix = "\\".join(cleaned)
    base = rf"\\{server}\{share}"
    return f"{base}\\{suffix}" if suffix else base


def configure_session(smb: dict) -> None:
    """SMB設定が変わったらセッションを張り直す。"""
    global _current_signature
    signature = (smb["host"], smb["port"], smb["username"], smb["password"], smb["domain"])
    with _session_lock:
        if signature == _current_signature:
            return
        username = smb["username"]
        if smb.get("domain"):
            username = f"{smb['domain']}\\{username}"
        smbclient.register_session(
            smb["host"],
            username=username,
            password=smb["password"],
            port=int(smb.get("port") or config.DEFAULT_SMB_PORT),
        )
        _current_signature = signature


def test_connection(smb: dict) -> None:
    """接続確認。base_path の存在を確認(無ければ作成を試みる)。"""
    configure_session(smb)
    root = _unc(smb["host"], smb["share"], smb.get("base_path", ""))
    if not smbclient.path.exists(root):
        smbclient.makedirs(root, exist_ok=True)


def exists(smb: dict, relative_path: str) -> bool:
    configure_session(smb)
    return smbclient.path.exists(_unc(smb["host"], smb["share"], smb.get("base_path", ""), relative_path))


@contextmanager
def open_write(smb: dict, relative_path: str):
    """SMB上のファイルを書込みモードで開く。親ディレクトリは自動作成。"""
    configure_session(smb)
    full = _unc(smb["host"], smb["share"], smb.get("base_path", ""), relative_path)
    parent = full.rsplit("\\", 1)[0]
    smbclient.makedirs(parent, exist_ok=True)
    handle = smbclient.open_file(full, mode="wb")
    try:
        yield handle
    finally:
        handle.close()


def write_text(smb: dict, relative_path: str, text: str) -> None:
    with open_write(smb, relative_path) as handle:
        handle.write(text.encode("utf-8"))
