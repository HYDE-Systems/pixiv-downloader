"""API入出力のスキーマ。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SmbSettings(BaseModel):
    host: str = ""
    port: int = 445
    share: str = ""
    username: str = ""
    password: str = ""
    domain: str = ""
    base_path: str = "pixiv"


class DownloadSettings(BaseModel):
    filename_template: str
    save_metadata: bool = True
    download_ugoira: bool = True
    concurrency: int = 2
    skip_existing: bool = True
    zip_per_work: bool = False
    zip_filename_template: str = ""


class SettingsPatch(BaseModel):
    """部分更新。送られたフィールドのみ反映する。"""

    smb: dict | None = None
    download: dict | None = None


class AuthBeginResponse(BaseModel):
    login_url: str
    state: str


class AuthCompleteRequest(BaseModel):
    state: str
    code: str


class AuthTokenRequest(BaseModel):
    """refresh_token を直接貼り付けてログインする場合。"""

    refresh_token: str


class LoginRequest(BaseModel):
    """ダッシュボードのログイン（APIトークンを資格情報として使う）。"""

    token: str


class EnqueueItem(BaseModel):
    """拡張機能やダッシュボードから投入する1件。illust_id か user_id のどちらか。"""

    illust_id: int | None = None
    user_id: int | None = None
    source_url: str | None = None
    title: str | None = None


class EnqueueRequest(BaseModel):
    items: list[EnqueueItem] = Field(default_factory=list)


class SearchRequest(BaseModel):
    word: str
    page: int = 1
