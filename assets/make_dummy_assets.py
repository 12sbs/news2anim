"""Buat karakter dummy + background untuk uji coba.

Menghasilkan:
  assets/characters/host/body.png          (kanvas 600x800, transparan)
  assets/characters/host/mouth_A..H,X.png   (kanvas SAMA, hanya mulut)
  assets/backgrounds/studio.png             (1280x720)

Konvensi: tiap mouth_*.png punya ukuran kanvas SAMA dengan body.png,
mulut digambar di koordinat yang sama, sisanya transparan. Jadi saat
render cukup ditumpuk di posisi & skala yang sama dengan body.

Jalankan:  python assets/make_dummy_assets.py
Ganti file-file ini dengan karaktermu sendiri (ikuti konvensi yang sama).
"""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
CHAR = HERE / "characters" / "host"
BG = HERE / "backgrounds"

CW, CH = 600, 800          # kanvas karakter
# Titik pusat mulut pada kanvas karakter
MX, MY = 300, 430


def _new_canvas():
    return Image.new("RGBA", (CW, CH), (0, 0, 0, 0))


def make_body():
    img = _new_canvas()
    d = ImageDraw.Draw(img)
    # tubuh (baju)
    d.rounded_rectangle([180, 520, 420, 800], radius=60, fill=(40, 90, 160, 255))
    d.polygon([(300, 520), (250, 800), (350, 800)], fill=(230, 230, 235, 255))  # dasi/kemeja
    # leher
    d.rectangle([270, 470, 330, 540], fill=(240, 200, 170, 255))
    # kepala
    d.ellipse([200, 200, 400, 470], fill=(245, 205, 175, 255))
    # rambut
    d.pieslice([195, 175, 405, 360], start=180, end=360, fill=(50, 35, 30, 255))
    # mata
    d.ellipse([255, 320, 285, 350], fill=(255, 255, 255, 255))
    d.ellipse([315, 320, 345, 350], fill=(255, 255, 255, 255))
    d.ellipse([265, 328, 281, 344], fill=(30, 30, 30, 255))
    d.ellipse([325, 328, 341, 344], fill=(30, 30, 30, 255))
    # alis
    d.line([252, 312, 288, 308], fill=(50, 35, 30, 255), width=5)
    d.line([312, 308, 348, 312], fill=(50, 35, 30, 255), width=5)
    # hidung
    d.line([300, 350, 300, 395], fill=(210, 170, 140, 255), width=4)
    img.save(CHAR / "body.png")
    print("dibuat:", CHAR / "body.png")


def _mouth_canvas(draw_fn):
    img = _new_canvas()
    d = ImageDraw.Draw(img)
    draw_fn(d)
    return img


def make_mouths():
    lip = (170, 70, 70, 255)
    inner = (110, 40, 45, 255)
    teeth = (250, 250, 250, 255)

    def closed(d):  # A - tutup (M B P)
        d.line([MX - 35, MY, MX + 35, MY], fill=lip, width=8)

    def slight(d):  # B - sedikit buka
        d.ellipse([MX - 30, MY - 8, MX + 30, MY + 18], fill=inner)
        d.rectangle([MX - 26, MY - 4, MX + 26, MY + 4], fill=teeth)

    def open_mid(d):  # C - buka sedang
        d.ellipse([MX - 34, MY - 16, MX + 34, MY + 30], fill=inner)
        d.rectangle([MX - 28, MY - 12, MX + 28, MY - 4], fill=teeth)

    def open_wide(d):  # D - buka lebar (A)
        d.ellipse([MX - 36, MY - 26, MX + 36, MY + 44], fill=inner)
        d.rectangle([MX - 30, MY - 22, MX + 30, MY - 12], fill=teeth)

    def round_o(d):  # E - bulat (O)
        d.ellipse([MX - 22, MY - 18, MX + 22, MY + 30], fill=inner)
        d.ellipse([MX - 22, MY - 18, MX + 22, MY + 30], outline=lip, width=6)

    def pucker(d):  # F - mengerucut (U W)
        d.ellipse([MX - 14, MY - 10, MX + 14, MY + 20], fill=inner)
        d.ellipse([MX - 14, MY - 10, MX + 14, MY + 20], outline=lip, width=7)

    def fv(d):  # G - F V (gigi di bibir)
        d.line([MX - 30, MY + 6, MX + 30, MY + 6], fill=lip, width=8)
        d.rectangle([MX - 24, MY - 6, MX + 24, MY + 2], fill=teeth)

    def l_shape(d):  # H - L
        d.ellipse([MX - 28, MY - 12, MX + 28, MY + 26], fill=inner)
        d.polygon([(MX, MY - 8), (MX - 8, MY + 16), (MX + 8, MY + 16)], fill=(220, 120, 120, 255))

    def rest(d):  # X - istirahat
        d.line([MX - 30, MY, MX + 30, MY], fill=lip, width=6)

    shapes = {
        "A": closed, "B": slight, "C": open_mid, "D": open_wide,
        "E": round_o, "F": pucker, "G": fv, "H": l_shape, "X": rest,
    }
    for name, fn in shapes.items():
        img = _mouth_canvas(fn)
        out = CHAR / f"mouth_{name}.png"
        img.save(out)
    print("dibuat: 9 bentuk mulut di", CHAR)


def make_background():
    W, H = 1280, 720
    img = Image.new("RGB", (W, H), (28, 34, 52))
    d = ImageDraw.Draw(img)
    # gradien sederhana
    for y in range(H):
        c = int(28 + (y / H) * 30)
        d.line([(0, y), (W, y)], fill=(c, c + 6, c + 24))
    # meja studio
    d.rectangle([0, 600, W, H], fill=(60, 40, 35))
    # panel "layar berita"
    d.rounded_rectangle([840, 120, 1180, 360], radius=20, fill=(20, 60, 110))
    d.rectangle([60, 60, 380, 110], fill=(200, 40, 40))
    img.save(BG / "studio.png")
    print("dibuat:", BG / "studio.png")


if __name__ == "__main__":
    CHAR.mkdir(parents=True, exist_ok=True)
    BG.mkdir(parents=True, exist_ok=True)
    make_body()
    make_mouths()
    make_background()
    print("\nSelesai. Jalankan: python src/render.py untuk uji satu adegan.")
