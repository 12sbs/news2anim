"""Buat overlay partikel/cahaya (bokeh) transparan untuk animasi background.

Menghasilkan assets/overlays/particles.png (1536x864, RGBA) berisi titik-titik
cahaya lembut. Di render, overlay ini ditumpuk di atas background lalu di-drift
pelan (lihat render._overlay_clip) sehingga latar terasa hidup.

Ganti file ini dengan bokeh/efek buatanmu kapan saja (nama file sama).
Jalankan:  python assets/make_overlay.py
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent / "overlays"
W, H = 1536, 864


def make_particles(seed: int = 7) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # warna cahaya: putih hangat & sedikit biru, agar netral di banyak background
    palette = [(255, 244, 214), (255, 255, 255), (210, 226, 255)]
    for _ in range(60):
        r = rnd.randint(8, 46)
        cx = rnd.randint(0, W)
        cy = rnd.randint(0, H)
        col = rnd.choice(palette)
        alpha = rnd.randint(40, 130)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*col, alpha))
    # blur agar jadi bokeh lembut (bukan lingkaran tajam)
    img = img.filter(ImageFilter.GaussianBlur(10))
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    make_particles().save(OUT / "particles.png")
    print("dibuat:", OUT / "particles.png")
