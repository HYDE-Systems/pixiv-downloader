"""pixivpy(AppPixivAPI)のラッパー。認証・検索・メタ取得・画像URL列挙を担う。"""
from __future__ import annotations

import threading
import time

from pixivpy3 import AppPixivAPI

from . import config

# refresh_token によるアクセストークンの有効期間は約1時間。余裕をもって再認証する。
_AUTH_TTL_SECONDS = 2700


class PixivClient:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._api = AppPixivAPI()
        self._authed_at = 0.0
        self._refresh_token = ""

    def configure(self, refresh_token: str) -> None:
        with self._lock:
            if refresh_token != self._refresh_token:
                self._refresh_token = refresh_token
                self._authed_at = 0.0

    def is_configured(self) -> bool:
        return bool(self._refresh_token)

    def _ensure_auth(self) -> AppPixivAPI:
        if not self._refresh_token:
            raise RuntimeError("pixiv にログインしていません。設定からログインしてください。")
        with self._lock:
            if time.time() - self._authed_at > _AUTH_TTL_SECONDS:
                self._api.auth(refresh_token=self._refresh_token)
                self._authed_at = time.time()
            return self._api

    def verify(self, refresh_token: str) -> str:
        """refresh_token の有効性を検証し、アカウント名を返す。"""
        api = AppPixivAPI()
        result = api.auth(refresh_token=refresh_token)
        return getattr(getattr(result, "user", None), "name", "") or ""

    # --- 取得系 ------------------------------------------------------------
    def illust_detail(self, illust_id: int) -> dict:
        api = self._ensure_auth()
        result = api.illust_detail(illust_id)
        illust = result.get("illust")
        if not illust:
            raise RuntimeError(f"作品 {illust_id} を取得できませんでした: {result.get('error')}")
        return illust

    def user_illust_ids(self, user_id: int) -> list[int]:
        """指定ユーザーの全イラストIDを取得する。"""
        api = self._ensure_auth()
        ids: list[int] = []
        result = api.user_illusts(user_id)
        while True:
            for illust in result.get("illusts", []):
                ids.append(illust["id"])
            next_qs = api.parse_qs(result.get("next_url"))
            if not next_qs:
                break
            result = api.user_illusts(user_id, **next_qs)
        return ids

    def search(self, word: str, page: int = 1) -> dict:
        api = self._ensure_auth()
        offset = (max(page, 1) - 1) * 30
        result = api.search_illust(word, offset=offset) if offset else api.search_illust(word)
        return result

    def ugoira_metadata(self, illust_id: int) -> dict:
        api = self._ensure_auth()
        return api.ugoira_metadata(illust_id).get("ugoira_metadata", {})

    def user_illusts_first(self, user_id: int) -> list[dict]:
        """指定ユーザーの新着イラスト(先頭ページ)を作品オブジェクトで返す。"""
        api = self._ensure_auth()
        return api.user_illusts(user_id).get("illusts", [])

    def following_illusts(self) -> list[dict]:
        """フォロー中ユーザーの新着作品を返す。"""
        api = self._ensure_auth()
        return api.illust_follow(restrict="all").get("illusts", [])


def extract_image_urls(illust: dict) -> list[str]:
    """作品から原寸画像URLを列挙する(複数ページ対応)。"""
    meta_pages = illust.get("meta_pages") or []
    if meta_pages:
        return [p["image_urls"]["original"] for p in meta_pages]
    single = illust.get("meta_single_page") or {}
    if single.get("original_image_url"):
        return [single["original_image_url"]]
    # フォールバック: large
    return [illust["image_urls"]["large"]]


def extract_preview_urls(illust: dict) -> list[str]:
    """詳細表示用に large サイズのプレビューURLを列挙する(複数ページ対応)。"""
    meta_pages = illust.get("meta_pages") or []
    if meta_pages:
        return [p["image_urls"].get("large") or p["image_urls"]["medium"] for p in meta_pages]
    return [illust["image_urls"].get("large") or illust["image_urls"]["medium"]]


client = PixivClient()
