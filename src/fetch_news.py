"""Ambil berita dari RSS feed dan kembalikan artikel baru."""
from __future__ import annotations

import hashlib
import re

import feedparser
import requests
from bs4 import BeautifulSoup

from utils import is_processed, load_config, log


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def _entry_id(entry) -> str:
    raw = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def fetch_articles(cfg: dict) -> list[dict]:
    """Kembalikan daftar artikel BARU (belum pernah diproses).

    Tiap artikel: {id, title, summary, link, source}
    """
    feeds = cfg["news"]["feeds"]
    min_chars = cfg["news"]["min_chars"]
    limit = cfg["news"]["max_per_run"]

    found: list[dict] = []
    for feed_url in feeds:
        log.info("Membaca feed: %s", feed_url)
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:  # noqa: BLE001
            log.warning("Gagal baca feed %s: %s", feed_url, e)
            continue

        for entry in parsed.entries:
            nid = _entry_id(entry)
            if is_processed(cfg, nid):
                continue

            title = entry.get("title", "").strip()
            summary = _clean_html(
                entry.get("summary") or entry.get("description") or ""
            )
            # Coba ambil isi lebih lengkap jika ada content:encoded
            if entry.get("content"):
                summary = _clean_html(entry["content"][0].get("value", "")) or summary

            if len(summary) < min_chars:
                log.info("Lewati (terlalu pendek): %s", title[:50])
                continue

            found.append(
                {
                    "id": nid,
                    "title": title,
                    "summary": summary,
                    "link": entry.get("link", ""),
                    "source": parsed.feed.get("title", feed_url),
                }
            )
            if len(found) >= limit:
                return found

    return found


if __name__ == "__main__":
    cfg = load_config()
    arts = fetch_articles(cfg)
    log.info("Ditemukan %d artikel baru", len(arts))
    for a in arts:
        print(f"- [{a['id']}] {a['title']}\n  {a['summary'][:120]}...")
