"""Buat metadata YouTube SEO-friendly: judul, deskripsi, tags.

Memakai Ollama (LLM lokal). Ada fallback bila Ollama tidak tersedia.
Judul & deskripsi dibuat HANYA dari fakta artikel (tidak mengarang/clickbait
menyesatkan), tetap menarik dan mengandung kata kunci pencarian.
"""
from __future__ import annotations

import json
import re

import requests

from utils import log

SEO_SYSTEM = """You write YouTube metadata for a factual world-news animation channel.
Given a news article, produce SEO-friendly metadata in English.

Return ONLY valid JSON:
{"title": "...", "description": "...", "tags": ["...", "..."]}

RULES:
- title: <= 90 characters, accurate and engaging, include the main keywords a
  viewer would search. NO misleading clickbait, NO fabricated claims.
- description: 2-4 sentences summarising the story (only facts from the article),
  then a blank line, then 5-8 relevant hashtags.
- tags: 10-15 lowercase search keywords/phrases relevant to the story.
- Everything must stay strictly on the article's topic. Do not invent facts."""


def _ollama_json(cfg: dict, user: str) -> dict | None:
    sc = cfg["script"]
    payload = {
        "model": sc["model"],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.5},
        "messages": [
            {"role": "system", "content": SEO_SYSTEM},
            {"role": "user", "content": user},
        ],
    }
    try:
        r = requests.post(f"{sc['ollama_url']}/api/chat", json=payload, timeout=180)
        r.raise_for_status()
        content = r.json()["message"]["content"]
        m = re.search(r"\{.*\}", content, re.DOTALL)
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # noqa: BLE001
        log.warning("SEO via Ollama gagal (%s). Pakai fallback.", e)
        return None


def _fallback(article: dict, scenario: dict, cfg: dict) -> dict:
    title = article["title"][:90]
    treatment = scenario.get("treatment") or article.get("summary", "")
    desc = treatment[:280].rsplit(".", 1)[0] + "."
    base_tags = cfg["youtube"].get("tags", [])
    # tambah kata kunci dari judul
    extra = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", article["title"])][:8]
    tags = list(dict.fromkeys(base_tags + extra))
    hashtags = " ".join("#" + t.replace(" ", "") for t in (base_tags[:5] or ["worldnews"]))
    return {
        "title": title,
        "description": f"{desc}\n\n{hashtags}",
        "tags": tags,
    }


def generate_metadata(cfg: dict, article: dict, scenario: dict) -> dict:
    """Hasilkan {title, description, tags} untuk upload YouTube."""
    meta = None
    if cfg["script"].get("use_ollama"):
        treatment = scenario.get("treatment") or article.get("summary", "")
        user = (
            f"ARTICLE TITLE: {article['title']}\n\n"
            f"SUMMARY:\n{treatment[:1200]}\n\n"
            f"Source: {article.get('source','')}"
        )
        meta = _ollama_json(cfg, user)

    if not meta or not meta.get("title"):
        meta = _fallback(article, scenario, cfg)

    # rapikan & batasi
    yt = cfg["youtube"]
    meta["title"] = (yt.get("title_prefix", "") + str(meta["title"]).strip())[:100]
    desc = str(meta.get("description", "")).strip()
    # selalu sertakan kredit sumber (enumerasi bila multi-sumber)
    sources = article.get("sources") or []
    if sources:
        # Nama sumber TETAP dicantumkan penuh (etika atribusi). Hanya pemisah
        # kategori feed '>' diganti '-' agar terbaca natural & lolos validasi YouTube.
        lines = "\n".join(
            f"- {str(s.get('name','')).replace('>', '-')}: {s.get('link','')}".rstrip(": ")
            for s in sources
        )
        src = f"\n\nSources:\n{lines}"
    else:
        src = f"\n\nSource: {article.get('source','')}\n{article.get('link','')}"
    meta["description"] = (desc + src + yt.get("description_footer", ""))[:4900]
    tags = meta.get("tags") or yt.get("tags", [])
    # gabung dgn tag default, unik, batasi
    tags = list(dict.fromkeys([str(t).lower().strip() for t in tags if t]))[:20]
    meta["tags"] = tags
    log.info("SEO judul: %s", meta["title"])
    return meta


if __name__ == "__main__":
    from utils import load_config

    cfg = load_config()
    art = {
        "title": "Coastal city hit by severe flooding after major storm",
        "summary": "A severe storm caused major flooding in a coastal city. Water "
        "rose over one metre. Hundreds were evacuated. Officials warned of more rain.",
        "source": "BBC World",
        "link": "https://example.com/flood",
    }
    scenario = {"treatment": art["summary"]}
    print(json.dumps(generate_metadata(cfg, art, scenario), ensure_ascii=False, indent=2))
