"""Thumbnail YouTube otomatis (1280x720) — hanya PIL (sudah dependency).

Pipeline: gambar dasar -> gelapkan -> band gelap + judul tebal -> logo channel.
Gambar dasar diambil dari (urut prioritas):
  1. Gambar AI sesuai isi berita (ai_image.generate_image).
  2. Frame paling terang dari video final.
  3. Background default.

Semua kegagalan -> return None (pemanggil melewati set-thumbnail, tidak memblok).
Output: workdir/thumbnail.jpg, dijamin < 2 MB (batas YouTube).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from utils import log, resolve

# probe font sederhana (tak impor render -> hindari muat moviepy saat thumbnail)
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
]

_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


def _find_font(cfg: dict) -> str | None:
    cfgfont = cfg.get("thumbnail", {}).get("font") or ""
    if cfgfont and Path(cfgfont).exists():
        return cfgfont
    for c in _FONT_CANDIDATES:
        if Path(c).exists():
            return c
    return None


def _base_image(cfg, merged, final_video, workdir, W, H) -> Path | None:
    """Sumber gambar dasar thumbnail."""
    tn = cfg.get("thumbnail", {})
    source = tn.get("source", "ai")

    # 1) gambar AI dari judul/isi berita
    if source == "ai" and cfg.get("ai_image", {}).get("enabled", False):
        try:
            from ai_image import generate_image

            prompt_text = merged.get("title", "") or merged.get("summary", "")[:200]
            out = generate_image(cfg, prompt_text, workdir / "thumb_bg.png", W, H)
            if out:
                return out
        except Exception as e:  # noqa: BLE001
            log.warning("Thumbnail: gambar AI gagal (%s).", e)

    # 2) frame paling terang dari video final
    if final_video and Path(final_video).exists():
        try:
            from validate import _frame_stats, _grab_frame, probe_duration

            dur = probe_duration(Path(final_video)) or 0
            best_png, best_mean = None, -1.0
            for frac in (0.2, 0.45, 0.7, 0.9):
                png = _grab_frame(Path(final_video), max(0.0, dur * frac))
                if png:
                    stats = _frame_stats(png)
                    if stats and stats[0] > best_mean:
                        best_mean, best_png = stats[0], png
            if best_png:
                out = workdir / "thumb_bg.png"
                out.write_bytes(best_png)
                return out
        except Exception as e:  # noqa: BLE001
            log.warning("Thumbnail: ambil frame gagal (%s).", e)

    # 3) background default
    default = resolve(cfg["video"]["background_default"])
    return default if default.exists() else None


def _draw_headline(img, text: str, cfg, W: int, H: int) -> None:
    from PIL import Image, ImageDraw, ImageFont

    tn = cfg.get("thumbnail", {})
    max_chars = int(tn.get("headline_max_chars", 60))
    text = (text or "WORLD NEWS").strip()[: max_chars * 2]

    font_path = _find_font(cfg)
    size = int(H * 0.10)  # ~72px pada 720p
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()

    # bungkus jadi <= 2-3 baris
    wrap_w = max(10, int(max_chars * 0.55))
    lines = textwrap.wrap(text, width=wrap_w)[:3]

    draw = ImageDraw.Draw(img)
    line_h = int(size * 1.2)
    block_h = line_h * len(lines)
    margin = int(W * 0.04)
    y0 = H - block_h - int(H * 0.06)

    # band gelap semi-transparan di belakang teks (legibilitas)
    band = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    bd.rectangle(
        [0, y0 - int(line_h * 0.4), W, H], fill=(0, 0, 0, 150)
    )
    img.alpha_composite(band)

    draw = ImageDraw.Draw(img)
    y = y0
    for line in lines:
        draw.text(
            (margin, y), line, font=font, fill=(255, 255, 255, 255),
            stroke_width=max(2, size // 18), stroke_fill=(0, 0, 0, 255),
        )
        y += line_h


def _paste_logo(img, cfg, W: int, H: int) -> None:
    tn = cfg.get("thumbnail", {})
    logo = tn.get("logo") or cfg.get("video", {}).get("logo")
    if not logo:
        return
    lp = resolve(logo)
    if not lp.exists():
        return
    try:
        from PIL import Image

        with Image.open(lp).convert("RGBA") as lim:
            target_h = max(1, int(H * 0.12))
            ratio = target_h / lim.height
            target_w = max(1, int(lim.width * ratio))
            lim = lim.resize((target_w, target_h))
            margin = int(W * 0.02)
            img.alpha_composite(lim, (W - target_w - margin, margin))
    except Exception as e:  # noqa: BLE001
        log.warning("Thumbnail: logo dilewati (%s).", e)


def generate_thumbnail(cfg, merged, scenario, final_video, workdir) -> Path | None:
    """Buat thumbnail.jpg 1280x720. Return path atau None bila gagal."""
    try:
        from PIL import Image, ImageEnhance
    except Exception as e:  # noqa: BLE001
        log.warning("Thumbnail: PIL tidak tersedia (%s).", e)
        return None

    tn = cfg.get("thumbnail", {})
    W = int(tn.get("width", 1280))
    H = int(tn.get("height", 720))
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    base = _base_image(cfg, merged, final_video, workdir, W, H)
    if base is None:
        log.warning("Thumbnail: tidak ada gambar dasar -> dilewati.")
        return None

    try:
        img = Image.open(base).convert("RGBA").resize((W, H))
        # sedikit gelapkan agar teks kontras
        img = ImageEnhance.Brightness(img).enhance(0.82).convert("RGBA")

        headline = (scenario or {}).get("title") or merged.get("title", "")
        _draw_headline(img, headline, cfg, W, H)
        _paste_logo(img, cfg, W, H)

        out = workdir / "thumbnail.jpg"
        rgb = img.convert("RGB")
        quality = 90
        rgb.save(out, "JPEG", quality=quality)
        # jaga < 2MB
        while out.stat().st_size > _MAX_BYTES and quality > 40:
            quality -= 10
            rgb.save(out, "JPEG", quality=quality)
        log.info("Thumbnail dibuat: %s (%.0f KB)", out.name, out.stat().st_size / 1024)
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("Thumbnail gagal dibuat (%s).", e)
        return None


if __name__ == "__main__":
    from utils import load_config

    cfg = load_config()
    wd = resolve("output/_thumb_test")
    merged = {
        "title": "Tehran selling deal with US as victory but for Iranians it was necessity",
        "summary": "Iran and the US signed a memorandum of understanding.",
    }
    out = generate_thumbnail(cfg, merged, {"title": merged["title"]}, None, wd)
    print("Hasil:", out)
