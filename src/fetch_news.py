"""Ambil berita dari RSS feed dan kembalikan artikel baru."""
from __future__ import annotations

import hashlib
import math
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


def _fetch_feed(feed_url: str, timeout: int = 15):
    """Ambil & parse RSS feed DENGAN timeout.

    feedparser.parse(url) melakukan fetch HTTP-nya sendiri TANPA timeout, jadi
    server yang menggantung (mis. CDN yang menerima koneksi tapi tak mengirim
    data) bisa membekukan SELURUH pipeline tanpa batas. Kita unduh via requests
    (punya timeout) lalu parse byte-nya. Bonus: User-Agent kustom mengurangi 403.
    """
    headers = {"User-Agent": "Mozilla/5.0 (news2anim bot)"}
    r = requests.get(feed_url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return feedparser.parse(r.content)


def fetch_page(url: str, timeout: int = 15) -> dict:
    """Unduh halaman artikel: kembalikan {text, image}.

    - text : gabungan paragraf utama (RSS sering pendek -> ambil teks penuh).
    - image: URL gambar utama (og:image) untuk dipakai sebagai b-roll.
    """
    result = {"text": "", "image": ""}
    try:
        headers = {"User-Agent": "Mozilla/5.0 (news2anim bot)"}
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        # og:image (gambar utama artikel)
        og = soup.find("meta", property="og:image") or soup.find(
            "meta", attrs={"name": "twitter:image"}
        )
        if og and og.get("content"):
            result["image"] = og["content"].strip()
        # teks
        for tag in soup(["script", "style", "nav", "footer", "aside", "form"]):
            tag.decompose()
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        paragraphs = [p for p in paragraphs if len(p) > 40]
        result["text"] = re.sub(r"\s+", " ", " ".join(paragraphs)).strip()
    except Exception as e:  # noqa: BLE001
        log.warning("Gagal ambil halaman %s: %s", url, e)
    return result


def fetch_fulltext(url: str, timeout: int = 15) -> str:
    """Kompatibilitas: hanya teks penuh."""
    return fetch_page(url, timeout)["text"]


def _entry_image(entry) -> str:
    """Ambil gambar dari entri RSS (media:thumbnail/content/enclosure)."""
    for key in ("media_thumbnail", "media_content"):
        media = entry.get(key)
        if media and isinstance(media, list) and media[0].get("url"):
            return media[0]["url"]
    for link in entry.get("links", []):
        if link.get("type", "").startswith("image") and link.get("href"):
            return link["href"]
    return ""


def _build_article(cfg: dict, entry, source_name: str) -> dict | None:
    """Bangun satu artikel dari entri RSS (atau None bila tak layak/duplikat)."""
    nid = _entry_id(entry)
    if is_processed(cfg, nid):
        return None

    min_chars = cfg["news"]["min_chars"]
    title = entry.get("title", "").strip()
    summary = _clean_html(entry.get("summary") or entry.get("description") or "")
    if entry.get("content"):
        summary = _clean_html(entry["content"][0].get("value", "")) or summary

    image_url = _entry_image(entry)
    link = entry.get("link", "")

    # RSS sering pendek -> ambil teks penuh (+ og:image) dari halaman
    if len(summary) < min_chars and link and cfg["news"].get("fetch_fulltext", True):
        page = fetch_page(link)
        if len(page["text"]) > len(summary):
            summary = page["text"]
        if not image_url and page["image"]:
            image_url = page["image"]

    if len(summary) < min_chars:
        log.info("Lewati (terlalu pendek): %s", title[:50])
        return None

    summary = summary[: cfg["news"].get("max_chars", 1500)]
    return {
        "id": nid,
        "title": title,
        "summary": summary,
        "link": link,
        "source": source_name,
        "image_url": image_url,
    }


def fetch_articles(cfg: dict) -> list[dict]:
    """Kembalikan daftar artikel BARU lintas-feed (ROUND-ROBIN demi keberagaman sumber).

    Round-robin penting: agar peristiwa sama dari BBC + Al Jazeera + Guardian
    sama-sama terambil dan bisa di-cluster (bukan menguras 1 feed saja).
    Tiap artikel: {id, title, summary, link, source, image_url}
    """
    feeds = cfg["news"]["feeds"]
    limit = cfg["news"]["max_per_run"]
    # batasi per-feed agar fetch fulltext tidak meledak, tetap beri buffer keberagaman
    per_feed_cap = max(1, math.ceil(limit / max(1, len(feeds)))) + 3

    per_feed: list[list[dict]] = []
    for feed_url in feeds:
        log.info("Membaca feed: %s", feed_url)
        try:
            parsed = _fetch_feed(feed_url)
        except Exception as e:  # noqa: BLE001
            log.warning("Gagal baca feed %s: %s", feed_url, e)
            continue
        source_name = parsed.feed.get("title", feed_url)
        bucket: list[dict] = []
        for entry in parsed.entries:
            art = _build_article(cfg, entry, source_name)
            if art:
                bucket.append(art)
            if len(bucket) >= per_feed_cap:
                break
        per_feed.append(bucket)

    # gabung round-robin sampai mencapai limit
    found: list[dict] = []
    idx = 0
    while len(found) < limit and any(idx < len(b) for b in per_feed):
        for b in per_feed:
            if idx < len(b):
                found.append(b[idx])
                if len(found) >= limit:
                    break
        idx += 1

    log.info("Total artikel baru terambil: %d (dari %d feed)", len(found), len(per_feed))
    return found


if __name__ == "__main__":
    cfg = load_config()
    arts = fetch_articles(cfg)
    log.info("Ditemukan %d artikel baru", len(arts))
    for a in arts:
        print(f"- [{a['id']}] {a['title']}\n  {a['summary'][:120]}...")
