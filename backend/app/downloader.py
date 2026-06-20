"""ダウンロードキューとワーカー。pixiv→メモリ→SMB へストリームし、サーバーには残さない。"""
from __future__ import annotations

import queue
import re
import threading
import time
import uuid
from datetime import datetime

import requests

from . import config, smb_writer
from .pixiv_client import client, extract_image_urls
from .store import store

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')
_session = requests.Session()


def _sanitize(name: str) -> str:
    return _INVALID_CHARS.sub("_", (name or "").strip()).strip(". ") or "untitled"


def _build_path(template: str, *, artist, artist_id, title, illust_id, page, ext, date) -> str:
    raw = template.format(
        artist=_sanitize(artist),
        artist_id=artist_id,
        title=_sanitize(title),
        illust_id=illust_id,
        page=page,
        ext=ext,
        date=date,
    )
    # ディレクトリ区切りは保持しつつ各セグメントを健全化
    segments = [seg for seg in raw.replace("\\", "/").split("/") if seg not in ("", ".", "..")]
    return "/".join(_sanitize(seg) if i < len(segments) - 1 else seg for i, seg in enumerate(segments))


class DownloadQueue:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, dict] = {}
        self._order: list[str] = []
        self._pending: queue.Queue[str] = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._started = False
        self._paused = threading.Event()
        self._dirty = threading.Event()

    # --- 起動/復元 --------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._restore()
        concurrency = max(1, min(store.get_settings()["download"]["concurrency"], config.MAX_CONCURRENCY))
        for _ in range(concurrency):
            thread = threading.Thread(target=self._worker_loop, daemon=True)
            thread.start()
            self._workers.append(thread)
        threading.Thread(target=self._snapshot_loop, daemon=True).start()

    def _restore(self) -> None:
        for item in store.load_queue_snapshot():
            # 未完了のものだけ復元して再投入
            if item.get("state") in ("queued", "downloading", "resolving"):
                item["state"] = "queued"
                self._items[item["id"]] = item
                self._order.append(item["id"])
                self._pending.put(item["id"])

    # --- 投入 --------------------------------------------------------------
    def add_illust(self, illust_id: int, title: str | None = None, source_url: str | None = None) -> str:
        item = {
            "id": uuid.uuid4().hex,
            "kind": "illust",
            "illust_id": illust_id,
            "title": title or f"#{illust_id}",
            "artist": "",
            "thumb_url": "",
            "source_url": source_url,
            "state": "queued",
            "pages_total": 0,
            "pages_done": 0,
            "bytes": 0,
            "error": "",
            "added_at": time.time(),
        }
        with self._lock:
            self._items[item["id"]] = item
            self._order.append(item["id"])
        self._pending.put(item["id"])
        self._dirty.set()
        return item["id"]

    def add_user(self, user_id: int) -> None:
        """ユーザーの全作品を非同期に展開してキューへ。"""
        def _resolve() -> None:
            try:
                ids = client.user_illust_ids(user_id)
            except Exception as exc:  # noqa: BLE001
                self._add_error_marker(f"作家 {user_id} の展開に失敗: {exc}")
                return
            for illust_id in ids:
                self.add_illust(illust_id, source_url=f"https://www.pixiv.net/artworks/{illust_id}")

        threading.Thread(target=_resolve, daemon=True).start()

    def _add_error_marker(self, message: str) -> None:
        item = {
            "id": uuid.uuid4().hex, "kind": "note", "title": message, "artist": "",
            "thumb_url": "", "state": "error", "pages_total": 0, "pages_done": 0,
            "bytes": 0, "error": message, "added_at": time.time(),
        }
        with self._lock:
            self._items[item["id"]] = item
            self._order.append(item["id"])
        self._dirty.set()

    # --- 制御 --------------------------------------------------------------
    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def is_paused(self) -> bool:
        return self._paused.is_set()

    def retry(self, item_id: str) -> bool:
        with self._lock:
            item = self._items.get(item_id)
            if not item or item["state"] not in ("error",):
                return False
            item.update(state="queued", error="", pages_done=0, bytes=0)
        self._pending.put(item_id)
        self._dirty.set()
        return True

    def clear_finished(self) -> None:
        with self._lock:
            keep = [i for i in self._order if self._items[i]["state"] in ("queued", "downloading", "resolving")]
            self._items = {i: self._items[i] for i in keep}
            self._order = keep
        self._dirty.set()

    def snapshot(self) -> dict:
        with self._lock:
            items = [self._items[i] for i in self._order]
            stats = {"queued": 0, "downloading": 0, "done": 0, "error": 0, "bytes": 0}
            for it in items:
                stats[it["state"]] = stats.get(it["state"], 0) + 1
                stats["bytes"] += it.get("bytes", 0)
            return {"items": items, "stats": stats, "paused": self.is_paused()}

    # --- ワーカー ----------------------------------------------------------
    def _worker_loop(self) -> None:
        while True:
            try:
                item_id = self._pending.get(timeout=config.WORKER_IDLE_SLEEP_SECONDS)
            except queue.Empty:
                continue
            while self._paused.is_set():
                time.sleep(config.WORKER_IDLE_SLEEP_SECONDS)
            self._process(item_id)
            self._pending.task_done()

    def _set(self, item_id: str, **changes) -> None:
        with self._lock:
            item = self._items.get(item_id)
            if item:
                item.update(changes)
        self._dirty.set()

    def _process(self, item_id: str) -> None:
        with self._lock:
            item = self._items.get(item_id)
        if not item or item["state"] != "queued":
            return
        self._set(item_id, state="downloading")
        settings = store.get_settings()
        smb = settings["smb"]
        opts = settings["download"]
        try:
            illust = client.illust_detail(item["illust_id"])
            artist = illust["user"]["name"]
            artist_id = illust["user"]["id"]
            title = illust["title"]
            date = (illust.get("create_date") or "")[:10]
            self._set(item_id, artist=artist, title=title,
                      thumb_url=illust["image_urls"].get("square_medium", ""))

            is_ugoira = illust.get("type") == "ugoira"
            if is_ugoira and opts.get("download_ugoira"):
                urls = [self._ugoira_zip_url(item["illust_id"])]
            else:
                urls = extract_image_urls(illust)
            self._set(item_id, pages_total=len(urls))

            ctx = {"artist": artist, "artist_id": artist_id, "title": title,
                   "illust_id": item["illust_id"], "date": date}

            # うごイラはpixiv側で既にzipなので二重圧縮しない
            if opts.get("zip_per_work") and not is_ugoira:
                done_bytes = self._download_as_zip(item_id, urls, illust, opts, smb, ctx)
            else:
                done_bytes = self._download_pages(item_id, urls, smb, opts, ctx)
                if opts.get("save_metadata"):
                    self._write_metadata(illust, opts, smb, ctx)

            self._set(item_id, state="done", bytes=done_bytes)
        except Exception as exc:  # noqa: BLE001
            self._set(item_id, state="error", error=str(exc))

    @staticmethod
    def _ext_of(url: str) -> str:
        return url.rsplit(".", 1)[-1].split("?")[0] or "jpg"

    def _download_pages(self, item_id, urls, smb, opts, ctx) -> int:
        """各ページを個別ファイルとしてSMBへ保存する。"""
        done = 0
        for page, url in enumerate(urls):
            rel = _build_path(opts["filename_template"], page=page, ext=self._ext_of(url), **ctx)
            if opts.get("skip_existing") and smb_writer.exists(smb, rel):
                self._set(item_id, pages_done=page + 1)
                continue
            done += self._stream_to_smb(url, smb, rel)
            self._set(item_id, pages_done=page + 1, bytes=done)
        return done

    def _download_as_zip(self, item_id, urls, illust, opts, smb, ctx) -> int:
        """作品の全ページ+メタデータを1つのzipにまとめ、SMBへストリーム書込みする。"""
        import json
        import zipfile

        zip_rel = self._zip_path(opts, ctx)
        if opts.get("skip_existing") and smb_writer.exists(smb, zip_rel):
            self._set(item_id, pages_done=len(urls))
            return 0
        headers = {"Referer": config.IMAGE_REFERER, "User-Agent": config.IMAGE_USER_AGENT}
        written = 0
        # 画像は既に圧縮済みなので ZIP_STORED（無圧縮）で束ねるだけにする
        with smb_writer.open_write(smb, zip_rel) as smb_handle:
            with zipfile.ZipFile(smb_handle, "w", zipfile.ZIP_STORED) as zf:
                for page, url in enumerate(urls):
                    arcname = f"{ctx['illust_id']}_p{page}.{self._ext_of(url)}"
                    with _session.get(url, headers=headers, stream=True,
                                      timeout=config.HTTP_TIMEOUT_SECONDS) as resp:
                        resp.raise_for_status()
                        with zf.open(arcname, "w") as entry:
                            for chunk in resp.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE):
                                if chunk:
                                    entry.write(chunk)
                                    written += len(chunk)
                    self._set(item_id, pages_done=page + 1, bytes=written)
                if opts.get("save_metadata"):
                    meta = json.dumps(self._metadata_payload(illust, ctx), ensure_ascii=False, indent=2)
                    zf.writestr("metadata.json", meta)
        return written

    def _stream_to_smb(self, url: str, smb: dict, rel: str) -> int:
        headers = {"Referer": config.IMAGE_REFERER, "User-Agent": config.IMAGE_USER_AGENT}
        written = 0
        with _session.get(url, headers=headers, stream=True, timeout=config.HTTP_TIMEOUT_SECONDS) as resp:
            resp.raise_for_status()
            with smb_writer.open_write(smb, rel) as handle:
                for chunk in resp.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        handle.write(chunk)
                        written += len(chunk)
        return written

    def _ugoira_zip_url(self, illust_id: int) -> str:
        meta = client.ugoira_metadata(illust_id)
        return meta["zip_urls"]["medium"]

    def _zip_path(self, opts, ctx) -> str:
        """テンプレートのフォルダ構成を尊重しつつ、作品単位のzipパスを組み立てる。"""
        sample = _build_path(opts["filename_template"], page=0, ext="zip", **ctx)
        dirpart = sample.rsplit("/", 1)[0] if "/" in sample else ""
        name = f"{ctx['illust_id']}_{_sanitize(ctx['title'])}.zip"
        return f"{dirpart}/{name}" if dirpart else name

    @staticmethod
    def _metadata_payload(illust, ctx) -> dict:
        return {
            "illust_id": ctx["illust_id"], "title": ctx["title"], "artist": ctx["artist"],
            "artist_id": ctx["artist_id"], "type": illust.get("type"),
            "tags": [t["name"] for t in illust.get("tags", [])],
            "create_date": illust.get("create_date"), "caption": illust.get("caption", ""),
            "total_view": illust.get("total_view"), "total_bookmarks": illust.get("total_bookmarks"),
        }

    def _write_metadata(self, illust, opts, smb, ctx) -> None:
        import json
        rel = _build_path(opts["filename_template"], page=0, ext="json", **ctx)
        rel = rel.rsplit("_p0.", 1)[0] + ".json" if "_p0." in rel else rel
        smb_writer.write_text(smb, rel, json.dumps(self._metadata_payload(illust, ctx),
                                                   ensure_ascii=False, indent=2))

    # --- スナップショット保存 ---------------------------------------------
    def _snapshot_loop(self) -> None:
        while True:
            self._dirty.wait()
            time.sleep(2.0)
            self._dirty.clear()
            store.save_queue_snapshot(self.snapshot()["items"])


download_queue = DownloadQueue()
