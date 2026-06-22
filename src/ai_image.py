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

# batas panjang prompt akhir (deskripsi detail kejadian + gaya animasi 2D)
_PROMPT_MAXLEN = 480


def _refine_prompt(cfg: dict, scene_text: str) -> str | None:
    """Ringkas teks adegan menjadi deskripsi visual singkat memakai Ollama."""
    sc = cfg["script"]
    system = (
        "You turn a news sentence into a VIVID, DETAILED visual scene description "
        "for an image generator. Capture the SPECIFICS of THIS event so the image "
        "matches what is being discussed: the kind of location/setting, key objects "
        "and vehicles, the number and role of people (e.g. firefighters, soldiers, "
        "crowd, officials), their actions, weather, time of day, and overall mood. "
        "Use only generic descriptors for people (their role/clothing), NEVER the "
        "names or faces of real, identifiable individuals; no on-screen text, logos, "
        "or captions. One rich phrase, 25-40 words. Output ONLY the description."
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


def build_prompt(cfg: dict, scene_text: str, style: str | None = None) -> str:
    """Gabung deskripsi visual + gaya menjadi prompt akhir.

    style: bila diberikan (mis. dipilih per video dari daftar `styles`), dipakai
    menggantikan cfg.ai_image.style. Bila None -> jatuh ke konfigurasi.
    """
    ai = cfg.get("ai_image", {})
    base = None
    if ai.get("refine_prompt", True) and cfg["script"].get("use_ollama"):
        base = _refine_prompt(cfg, scene_text)
    if not base:
        base = scene_text.strip()
    if not style:
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
    cfg: dict, scene_text: str, out_path: Path, width: int, height: int,
    style: str | None = None,
) -> Path | None:
    """Buat 1 gambar AI dari teks adegan. Sukses -> path, gagal -> None.

    style: override gaya (dipilih per video oleh pemanggil); None -> dari config.
    """
    ai = cfg.get("ai_image", {})
    if not ai.get("enabled", False):
        return None
    if ai.get("provider", "pollinations") != "pollinations":
        log.warning("Provider gambar '%s' belum didukung. Lewati.", ai.get("provider"))
        return None

    prompt = build_prompt(cfg, scene_text, style=style)
    # seed dasar deterministik dari prompt -> percobaan ke-1 idempoten saat re-run.
    base_seed = int(hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:8], 16)
    # NOTE: param 'model' kini praktis diabaikan Pollinations (selalu melayani
    # 'sana'); tetap dikirim untuk kompatibilitas bila mereka memulihkannya.
    # NOTE: negative_prompt nyaris tak berpengaruh pada model 'sana'; pengungkit
    # mutu nyata adalah SEED -> tiap retry reroll seed agar komposisi berbeda
    # (mengatasi figur tak komplit/anatomi rusak pada seed yang kebetulan buruk).

    def _build_url(seed: int) -> str:
        params = [
            f"width={width}",
            f"height={height}",
            f"model={ai.get('model', 'flux')}",
            "nologo=true",
            f"seed={seed}",
        ]
        if ai.get("enhance", True):
            params.append("enhance=true")  # Pollinations sempurnakan prompt otomatis
        quality = ai.get("quality")
        if quality:
            params.append(f"quality={quote(str(quality))}")  # high -> tajam/detail
        neg = ai.get("negative_prompt")
        if neg:
            params.append(f"negative_prompt={quote(str(neg))}")  # buang artefak
        if ai.get("private", True):
            params.append("nofeed=true")  # gambar berita tidak masuk feed publik
        return "https://image.pollinations.ai/prompt/" + quote(prompt) + "?" + "&".join(params)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = ai.get("timeout_sec", 60)
    retries = int(ai.get("retries", 2))

    for attempt in range(1, retries + 1):
        # percobaan 1 pakai seed dasar; berikutnya reroll seed (offset prima)
        seed = base_seed + (attempt - 1) * 100003
        url = _build_url(seed)
        try:
            log.info("Gambar AI [%d/%d] seed=%d: %s", attempt, retries, seed, prompt[:60])
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
