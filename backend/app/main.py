"""FastAPI アプリ本体。設定・認証・キュー・検索・画像プロキシのAPIを提供する。"""
from __future__ import annotations

import asyncio
import json

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import auth_flow, config, rss, smb_writer
from .downloader import download_queue
from .models import (
    AuthCompleteRequest,
    AuthTokenRequest,
    LoginRequest,
    SettingsPatch,
)
from .pixiv_client import client, extract_preview_urls
from .store import store

app = FastAPI(title="Pixiv Download Studio API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_COOKIE = "pds_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365
# 認証ゲートを通さない公開パス
_OPEN_PATHS = {"/api/status", "/api/login", "/api/session/logout"}
# RSSと画像プロキシは独自にトークン検証（外部リーダー対応）するためゲート対象外
_OPEN_PREFIXES = ("/api/rss/", "/api/proxy/")


@app.on_event("startup")
def _startup() -> None:
    settings = store.get_settings()
    if settings.get("refresh_token"):
        client.configure(settings["refresh_token"])
    download_queue.start()
    print(f"[Pixiv Download Studio] ダッシュボードログイン用トークン: {settings.get('api_token', '')}",
          flush=True)


def _is_authorized(request: Request) -> bool:
    expected = store.get_settings().get("api_token")
    if not expected:
        return False
    supplied = request.cookies.get(SESSION_COOKIE, "") or request.headers.get("x-api-token", "")
    return supplied == expected


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Cookie または X-API-Token ヘッダで /api/* を保護する。"""
    path = request.url.path
    needs_auth = (
        request.method != "OPTIONS"
        and path.startswith("/api/")
        and path not in _OPEN_PATHS
        and not path.startswith(_OPEN_PREFIXES)
    )
    if needs_auth and not _is_authorized(request):
        return JSONResponse({"detail": "認証が必要です。ダッシュボードにログインしてください。"}, status_code=401)
    return await call_next(request)


def _redact(settings: dict) -> dict:
    """秘匿値はダッシュボードへ「設定済み」フラグとして返す。"""
    safe = json.loads(json.dumps(settings))
    safe["refresh_token_set"] = bool(safe.pop("refresh_token", ""))
    if safe.get("smb", {}).get("password"):
        safe["smb"]["password"] = "********"
    return safe


# --- ダッシュボードのログイン（Cookie） ------------------------------------
@app.post("/api/login")
def login(req: LoginRequest, response: Response) -> dict:
    expected = store.get_settings().get("api_token", "")
    if not expected or req.token.strip() != expected:
        raise HTTPException(status_code=401, detail="トークンが違います。")
    response.set_cookie(SESSION_COOKIE, expected, httponly=True, samesite="lax",
                        max_age=COOKIE_MAX_AGE, path="/")
    return {"ok": True}


@app.post("/api/session/logout")
def session_logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


# --- 状態 ------------------------------------------------------------------
@app.get("/api/status")
def status(request: Request) -> dict:
    if not _is_authorized(request):
        return {"dashboard_authenticated": False}
    settings = store.get_settings()
    smb = settings["smb"]
    return {
        "dashboard_authenticated": True,
        "authenticated": client.is_configured(),
        "pixiv_user": settings.get("pixiv_user", ""),
        "smb_configured": bool(smb.get("host") and smb.get("share")),
        "api_token": settings.get("api_token", ""),
    }


# --- 認証 ------------------------------------------------------------------
@app.post("/api/auth/begin")
def auth_begin() -> dict:
    return auth_flow.begin()


@app.post("/api/auth/complete")
def auth_complete(req: AuthCompleteRequest) -> dict:
    try:
        result = auth_flow.complete(req.state, req.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store.set_refresh_token(result["refresh_token"], result.get("user", ""))
    client.configure(result["refresh_token"])
    return {"ok": True, "pixiv_user": result.get("user", "")}


@app.post("/api/auth/token")
def auth_token(req: AuthTokenRequest) -> dict:
    try:
        user = client.verify(req.refresh_token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"refresh_token が無効です: {exc}")
    store.set_refresh_token(req.refresh_token, user)
    client.configure(req.refresh_token)
    return {"ok": True, "pixiv_user": user}


@app.post("/api/auth/logout")
def auth_logout() -> dict:
    store.set_refresh_token("", "")
    client.configure("")
    return {"ok": True}


# --- 設定 ------------------------------------------------------------------
@app.get("/api/settings")
def get_settings() -> dict:
    return _redact(store.get_settings())


@app.put("/api/settings")
def update_settings(patch: SettingsPatch) -> dict:
    payload: dict = {}
    if patch.smb is not None:
        # マスク値はそのまま送られた場合に上書きしない
        smb = dict(patch.smb)
        if smb.get("password") == "********":
            smb.pop("password", None)
        payload["smb"] = smb
    if patch.download is not None:
        payload["download"] = patch.download
    updated = store.update_settings(payload)
    return _redact(updated)


@app.post("/api/settings/smb-test")
def smb_test() -> dict:
    smb = store.get_settings()["smb"]
    if not (smb.get("host") and smb.get("share")):
        raise HTTPException(status_code=400, detail="SMBのホストと共有名を設定してください。")
    try:
        smb_writer.test_connection(smb)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"接続に失敗しました: {exc}")
    return {"ok": True}


@app.post("/api/settings/rotate-token")
def rotate_token() -> dict:
    return {"api_token": store.rotate_api_token()}


# --- 検索 ------------------------------------------------------------------
@app.get("/api/search")
def search(word: str = Query(...), page: int = Query(1, ge=1)) -> dict:
    if not client.is_configured():
        raise HTTPException(status_code=401, detail="pixivにログインしていません。")
    try:
        result = client.search(word, page)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))
    illusts = [
        {
            "illust_id": it["id"],
            "title": it["title"],
            "artist": it["user"]["name"],
            "artist_id": it["user"]["id"],
            "thumb_url": it["image_urls"].get("square_medium", ""),
            "page_count": it.get("page_count", 1),
            "type": it.get("type"),
        }
        for it in result.get("illusts", [])
    ]
    return {"illusts": illusts, "has_next": bool(result.get("next_url"))}


@app.get("/api/illust/{illust_id}")
def illust_detail(illust_id: int) -> dict:
    if not client.is_configured():
        raise HTTPException(status_code=401, detail="pixivにログインしていません。")
    try:
        illust = client.illust_detail(illust_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "illust_id": illust["id"],
        "title": illust["title"],
        "artist": illust["user"]["name"],
        "artist_id": illust["user"]["id"],
        "type": illust.get("type"),
        "page_count": illust.get("page_count", 1),
        "tags": [t["name"] for t in illust.get("tags", [])],
        "caption": illust.get("caption", ""),
        "create_date": illust.get("create_date", ""),
        "total_view": illust.get("total_view", 0),
        "total_bookmarks": illust.get("total_bookmarks", 0),
        "previews": extract_preview_urls(illust),
    }


# --- キュー ----------------------------------------------------------------
def _coerce_item(raw) -> dict | None:
    """投入アイテムを正規化する。数値ID・文字列ID・オブジェクトのいずれも許容する。"""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return {"illust_id": raw}
    if isinstance(raw, str) and raw.strip().isdigit():
        return {"illust_id": int(raw.strip())}
    if isinstance(raw, dict):
        return raw
    return None


@app.post("/api/queue")
async def enqueue(request: Request) -> dict:
    if not client.is_configured():
        raise HTTPException(status_code=401, detail="pixivにログインしていません。")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="リクエストボディのJSONが不正です。")
    # {"items":[...]} でも 素の [...] でも受理する
    raw_items = body.get("items") if isinstance(body, dict) else body
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=400, detail="items は配列で指定してください。")

    added = 0
    for raw in raw_items:
        item = _coerce_item(raw)
        if not item:
            continue
        if item.get("illust_id"):
            download_queue.add_illust(int(item["illust_id"]), item.get("title"), item.get("source_url"))
            added += 1
        elif item.get("user_id"):
            download_queue.add_user(int(item["user_id"]))
            added += 1
    return {"accepted": added}


@app.get("/api/queue")
def queue_state() -> dict:
    return download_queue.snapshot()


@app.post("/api/queue/pause")
def queue_pause() -> dict:
    download_queue.pause()
    return {"paused": True}


@app.post("/api/queue/resume")
def queue_resume() -> dict:
    download_queue.resume()
    return {"paused": False}


@app.post("/api/queue/clear")
def queue_clear() -> dict:
    download_queue.clear_finished()
    return {"ok": True}


@app.post("/api/queue/retry/{item_id}")
def queue_retry(item_id: str) -> dict:
    return {"ok": download_queue.retry(item_id)}


@app.get("/api/queue/stream")
async def queue_stream() -> StreamingResponse:
    async def event_generator():
        while True:
            snapshot = download_queue.snapshot()
            yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            await asyncio.sleep(config.SSE_PUSH_INTERVAL_SECONDS)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# --- RSS フィード -----------------------------------------------------------
# 外部RSSリーダーから購読できるよう、トークンはクエリ(?token=)でも受理する。
def require_rss_token(request: Request, token: str = Query(default=""),
                      x_api_token: str = Header(default="")) -> None:
    expected = store.get_settings().get("api_token")
    supplied = token or x_api_token or request.cookies.get(SESSION_COOKIE, "")
    if not expected or supplied != expected:
        raise HTTPException(status_code=401, detail="トークンが不正です。?token=<APIトークン> を付けてください。")


_RSS_MEDIA = "application/rss+xml; charset=utf-8"


def _rss_response(title: str, link: str, desc: str, illusts: list, request: Request) -> Response:
    xml = rss.build_feed(title, link, desc, illusts, str(request.base_url))
    return Response(content=xml, media_type=_RSS_MEDIA)


@app.get("/api/rss/user/{user_id}", dependencies=[Depends(require_rss_token)])
def rss_user(user_id: int, request: Request) -> Response:
    if not client.is_configured():
        return _rss_response("pixiv: 未ログイン", "https://www.pixiv.net/", "ダッシュボードでログインしてください。", [], request)
    illusts = client.user_illusts_first(user_id)
    name = (illusts[0]["user"]["name"] if illusts else f"user {user_id}")
    return _rss_response(
        f"pixiv: {name} の新着", f"https://www.pixiv.net/users/{user_id}",
        f"{name} の新着作品", illusts, request,
    )


@app.get("/api/rss/search", dependencies=[Depends(require_rss_token)])
def rss_search(request: Request, word: str = Query(...)) -> Response:
    if not client.is_configured():
        return _rss_response("pixiv: 未ログイン", "https://www.pixiv.net/", "ダッシュボードでログインしてください。", [], request)
    illusts = client.search(word).get("illusts", [])
    link = f"https://www.pixiv.net/tags/{word}/artworks"
    return _rss_response(f"pixiv検索: {word}", link, f"「{word}」の検索結果", illusts, request)


@app.get("/api/rss/following", dependencies=[Depends(require_rss_token)])
def rss_following(request: Request) -> Response:
    if not client.is_configured():
        return _rss_response("pixiv: 未ログイン", "https://www.pixiv.net/", "ダッシュボードでログインしてください。", [], request)
    illusts = client.following_illusts()
    return _rss_response("pixiv: フォロー新着", "https://www.pixiv.net/bookmark_new_illust.php",
                         "フォロー中ユーザーの新着作品", illusts, request)


# --- 画像プロキシ（Referer制限を回避。サーバーには保存せずストリームのみ）-------
@app.get("/api/proxy/image")
def proxy_image(url: str = Query(...)) -> StreamingResponse:
    if not url.startswith("https://") or "pximg.net" not in url:
        raise HTTPException(status_code=400, detail="許可されていないURLです。")
    upstream = requests.get(
        url,
        headers={"Referer": config.IMAGE_REFERER, "User-Agent": config.IMAGE_USER_AGENT},
        stream=True,
        timeout=config.HTTP_TIMEOUT_SECONDS,
    )
    if upstream.status_code != 200:
        raise HTTPException(status_code=upstream.status_code, detail="画像取得に失敗しました。")
    return StreamingResponse(
        upstream.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE),
        media_type=upstream.headers.get("Content-Type", "image/jpeg"),
        headers={"Cache-Control": "no-store"},
    )
