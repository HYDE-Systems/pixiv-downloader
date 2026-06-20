"""pixivの作品リストからRSS 2.0フィードXMLを生成する。

サムネイルはRefererが必要なため、ダッシュボードの画像プロキシ経由の絶対URLで埋め込む
（RSSリーダーがそのまま画像取得できる）。
"""
from __future__ import annotations

from datetime import datetime
from email.utils import format_datetime
from urllib.parse import quote
from xml.sax.saxutils import escape

DC_NS = "http://purl.org/dc/elements/1.1/"


def _rfc822(iso: str) -> str:
    try:
        return format_datetime(datetime.fromisoformat(iso))
    except (ValueError, TypeError):
        return ""


def _proxy(base_url: str, img: str) -> str:
    if not img:
        return ""
    return f"{base_url}api/proxy/image?url={quote(img, safe='')}"


def build_feed(title: str, link: str, description: str, illusts: list[dict], base_url: str) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<rss version="2.0" xmlns:dc="{DC_NS}">',
        "<channel>",
        f"<title>{escape(title)}</title>",
        f"<link>{escape(link)}</link>",
        f"<description>{escape(description)}</description>",
        "<generator>Pixiv Download Studio</generator>",
    ]
    for il in illusts:
        art_url = f"https://www.pixiv.net/artworks/{il['id']}"
        artist = (il.get("user") or {}).get("name", "")
        thumb = (il.get("image_urls") or {}).get("square_medium", "")
        pages = il.get("page_count", 1)
        tags = ", ".join(t.get("name", "") for t in il.get("tags", [])[:8])
        body = (
            f'<img src="{_proxy(base_url, thumb)}" alt=""/><br/>'
            f"作者: {escape(artist)}<br/>"
            f"ページ数: {pages} / 種別: {escape(il.get('type', ''))}<br/>"
            f"タグ: {escape(tags)}"
        )
        parts.append("<item>")
        parts.append(f"<title>{escape(il.get('title', '') or '(無題)')}</title>")
        parts.append(f"<link>{escape(art_url)}</link>")
        parts.append(f'<guid isPermaLink="true">{escape(art_url)}</guid>')
        if artist:
            parts.append(f"<dc:creator>{escape(artist)}</dc:creator>")
        pub = _rfc822(il.get("create_date", ""))
        if pub:
            parts.append(f"<pubDate>{pub}</pubDate>")
        parts.append(f"<description><![CDATA[{body}]]></description>")
        parts.append("</item>")
    parts.append("</channel></rss>")
    return "\n".join(parts)
