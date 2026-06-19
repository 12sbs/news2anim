"""Buat beberapa karakter pembawa berita yang BERVARIASI + varian background.

Tiap video bisa tampil beda: rambut, bentuk wajah, warna kulit, baju, dan dasi
berbeda. Semua mengikuti konvensi lipsync news2anim:

  assets/characters/<nama>/body.png       (kanvas 600x800, transparan)
  assets/characters/<nama>/mouth_A..H,X.png (kanvas SAMA, pusat mulut 300,430)

Background varian (dipilih acak per video oleh render._find_background):
  assets/backgrounds/studio_*.png         (1280x720)

Karakter 'host' bawaan TIDAK ditimpa. Jalankan:
  python assets/make_variety.py
Lalu (opsional) daftarkan di config character.variants, atau biarkan [] supaya
semua folder ber-body.png otomatis dipakai.
"""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
CHARS = HERE / "characters"
BG = HERE / "backgrounds"

CW, CH = 600, 800          # kanvas karakter (HARUS sama dgn host bawaan)
MX, MY = 300, 430          # pusat mulut (HARUS sama agar lipsync pas)


# --------------------------------------------------------------- bentuk mulut
def make_mouths(char_dir: Path,
                lip=(170, 70, 70, 255),
                inner=(110, 40, 45, 255),
                teeth=(250, 250, 250, 255)) -> None:
    def closed(d):   # A - tutup (M B P)
        d.line([MX - 35, MY, MX + 35, MY], fill=lip, width=8)

    def slight(d):   # B - sedikit buka
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

    def pucker(d):   # F - mengerucut (U W)
        d.ellipse([MX - 14, MY - 10, MX + 14, MY + 20], fill=inner)
        d.ellipse([MX - 14, MY - 10, MX + 14, MY + 20], outline=lip, width=7)

    def fv(d):       # G - F V
        d.line([MX - 30, MY + 6, MX + 30, MY + 6], fill=lip, width=8)
        d.rectangle([MX - 24, MY - 6, MX + 24, MY + 2], fill=teeth)

    def l_shape(d):  # H - L
        d.ellipse([MX - 28, MY - 12, MX + 28, MY + 26], fill=inner)
        d.polygon([(MX, MY - 8), (MX - 8, MY + 16), (MX + 8, MY + 16)],
                  fill=(220, 120, 120, 255))

    def rest(d):     # X - istirahat
        d.line([MX - 30, MY, MX + 30, MY], fill=lip, width=6)

    shapes = {"A": closed, "B": slight, "C": open_mid, "D": open_wide,
              "E": round_o, "F": pucker, "G": fv, "H": l_shape, "X": rest}
    for name, fn in shapes.items():
        img = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
        fn(ImageDraw.Draw(img))
        img.save(char_dir / f"mouth_{name}.png")


# --------------------------------------------------------------- gambar tubuh
def _draw_hair_back(d, style, color):
    """Massa rambut di BELAKANG kepala (digambar sebelum kepala)."""
    if style == "bob":
        d.ellipse([185, 200, 415, 540], fill=color)
    elif style == "afro":
        d.ellipse([168, 158, 432, 472], fill=color)
    elif style == "ponytail":
        d.ellipse([205, 185, 395, 360], fill=color)        # sanggul atas
        d.ellipse([392, 250, 452, 520], fill=color)        # ekor kuda (samping)


def _draw_hair(d, style, color):
    if style == "side":
        d.pieslice([195, 175, 405, 360], start=180, end=360, fill=color)
    elif style == "short":
        d.pieslice([200, 185, 400, 330], start=180, end=360, fill=color)
        d.rectangle([200, 250, 220, 360], fill=color)   # cambang
        d.rectangle([380, 250, 400, 360], fill=color)
    elif style == "spiky":
        for x in range(205, 400, 26):
            d.polygon([(x, 250), (x + 13, 165), (x + 26, 250)], fill=color)
        d.pieslice([200, 200, 400, 320], start=180, end=360, fill=color)
    elif style == "bob":   # rambut panjang: poni + helai membingkai wajah
        d.pieslice([195, 200, 405, 330], start=180, end=360, fill=color)
        d.rectangle([188, 290, 232, 540], fill=color)   # helai kiri
        d.rectangle([368, 290, 412, 540], fill=color)   # helai kanan
    elif style == "curly":
        for cx, cy in [(220, 230), (255, 200), (300, 188), (345, 200), (380, 230),
                       (210, 270), (390, 270)]:
            d.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], fill=color)
    elif style == "bald":
        d.arc([220, 210, 380, 360], start=200, end=340, fill=color, width=6)
    elif style == "afro":
        d.pieslice([200, 200, 400, 330], start=180, end=360, fill=color)  # poni depan
    elif style == "ponytail":
        d.pieslice([205, 195, 395, 322], start=180, end=360, fill=color)
    elif style == "buzz":
        lighter = tuple(min(255, c + 25) for c in color[:3]) + (255,)
        d.pieslice([206, 205, 394, 318], start=180, end=360, fill=lighter)
    elif style == "wavy":
        d.pieslice([200, 190, 400, 320], start=180, end=360, fill=color)
        for cx in range(212, 392, 30):                       # gelombang di tepi poni
            d.ellipse([cx - 16, 250, cx + 16, 290], fill=color)


def make_body(char_dir: Path, spec: dict) -> None:
    img = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin = spec["skin"]
    shirt = spec["shirt"]
    hair_color = spec["hair_color"]

    # rambut belakang (bob/afro/ponytail) digambar dulu agar di belakang kepala
    _draw_hair_back(d, spec["hair"], hair_color)

    # tubuh / baju
    d.rounded_rectangle([180, 520, 420, 800], radius=60, fill=shirt)
    # kerah V putih
    d.polygon([(300, 520), (250, 640), (300, 600)], fill=(235, 235, 240, 255))
    d.polygon([(300, 520), (350, 640), (300, 600)], fill=(215, 215, 222, 255))
    # dasi atau blus
    if spec.get("tie"):
        d.polygon([(300, 540), (286, 560), (300, 720), (314, 560)], fill=spec["tie"])
        d.polygon([(292, 540), (300, 552), (308, 540)], fill=spec["tie"])
    # leher
    d.rectangle([270, 470, 330, 545], fill=skin)

    # kepala (bentuk wajah)
    face = spec["face"]
    if face == "oval":
        d.ellipse([200, 200, 400, 470], fill=skin)
    elif face == "round":
        d.ellipse([195, 210, 405, 462], fill=skin)
    elif face == "square":
        d.rounded_rectangle([206, 205, 394, 470], radius=55, fill=skin)

    # rambut depan
    _draw_hair(d, spec["hair"], hair_color)

    # mata
    d.ellipse([255, 320, 285, 350], fill=(255, 255, 255, 255))
    d.ellipse([315, 320, 345, 350], fill=(255, 255, 255, 255))
    d.ellipse([265, 328, 281, 344], fill=(30, 30, 30, 255))
    d.ellipse([325, 328, 341, 344], fill=(30, 30, 30, 255))
    # alis
    d.line([252, 312, 288, 308], fill=hair_color, width=5)
    d.line([312, 308, 348, 312], fill=hair_color, width=5)
    # hidung
    nose = tuple(max(0, c - 35) for c in skin[:3]) + (255,)
    d.line([300, 350, 300, 395], fill=nose, width=4)

    img.save(char_dir / "body.png")


# karakter: skin, hair_color, hair, face, shirt, tie(None=blus)
VARIANTS = {
    "alex":  dict(skin=(245, 205, 175, 255), hair_color=(60, 40, 30, 255),
                  hair="side",  face="oval",   shirt=(40, 90, 160, 255),  tie=(190, 40, 45, 255)),
    "deni":  dict(skin=(210, 165, 120, 255), hair_color=(25, 22, 20, 255),
                  hair="short", face="square", shirt=(70, 72, 80, 255),   tie=(45, 110, 185, 255)),
    "rama":  dict(skin=(160, 110, 78, 255),  hair_color=(20, 18, 18, 255),
                  hair="spiky", face="oval",   shirt=(45, 48, 56, 255),   tie=(210, 170, 60, 255)),
    "maya":  dict(skin=(245, 210, 185, 255), hair_color=(70, 45, 30, 255),
                  hair="curly", face="round",  shirt=(30, 120, 120, 255), tie=None),
    "sara":  dict(skin=(230, 185, 150, 255), hair_color=(20, 18, 22, 255),
                  hair="bob",   face="oval",   shirt=(130, 45, 70, 255),  tie=None),
    "budi":  dict(skin=(205, 158, 112, 255), hair_color=(35, 30, 28, 255),
                  hair="bald",  face="oval",   shirt=(30, 95, 70, 255),   tie=(30, 50, 110, 255)),
    "nina":  dict(skin=(245, 212, 188, 255), hair_color=(40, 28, 24, 255),
                  hair="ponytail", face="round", shirt=(95, 55, 130, 255), tie=None),
    "tony":  dict(skin=(214, 170, 128, 255), hair_color=(22, 20, 20, 255),
                  hair="buzz",  face="square", shirt=(225, 228, 235, 255), tie=(25, 25, 30, 255)),
    "lina":  dict(skin=(150, 102, 70, 255),  hair_color=(18, 16, 16, 255),
                  hair="afro",  face="oval",   shirt=(200, 110, 40, 255),  tie=None),
    "yusuf": dict(skin=(235, 195, 160, 255), hair_color=(45, 32, 26, 255),
                  hair="wavy",  face="oval",   shirt=(70, 120, 175, 255),  tie=(120, 40, 55, 255)),
}


# ----------------------------------------------------------- varian background
def _studio(name, top, bottom, desk, screen, banner):
    W, H = 1280, 720
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    for y in range(H):
        r = top[0] + (bottom[0] - top[0]) * y // H
        g = top[1] + (bottom[1] - top[1]) * y // H
        b = top[2] + (bottom[2] - top[2]) * y // H
        d.line([(0, y), (W, y)], fill=(r, g, b))
    d.rectangle([0, 600, W, H], fill=desk)                                # meja
    d.rounded_rectangle([840, 120, 1180, 360], 20, fill=screen)           # layar
    d.rectangle([60, 60, 380, 110], fill=banner)                          # banner
    img.save(BG / f"{name}.png")
    print("dibuat:", BG / f"{name}.png")


def make_studio_variants():
    _studio("studio_blue",  (24, 32, 58), (44, 58, 96),  (58, 40, 36), (20, 60, 110), (200, 40, 40))
    _studio("studio_warm",  (52, 36, 30), (90, 60, 44),  (60, 42, 34), (120, 70, 30), (210, 150, 40))
    _studio("studio_green", (20, 40, 34), (32, 70, 58),  (40, 46, 42), (20, 90, 80),  (40, 160, 110))
    _studio("studio_dark",  (16, 18, 26), (30, 34, 50),  (34, 30, 32), (40, 70, 120), (200, 50, 60))


if __name__ == "__main__":
    BG.mkdir(parents=True, exist_ok=True)
    for name, spec in VARIANTS.items():
        cdir = CHARS / name
        cdir.mkdir(parents=True, exist_ok=True)
        make_body(cdir, spec)
        make_mouths(cdir)
        print("dibuat karakter:", cdir)
    make_studio_variants()
    print("\nSelesai. %d karakter + 4 varian studio dibuat." % len(VARIANTS))
    print("Uji: python src/render.py  (atau biarkan service memakainya otomatis)")
