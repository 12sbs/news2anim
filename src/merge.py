"""Gabung fakta dari BANYAK sumber (satu cluster peristiwa) menjadi satu artikel.

Output `merge_cluster` adalah dict berbentuk SUPERSET dari artikel biasa, sehingga
seluruh tahap hilir (script_gen, seo, render._download_broll) bekerja tanpa diubah:

  {id, title, summary, link, source, sources, image_url, image_candidates}

Faithfulness terjaga: `summary` hanya berisi kalimat yang BENAR-BENAR muncul di
artikel sumber. Penggabungan tidak menambah fakta apa pun — hanya menyatukan dan
membuang kalimat yang berulang antar-sumber.
"""
from __future__ import annotations

import re

from utils import log

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_TOKEN = re.compile(r"[a-zA-Z]{3,}")


def _norm_key(sentence: str) -> str:
    """Kunci normalisasi kalimat (huruf kecil, hanya alnum+spasi)."""
    return re.sub(r"[^a-z0-9 ]", "", sentence.lower()).strip()


def _tokens(sentence: str) -> set[str]:
    return {t for t in _TOKEN.findall(sentence.lower())}


def _overlap(a: set, b: set) -> float:
    """Overlap coefficient: |A∩B| / min(|A|,|B|) (pola sama dgn dedup._overlap)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _dedupe_sentences(texts: list[str], cap_chars: int) -> str:
    """Gabung body antar-sumber, buang kalimat near-duplicate, potong di batas kalimat.

    Urutan dipertahankan: sumber primer (texts[0]) dulu sebagai tulang punggung,
    sumber berikutnya hanya menyumbang kalimat yang BENAR-BENAR baru.
    """
    kept: list[str] = []
    kept_keys: set[str] = set()
    kept_tokens: list[set[str]] = []

    for text in texts:
        if not text:
            continue
        for sent in _SENT_SPLIT.split(text):
            sent = sent.strip()
            if len(sent) < 25:  # buang fragmen/teks navigasi
                continue
            key = _norm_key(sent)
            if not key or key in kept_keys:
                continue
            toks = _tokens(sent)
            # lewati bila isinya ~sama dengan kalimat yang sudah ada
            if any(_overlap(toks, kt) >= 0.8 for kt in kept_tokens):
                continue
            kept.append(sent)
            kept_keys.add(key)
            kept_tokens.append(toks)

    merged = " ".join(kept)
    if len(merged) <= cap_chars:
        return merged
    # potong di batas kalimat terdekat sebelum cap
    cut = merged[:cap_chars]
    m = list(_SENT_SPLIT.finditer(cut))
    if m:
        cut = cut[: m[-1].end()].strip()
    return cut.strip()


def merge_cluster(cfg: dict, cluster: list[dict]) -> dict:
    """Gabungkan anggota cluster jadi satu artikel multi-sumber.

    `cluster` diasumsikan sudah terurut: anggota paling kaya (primer) di depan.
    """
    if not cluster:
        raise ValueError("cluster kosong")

    primary = cluster[0]
    cap = cfg.get("news", {}).get("merge_max_chars", 6000)

    # judul terlengkap
    title = max((a.get("title", "") for a in cluster), key=len, default=primary.get("title", ""))

    # body gabungan ter-dedup (primer dulu)
    texts = [a.get("summary", "") for a in cluster]
    summary = _dedupe_sentences(texts, cap)

    # atribusi sumber unik (jaga urutan)
    sources: list[dict] = []
    seen_names: set[str] = set()
    image_candidates: list[str] = []
    for a in cluster:
        name = (a.get("source") or "").strip()
        link = (a.get("link") or "").strip()
        if name and name.lower() not in seen_names:
            seen_names.add(name.lower())
            sources.append({"name": name, "link": link})
        img = (a.get("image_url") or "").strip()
        if img and img not in image_candidates:
            image_candidates.append(img)

    source_str = ", ".join(s["name"] for s in sources) or primary.get("source", "")

    merged = {
        "id": primary.get("id", ""),
        "title": title,
        "summary": summary,
        "link": primary.get("link", ""),
        "source": source_str,
        "sources": sources,
        "image_url": image_candidates[0] if image_candidates else "",
        "image_candidates": image_candidates,
    }
    log.info(
        "Merge: %d sumber -> %d kata gabungan (%s)",
        len(cluster), len(summary.split()), source_str[:60],
    )
    return merged


if __name__ == "__main__":
    from utils import load_config

    cfg = load_config()
    cluster = [
        {"id": "a1", "title": "Trump says deal to end war with Iran signed",
         "source": "BBC World", "link": "https://bbc.example/iran",
         "image_url": "https://img.example/a.jpg",
         "summary": "US President Donald Trump announced a deal to end the war "
         "with Iran has been signed. The Strait of Hormuz will reopen on Friday. "
         "Oil prices fell after the announcement."},
        {"id": "b2", "title": "Iran-US agreement signed, Trump confirms",
         "source": "Al Jazeera", "link": "https://aj.example/iran",
         "image_url": "https://img.example/b.jpg",
         "summary": "Donald Trump confirmed an agreement with Iran was signed. "
         "The Strait of Hormuz will reopen on Friday. Iranian officials said "
         "oil shipments through the strait resume immediately."},
    ]
    m = merge_cluster(cfg, cluster)
    print("TITLE :", m["title"])
    print("SOURCE:", m["source"])
    print("IMGS  :", m["image_candidates"])
    print("WORDS :", len(m["summary"].split()))
    print("BODY  :", m["summary"])
