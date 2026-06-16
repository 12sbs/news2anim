"""Buat pustaka background bertema (flat-design) untuk variasi visual.

Menghasilkan assets/backgrounds/<tema>.png (1280x720) untuk kata kunci yang
dipakai script_gen._guess_background: studio, city, war, flood, fire,
protest, election, economy, court, map.

Ganti dengan gambar/foto buatanmu sendiri kapan saja (nama file sama).
Jalankan:  python assets/make_backgrounds.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

BG = Path(__file__).resolve().parent / "backgrounds"
W, H = 1280, 720


def _canvas(top, bottom):
    """Kanvas dengan gradien vertikal."""
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    for y in range(H):
        r = top[0] + (bottom[0] - top[0]) * y // H
        g = top[1] + (bottom[1] - top[1]) * y // H
        b = top[2] + (bottom[2] - top[2]) * y // H
        d.line([(0, y), (W, y)], fill=(r, g, b))
    return img, d


def _save(img, name):
    img.save(BG / f"{name}.png")
    print("dibuat:", name)


def studio():
    img, d = _canvas((28, 34, 52), (40, 52, 86))
    d.rectangle([0, 600, W, H], fill=(60, 40, 35))            # meja
    d.rounded_rectangle([840, 120, 1180, 360], 20, fill=(20, 60, 110))  # layar
    d.rectangle([60, 60, 380, 110], fill=(200, 40, 40))       # banner merah
    _save(img, "studio")


def city():
    img, d = _canvas((40, 52, 90), (120, 130, 160))
    # siluet gedung
    import math
    x = 0
    cols = [(30, 40, 70), (45, 55, 85), (20, 28, 55)]
    i = 0
    while x < W:
        bw = 70 + (i * 37) % 90
        bh = 180 + (i * 53) % 320
        d.rectangle([x, H - bh - 120, x + bw, H - 120], fill=cols[i % 3])
        # jendela
        for wy in range(H - bh - 110, H - 130, 34):
            for wx in range(x + 8, x + bw - 8, 26):
                if (wx + wy + i) % 3:
                    d.rectangle([wx, wy, wx + 12, wy + 18], fill=(220, 210, 140))
        x += bw + 14
        i += 1
    d.rectangle([0, H - 120, W, H], fill=(25, 28, 40))        # jalan
    _save(img, "city")


def war():
    img, d = _canvas((50, 40, 38), (20, 18, 22))
    # asap/awan gelap
    for cx, cy, r in [(300, 200, 140), (700, 150, 180), (1000, 240, 150)]:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(70, 60, 58))
    d.rectangle([0, 560, W, H], fill=(35, 30, 28))            # tanah
    # reruntuhan (balok)
    for bx in range(80, W, 220):
        d.polygon([(bx, H), (bx + 40, 600), (bx + 120, H)], fill=(55, 48, 45))
    _save(img, "war")


def flood():
    img, d = _canvas((90, 110, 130), (40, 70, 110))
    d.rectangle([0, 460, W, H], fill=(60, 95, 140))           # air
    for wy in range(480, H, 40):                              # riak
        d.line([(0, wy), (W, wy)], fill=(80, 120, 165), width=3)
    # garis hujan
    for rx in range(0, W, 24):
        d.line([(rx, 0), (rx - 30, 460)], fill=(170, 190, 210), width=2)
    _save(img, "flood")


def fire():
    img, d = _canvas((60, 30, 20), (20, 12, 12))
    d.rectangle([0, 580, W, H], fill=(30, 22, 20))
    for fx in range(120, W, 200):                             # lidah api
        d.polygon([(fx, 600), (fx - 50, 600), (fx - 20, 430),
                   (fx + 10, 520), (fx + 30, 400), (fx + 55, 600)],
                  fill=(220, 120, 40))
        d.polygon([(fx, 600), (fx - 20, 600), (fx + 5, 500),
                   (fx + 20, 600)], fill=(250, 200, 80))
    _save(img, "fire")


def protest():
    img, d = _canvas((60, 66, 92), (95, 100, 120))
    d.rectangle([0, 520, W, H], fill=(45, 48, 60))            # jalan
    # kerumunan siluet
    for cx in range(40, W, 60):
        d.ellipse([cx, 470, cx + 44, 540], fill=(30, 33, 45))
        d.rectangle([cx + 8, 520, cx + 36, 620], fill=(30, 33, 45))
    # papan demo
    for sx in [200, 520, 860, 1080]:
        d.rectangle([sx, 360, sx + 110, 430], fill=(235, 230, 220))
        d.line([sx + 55, 430, sx + 55, 520], fill=(120, 90, 60), width=8)
    _save(img, "protest")


def election():
    img, d = _canvas((30, 50, 80), (60, 80, 120))
    d.rounded_rectangle([540, 300, 740, 480], 12, fill=(225, 225, 230))  # kotak suara
    d.rectangle([600, 290, 680, 320], fill=(180, 180, 190))
    d.polygon([(620, 250), (660, 250), (650, 300), (630, 300)], fill=(240, 240, 245))
    d.rectangle([60, 60, 360, 108], fill=(40, 110, 70))
    _save(img, "election")


def economy():
    img, d = _canvas((22, 40, 38), (30, 60, 56))
    base = H - 140
    vals = [120, 180, 150, 240, 300, 270, 360, 420]
    bw = 110
    for i, v in enumerate(vals):
        x = 120 + i * (bw + 20)
        d.rectangle([x, base - v, x + bw, base], fill=(60, 200, 150))
    # garis tren naik
    pts = [(120 + i * (bw + 20) + bw // 2, base - v) for i, v in enumerate(vals)]
    d.line(pts, fill=(240, 220, 90), width=6)
    d.line([0, base, W, base], fill=(120, 140, 135), width=3)
    _save(img, "economy")


def court():
    img, d = _canvas((45, 40, 55), (75, 68, 85))
    # pilar
    for px in range(120, W - 100, 180):
        d.rectangle([px, 160, px + 70, 560], fill=(210, 205, 200))
        d.rectangle([px - 12, 140, px + 82, 165], fill=(190, 185, 180))
    d.polygon([(W // 2 - 420, 160), (W // 2 + 420, 160), (W // 2, 60)],
              fill=(225, 220, 215))                           # atap segitiga
    d.rectangle([0, 560, W, H], fill=(50, 45, 55))
    _save(img, "court")


def world_map():
    img, d = _canvas((18, 30, 55), (30, 48, 80))
    # grid garis bujur/lintang
    for x in range(0, W, 80):
        d.line([(x, 0), (x, H)], fill=(40, 60, 95), width=1)
    for y in range(0, H, 80):
        d.line([(0, y), (W, y)], fill=(40, 60, 95), width=1)
    # benua abstrak (gumpalan)
    blobs = [(300, 300, 180, 120), (560, 250, 150, 200),
             (820, 360, 220, 140), (1050, 250, 120, 100)]
    for bx, by, bw, bh in blobs:
        d.ellipse([bx, by, bx + bw, by + bh], fill=(70, 130, 110))
    _save(img, "map")


if __name__ == "__main__":
    BG.mkdir(parents=True, exist_ok=True)
    studio(); city(); war(); flood(); fire()
    protest(); election(); economy(); court(); world_map()
    print("\nSelesai. Semua background bertema dibuat di", BG)
