"""Buat logo channel sederhana (assets/logo.png) — badge bulat 'N2A'.

Jalankan:  python assets/make_logo.py
Ganti dengan logo aslimu kapan saja (PNG transparan disarankan).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "logo.png"
SIZE = 256
RED = (200, 40, 30, 255)
WHITE = (255, 255, 255, 255)


def _font(size: int):
    for c in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def make_logo() -> Path:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([8, 8, SIZE - 8, SIZE - 8], fill=RED)
    d.ellipse([8, 8, SIZE - 8, SIZE - 8], outline=WHITE, width=8)
    text = "N2A"
    font = _font(96)
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((SIZE - tw) / 2 - box[0], (SIZE - th) / 2 - box[1]), text,
           font=font, fill=WHITE)
    img.save(OUT)
    return OUT


if __name__ == "__main__":
    print("Logo dibuat:", make_logo())
