"""アプリ全体で共有する定数。マジックナンバーはすべてここに集約する。"""
from __future__ import annotations

import os
from pathlib import Path

# --- 永続化（暗号化Dockerボリューム）---------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SECRET_KEY_FILE = DATA_DIR / "secret.key"
CONFIG_FILE = DATA_DIR / "config.enc"
QUEUE_FILE = DATA_DIR / "queue.enc"
# 設定値の暗号鍵を環境変数のパスフレーズから導出する場合に使用（任意）。
MASTER_PASSWORD_ENV = "MASTER_PASSWORD"
KDF_SALT = b"pixiv-download-studio-v1"
KDF_ITERATIONS = 390_000

# --- pixiv OAuth (PKCE) -----------------------------------------------------
PIXIV_CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
PIXIV_CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
PIXIV_AUTH_TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"
PIXIV_LOGIN_URL = "https://app-api.pixiv.net/web/v1/login"
PIXIV_REDIRECT_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
OAUTH_USER_AGENT = "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)"

# --- 画像取得 ----------------------------------------------------------------
IMAGE_REFERER = "https://www.pixiv.net/"
IMAGE_USER_AGENT = "PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)"
DOWNLOAD_CHUNK_SIZE = 1 << 16  # 64KiB ずつストリームしてSMBへ流す
HTTP_TIMEOUT_SECONDS = 60

# --- ダウンロードワーカー ----------------------------------------------------
DEFAULT_CONCURRENCY = 2
MAX_CONCURRENCY = 6
WORKER_IDLE_SLEEP_SECONDS = 0.5
SSE_PUSH_INTERVAL_SECONDS = 1.0

# --- SMB --------------------------------------------------------------------
DEFAULT_SMB_PORT = 445

# --- ファイル名テンプレート --------------------------------------------------
# 使用可能なトークン: {artist} {artist_id} {title} {illust_id} {page} {ext} {date}
DEFAULT_FILENAME_TEMPLATE = "{artist} ({artist_id})/{illust_id}_{title}_p{page}.{ext}"

# --- 既定の設定値 ------------------------------------------------------------
DEFAULT_SETTINGS = {
    "refresh_token": "",
    "pixiv_user": "",  # 認証後に表示する自分のアカウント名
    "smb": {
        "host": "",
        "port": DEFAULT_SMB_PORT,
        "share": "",
        "username": "",
        "password": "",
        "domain": "",
        "base_path": "pixiv",
    },
    "download": {
        "filename_template": DEFAULT_FILENAME_TEMPLATE,
        "save_metadata": True,
        "download_ugoira": True,
        "concurrency": DEFAULT_CONCURRENCY,
        "skip_existing": True,
        "zip_per_work": False,  # 作品ごとに全ページ+メタを1つのzipにまとめる
    },
    # 拡張機能からの投入を認証するトークン（ダッシュボードで生成）
    "api_token": "",
}
