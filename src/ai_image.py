"""Gambar AI untuk b-roll adegan reenactment (provider gratis: Pollinations/Flux).

Dipakai render.py: adegan reenactment menampilkan gambar yang dibuat AI sesuai
isi naskah, bukan karakter. Bila gagal (jaringan/timeout/hasil rusak) -> None,
dan pemanggil jatuh ke background bertema (degradasi anggun).

Tidak butuh API key. Endpoint: https://image.pollinations.ai/prompt/<prompt>
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from urllib.parse import quote

import requests

from utils import log

# kata visual generik agar prompt fokus ke gambar (bukan teks berita panjang)
_PROMPT_MAXLEN = 320


def _refine_prompt(cfg: dict, scene_text: str) -> str | None:
    """Ringkas teks adegan menjadi deskripsi visual singkat memakai Ollama."""
    sc = cfg["script"]
    system = (
        "Turn a news sentence into a SHORT visual scene description for an image "
        "generator. Describe ONLY what is literally seen (place, people, action, "
        "time of day). No names of real people, no text/logos, no captions. "
        "One concise phrase, max 25 words. Output ONLY the description."
    )
    payload = {
        "model": sc["model"],
        "stream": False,
        "options": {"temperature": 0.4},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": scene_text[:600]},
        ],
    }
    try:
        r = requests.post(f"{sc['ollama_url']}/api/chat", json=payload, timeout=60)
        r.raise_for_status()
        out = r.json()["message"]["content"].strip()
        out = out.replace("\n", " ").strip(' "')
        return out or None
    except Exception as e:  # noqa: BLE001
        log.warning("Refine prompt gambar gagal (%s). Pakai teks adegan.", e)
        return None


def build_prompt(cfg: dict, scene_text: str) -> str:
    """Gabung deskripsi visual + gaya menjadi prompt akhir."""
    ai = cfg.get("ai_image", {})
    base = None
    if ai.get("refine_prompt", True) and cfg["script"].get("use_ollama"):
        base = _refine_prompt(cfg, scene_text)
    if not base:
        base = scene_text.strip()
    style = ai.get("style", "cinematic, photorealistic")
    prompt = f"{base}. {style}"
    return prompt[:_PROMPT_MAXLEN]


def _is_valid_image(data: bytes, min_std: float = 4.0) -> bool:
    """Pastikan byte adalah gambar valid & tidak polos/blank."""
    try:
        from PIL import Image, ImageStat

        im = Image.open(io.BytesIO(data))
        im.verify()  # cek integritas
        im = Image.open(io.BytesIO(data)).convert("L")
        if min(im.size) < 64:
            return False
        std = ImageStat.Stat(im).stddev[0]
        return std >= min_std
    except Exception:  # noqa: BLE001
        return False


def generate_image(
    cfg: dict, scene_text: str, out_path: Path, width: int, height: int
) -> Path | None:
    """Buat 1 gambar AI dari teks adegan. Sukses -> path, gagal -> None."""
    ai = cfg.get("ai_image", {})
    if not ai.get("enabled", False):
        return None
    if ai.get("provider", "pollinations") != "pollinations":
        log.warning("Provider gambar '%s' belum didukung. Lewati.", ai.get("provider"))
        return None

    prompt = build_prompt(cfg, scene_text)
    # seed deterministik dari prompt -> hasil stabil & idempoten saat retry
    seed = int(hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:8], 16)
    url = (
        f"https://image.pollinations.ai/prompt/{quote(prompt)}"
        f"?width={width}&height={height}&model={ai.get('model', 'flux')}"
        f"&nologo=true&seed={seed}"
    )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = ai.get("timeout_sec", 60)
    retries = int(ai.get("retries", 2))

    for attempt in range(1, retries + 1):
        try:
            log.info("Gambar AI [%d/%d]: %s", attempt, retries, prompt[:70])
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            if _is_valid_image(r.content):
                out_path.write_bytes(r.content)
                return out_path
            log.warning("Gambar AI tidak valid/blank (percobaan %d).", attempt)
        except Exception as e:  # noqa: BLE001
            log.warning("Gambar AI gagal (percobaan %d): %s", attempt, e)
    return None


if __name__ == "__main__":
    from utils import load_config, resolve

    cfg = load_config()
    out = generate_image(
        cfg,
        "Crowds gathered in the city square as the protest grew into the evening.",
        resolve("output/_ai_test.png"),
        1280,
        720,
    )
    print("Hasil:", out)
