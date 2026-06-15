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


def fetch_fulltext(url: str, timeout: int = 15) -> str:
    """Unduh halaman artikel dan ambil isi paragraf utama.

    RSS biasanya hanya memberi ringkasan pendek, jadi kita ambil teks penuh
    dari halaman aslinya. Heuristik sederhana: kumpulkan semua <p>.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (news2anim bot)"}
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        # buang elemen non-konten
        for tag in soup(["script", "style", "nav", "footer", "aside", "form"]):
            tag.decompose()
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        # ambil paragraf yang cukup panjang (hindari menu/caption)
        paragraphs = [p for p in paragraphs if len(p) > 40]
        text = " ".join(paragraphs)
        return re.sub(r"\s+", " ", text).strip()
    except Exception as e:  # noqa: BLE001
        log.warning("Gagal ambil teks penuh %s: %s", url, e)
        return ""


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

            # RSS sering pendek -> coba ambil teks penuh dari halaman artikel
            link = entry.get("link", "")
            if len(summary) < min_chars and link and cfg["news"].get("fetch_fulltext", True):
                full = fetch_fulltext(link)
                if len(full) > len(summary):
                    summary = full

            if len(summary) < min_chars:
                log.info("Lewati (terlalu pendek): %s", title[:50])
                continue
            # batasi panjang agar naskah tidak kepanjangan
            summary = summary[: cfg["news"].get("max_chars", 1500)]

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
