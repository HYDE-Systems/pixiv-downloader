"""pixiv の refresh_token をダッシュボード内で取得するための PKCE フロー。

1. begin(): code_verifier / code_challenge を生成しログインURLを返す。
2. ユーザーがブラウザでログインし、リダイレクトURL内の `code` を取得して貼り付ける。
3. complete(): code を refresh_token に交換する。
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time

import requests

from . import config

# state -> (code_verifier, 作成時刻)
_pending: dict[str, tuple[str, float]] = {}
_PENDING_TTL_SECONDS = 1800


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _purge_expired() -> None:
    now = time.time()
    for state in [s for s, (_, ts) in _pending.items() if now - ts > _PENDING_TTL_SECONDS]:
        _pending.pop(state, None)


def begin() -> dict:
    _purge_expired()
    code_verifier = secrets.token_urlsafe(32)
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
    state = secrets.token_urlsafe(8)
    _pending[state] = (code_verifier, time.time())
    login_url = (
        f"{config.PIXIV_LOGIN_URL}"
        f"?code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&client=pixiv-android"
    )
    return {"login_url": login_url, "state": state}


def complete(state: str, code: str) -> dict:
    _purge_expired()
    # 失敗時は検証情報を破棄せず、同じログインURLで取り直した新しいcodeで再試行できるようにする。
    entry = _pending.get(state)
    if entry is None:
        raise ValueError("ログインセッションの有効期限が切れています。「ログインURLを開く」からやり直してください。")
    code_verifier, _ = entry

    # URL全体を貼り付けられても code を抽出する
    matched = re.search(r"code=([^&\s]+)", code)
    if matched:
        code = matched.group(1)
    code = code.strip()
    if not code:
        raise ValueError("認証コードが空です。リダイレクトURLまたはcodeを貼り付けてください。")

    response = requests.post(
        config.PIXIV_AUTH_TOKEN_URL,
        data={
            "client_id": config.PIXIV_CLIENT_ID,
            "client_secret": config.PIXIV_CLIENT_SECRET,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "include_policy": "true",
            "redirect_uri": config.PIXIV_REDIRECT_URI,
        },
        headers={"User-Agent": config.OAUTH_USER_AGENT},
        timeout=config.HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise ValueError(_friendly_error(response))

    payload = response.json()
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise ValueError("レスポンスに refresh_token が含まれていませんでした。")

    _pending.pop(state, None)  # 成功時のみ消費
    user = (payload.get("user") or {}).get("name", "")
    return {"refresh_token": refresh_token, "user": user}


def _friendly_error(response) -> str:
    """pixivのエラーレスポンスを分かりやすい日本語に変換する。"""
    body = response.text[:300]
    if "invalid_request" in body or "918" in body or response.status_code == 400:
        return (
            "認証コードが無効です。pixivのcodeはワンタイムかつ数十秒で失効します。"
            "『ログインURLを開く』のリンクをもう一度開いてログインし、表示されたURLを"
            "すぐに貼り付けて再試行してください（別のログインURLを新規生成すると一致しなくなります）。"
        )
    return f"トークン交換に失敗しました ({response.status_code}): {body}"
