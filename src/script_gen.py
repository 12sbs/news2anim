"""Ubah artikel berita menjadi skenario adegan (JSON) memakai Ollama (LLM lokal).

Output skenario:
{
  "title": "...",
  "scenes": [
     {"speaker": "Host", "text": "...", "background": "studio"},
     {"speaker": "Narator", "text": "...", "background": "jalan"}
  ]
}
"""
from __future__ import annotations

import json
import re

import requests

from utils import load_config, log

SYSTEM_PROMPT = """Kamu adalah penulis naskah video berita animasi berbahasa Indonesia.
Ubah artikel berita menjadi naskah video pendek yang natural dan mudah dipahami.
Pecah menjadi beberapa adegan. Tiap adegan punya:
- speaker: "Host" (pembawa berita) atau "Narator"
- text: kalimat yang diucapkan (1-3 kalimat, bahasa lugas)
- background: satu kata kunci latar (mis. studio, jalan, gedung, banjir)

Balas HANYA dengan JSON valid, tanpa penjelasan, format:
{"title": "...", "scenes": [{"speaker": "...", "text": "...", "background": "..."}]}
"""


def _extract_json(text: str) -> dict | None:
    """Ambil objek JSON pertama dari teks bebas."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _via_ollama(cfg: dict, article: dict) -> dict | None:
    sc = cfg["script"]
    prompt = (
        f"Judul: {article['title']}\n\n"
        f"Isi berita:\n{article['summary']}\n\n"
        f"Buat maksimal {sc['max_scenes']} adegan."
    )
    payload = {
        "model": sc["model"],
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "format": "json",
    }
    try:
        r = requests.post(
            f"{sc['ollama_url']}/api/chat", json=payload, timeout=180
        )
        r.raise_for_status()
        content = r.json()["message"]["content"]
        return _extract_json(content)
    except Exception as e:  # noqa: BLE001
        log.warning("Ollama gagal (%s). Pakai fallback.", e)
        return None


def _fallback(cfg: dict, article: dict) -> dict:
    """Pemecah kalimat sederhana bila Ollama tidak ada."""
    max_scenes = cfg["script"]["max_scenes"]
    sentences = re.split(r"(?<=[.!?])\s+", article["summary"])
    sentences = [s.strip() for s in sentences if len(s.strip()) > 15]

    scenes = []
    # adegan pembuka oleh Host
    scenes.append(
        {"speaker": "Host", "text": article["title"], "background": "studio"}
    )
    for s in sentences[: max_scenes - 1]:
        scenes.append({"speaker": "Narator", "text": s, "background": "studio"})
    return {"title": article["title"], "scenes": scenes}


def _validate(scenario: dict, cfg: dict) -> dict:
    """Pastikan struktur benar & batasi jumlah adegan."""
    scenes = scenario.get("scenes") or []
    clean = []
    for sc in scenes:
        text = (sc.get("text") or "").strip()
        if not text:
            continue
        clean.append(
            {
                "speaker": sc.get("speaker", "Narator") or "Narator",
                "text": text,
                "background": (sc.get("background") or "studio").strip().lower(),
            }
        )
    clean = clean[: cfg["script"]["max_scenes"]]
    return {"title": scenario.get("title", "Berita"), "scenes": clean}


def generate_script(cfg: dict, article: dict) -> dict:
    scenario = None
    if cfg["script"].get("use_ollama"):
        scenario = _via_ollama(cfg, article)
    if not scenario or not scenario.get("scenes"):
        scenario = _fallback(cfg, article)
    scenario = _validate(scenario, cfg)
    log.info("Skenario: %d adegan", len(scenario["scenes"]))
    return scenario


if __name__ == "__main__":
    cfg = load_config()
    demo = {
        "title": "Contoh Berita Banjir di Jakarta",
        "summary": (
            "Banjir melanda beberapa wilayah Jakarta pada pagi hari. "
            "Ketinggian air mencapai satu meter di sejumlah titik. "
            "Warga dievakuasi ke tempat yang lebih aman. "
            "Pemerintah daerah mengerahkan tim untuk membantu korban."
        ),
    }
    print(json.dumps(generate_script(cfg, demo), ensure_ascii=False, indent=2))
