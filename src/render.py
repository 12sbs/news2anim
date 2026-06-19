"""Render satu adegan menjadi klip video.

Dua jenis adegan:
- ANCHOR     : karakter pembawa berita + background + banner headline.
- REENACTMENT: b-roll layar-penuh (pemandangan/foto) TANPA karakter, hanya
               voice-over + subtitle. Memecah kebosanan -> retensi naik.

Semua background memakai efek Ken Burns (zoom pelan) agar terasa hidup.

Konvensi aset karakter:
- body.png    : tubuh+kepala (transparan)
- mouth_X.png : bentuk mulut, kanvas SAMA dgn body.png, sisanya transparan.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from moviepy import AudioFileClip, CompositeVideoClip, ImageClip
from PIL import Image


def _seed_int(seed) -> int:
    """Angka deterministik dari seed (str apa pun) -> idempoten lintas render."""
    return int(hashlib.sha1(str(seed).encode("utf-8")).hexdigest(), 16)

from lipsync import MOUTH_SHAPES, get_mouth_cues
from tts import synth
from utils import load_config, log, resolve


def _find_font(cfg: dict) -> str | None:
    cfgfont = cfg["video"].get("subtitle_font")
    if cfgfont and Path(cfgfont).exists():
        return cfgfont
    for c in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]:
        if Path(c).exists():
            return c
    return None


def _list_character_dirs(cfg: dict) -> list[Path]:
    """Daftar folder karakter valid (punya body.png)."""
    base = resolve("assets/characters")
    variants = cfg["character"].get("variants") or []
    dirs: list[Path] = []
    if variants:
        for v in variants:
            d = base / str(v)
            if (d / "body.png").exists():
                dirs.append(d)
    else:
        for d in sorted(base.glob("*")):
            if d.is_dir() and (d / "body.png").exists():
                dirs.append(d)
    if not dirs:
        dirs = [resolve(cfg["character"]["dir"])]
    return dirs


def pick_character_dir(cfg: dict, seed) -> Path:
    """Pilih folder karakter acak-deterministik dari seed (mis. headline).

    Konsisten utk semua adegan satu video, beragam antar video.
    """
    dirs = _list_character_dirs(cfg)
    return dirs[_seed_int(seed) % len(dirs)]


def _find_background(cfg: dict, keyword: str, workdir: Path,
                     allow_broll: bool = False, seed=None) -> Path:
    """Cari latar: (utk b-roll) foto artikel > assets/backgrounds/<keyword> > default.

    Bila ada beberapa varian (mis. studio.png, studio_blue.png, studio2.png),
    dipilih acak-deterministik dari seed -> background ikut berubah antar video.
    """
    # foto artikel hanya untuk adegan b-roll (bukan anchor)
    if allow_broll and cfg["video"].get("use_article_image", True):
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            cand = workdir / f"broll{ext}"
            if cand.exists():
                return cand
    bg_dir = resolve("assets/backgrounds")
    variants: list[Path] = []
    for ext in (".png", ".jpg", ".jpeg"):
        for pat in (f"{keyword}{ext}", f"{keyword}_*{ext}", f"{keyword}[0-9]*{ext}"):
            variants += sorted(bg_dir.glob(pat))
    # dedup jaga urutan
    seen, uniq = set(), []
    for v in variants:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    if uniq:
        if seed is None or len(uniq) == 1:
            return uniq[0]
        return uniq[_seed_int(seed) % len(uniq)]
    return resolve(cfg["video"]["background_default"])


def _bg_clip(cfg: dict, path: Path, W: int, H: int, duration: float):
    """Background menutup layar + efek Ken Burns (zoom pelan)."""
    base = ImageClip(str(path)).resized((W, H)).with_duration(duration)
    if not cfg["video"].get("ken_burns", True):
        return base
    zoom = float(cfg["video"].get("ken_burns_zoom", 0.08))
    dur = max(duration, 0.01)
    try:
        kb = (
            base.resized(lambda t: 1 + zoom * (t / dur))
            .with_position(("center", "center"))
            .with_duration(duration)
        )
        return kb
    except Exception as e:  # noqa: BLE001
        log.warning("Ken Burns dilewati (%s).", e)
        return base


def _camera_zoom_fn(cfg: dict, seed, duration: float):
    """Fungsi skala terhadap waktu utk punch-in kamera (selalu >= 1.0).

    Besaran & arah (in/out) ditentukan hash seed -> beragam antar adegan,
    tetap idempoten saat re-render.
    """
    h = _seed_int(seed)
    vid = cfg["video"]
    zmin = float(vid.get("camera_zoom_min", 0.06))
    zmax = float(vid.get("camera_zoom_max", 0.14))
    amt = zmin + (h % 1000) / 999.0 * max(zmax - zmin, 0.0)
    zoom_in = (h // 1000) % 2 == 0
    dur = max(duration, 0.01)
    if zoom_in:
        return lambda t: 1.0 + amt * (t / dur)
    return lambda t: (1.0 + amt) - amt * (t / dur)


def _overlay_clip(cfg: dict, W: int, H: int, duration: float, seed):
    """Overlay partikel/cahaya bergerak (drift pelan). None bila aset tak ada."""
    vid = cfg["video"]
    fpath = vid.get("bg_overlay_file", "")
    if not fpath:
        return None
    p = resolve(fpath)
    if not p.exists():
        log.warning("Overlay tak ditemukan: %s (dilewati).", p)
        return None
    op = float(vid.get("bg_overlay_opacity", 0.35))
    ow, oh = int(W * 1.2), int(H * 1.2)
    # drift halus: arah dari seed, amplitudo ~5% layar
    h = _seed_int(seed)
    ax = (W * 0.05) * (1 if (h % 2) else -1)
    ay = (H * 0.05) * (1 if ((h // 2) % 2) else -1)
    dur = max(duration, 0.01)
    x0, y0 = -int(W * 0.1), -int(H * 0.1)
    try:
        clip = (
            ImageClip(str(p)).resized((ow, oh))
            .with_duration(duration)
            .with_opacity(op)
            .with_position(lambda t: (x0 + ax * (t / dur), y0 + ay * (t / dur)))
        )
        return clip
    except Exception as e:  # noqa: BLE001
        log.warning("Overlay dilewati (%s).", e)
        return None


def _subtitle(cfg: dict, text: str, W: int, H: int, duration: float):
    from moviepy import TextClip

    vid = cfg["video"]
    return (
        TextClip(
            text=text,
            font=_find_font(cfg),
            font_size=vid["subtitle_fontsize"],
            color=vid["subtitle_color"],
            stroke_color=vid.get("subtitle_stroke", "black"),
            stroke_width=2,
            method="caption",
            size=(int(W * 0.9), None),
            text_align="center",
        )
        .with_duration(duration)
        .with_position(("center", int(H * 0.84)))
    )


def _banner(cfg: dict, headline: str, W: int, H: int, duration: float):
    """Banner headline di kiri-atas (gaya breaking news)."""
    from moviepy import TextClip

    text = (headline or "WORLD NEWS").upper()[:48]
    return (
        TextClip(
            text=text,
            font=_find_font(cfg),
            font_size=30,
            color="white",
            bg_color=cfg["video"].get("banner_color", "#c8281e"),
            method="caption",
            size=(int(W * 0.5), None),
            text_align="left",
            margin=(14, 8),
        )
        .with_duration(duration)
        .with_position((40, 40))
    )


def _load_mouths(char_dir: Path) -> dict[str, Path]:
    mouths = {}
    for shape in MOUTH_SHAPES:
        p = char_dir / f"mouth_{shape}.png"
        if p.exists():
            mouths[shape] = p
    if not mouths:
        raise FileNotFoundError(f"Tidak ada gambar mulut di {char_dir}")
    default = mouths.get("X") or next(iter(mouths.values()))
    for shape in MOUTH_SHAPES:
        mouths.setdefault(shape, default)
    return mouths


def _character_layers(cfg: dict, char_dir: Path, cues: list, W: int, H: int, dur: float):
    """Layer karakter: body + mulut bergerak."""
    char = cfg["character"]
    body_path = char_dir / "body.png"
    with Image.open(body_path) as im:
        bw, bh = im.size
    target_h = int(H * char["scale"])
    ratio = target_h / bh
    target_w = int(bw * ratio)
    px = int(W * char["pos_x"] - target_w / 2)
    py = int(H * char["pos_y"] - target_h / 2)

    body = (
        ImageClip(str(body_path)).resized((target_w, target_h))
        .with_duration(dur).with_position((px, py))
    )
    mouths = _load_mouths(char_dir)
    mox = int(char.get("mouth_offset_x", 0) * ratio)
    moy = int(char.get("mouth_offset_y", 0) * ratio)
    mouth_clips = []
    for cue in cues:
        start = float(cue["start"])
        end = min(float(cue["end"]), dur)
        if end <= start:
            continue
        mp = mouths.get(cue.get("value", "X"), mouths["X"])
        mouth_clips.append(
            ImageClip(str(mp)).resized((target_w, target_h))
            .with_start(start).with_duration(end - start)
            .with_position((px + mox, py + moy))
        )
    return [body, *mouth_clips]


def render_scene(cfg: dict, scene: dict, idx: int, workdir: Path,
                 headline: str = "") -> Path:
    """Render satu adegan (anchor atau reenactment) -> mp4."""
    vid = cfg["video"]
    W, H = vid["width"], vid["height"]
    workdir.mkdir(parents=True, exist_ok=True)

    # Suara + timing mulut
    wav = workdir / f"scene_{idx:02d}.wav"
    synth(cfg, scene["text"], wav, speaker=scene.get("speaker", "default"))
    audio = AudioFileClip(str(wav))
    duration = audio.duration
    cues = get_mouth_cues(cfg, wav)

    is_broll = (
        scene.get("type") == "reenactment" and vid.get("broll_scenes", True)
    )
    # b-roll: utamakan gambar AI sesuai isi naskah; gagal -> background bertema.
    bg_path = None
    if is_broll and cfg.get("ai_image", {}).get("enabled", False):
        try:
            from ai_image import generate_image

            ai_path = generate_image(
                cfg, scene["text"], workdir / f"ai_{idx:02d}.png", W, H
            )
            if ai_path:
                bg_path = ai_path
                log.info("  (b-roll pakai gambar AI: %s)", ai_path.name)
        except Exception as e:  # noqa: BLE001
            log.warning("Gambar AI dilewati (%s).", e)
    if bg_path is None:
        bg_path = _find_background(
            cfg, scene.get("background", "studio"), workdir,
            allow_broll=is_broll, seed=headline,
        )
    camera_on = vid.get("camera_zoom", False)
    seed = f"{headline}|{idx}"

    # "world" = bg + overlay + karakter (semua ini kena zoom kamera bila aktif).
    # Saat camera_zoom aktif, bg pakai versi rata-layar (tanpa Ken Burns) agar
    # tak dobel zoom; saat nonaktif, jalur lama (Ken Burns per-bg).
    if camera_on:
        bg = ImageClip(str(bg_path)).resized((W, H)).with_duration(duration)
    else:
        bg = _bg_clip(cfg, bg_path, W, H, duration)
    world_layers = [bg]

    overlay = _overlay_clip(cfg, W, H, duration, seed) if vid.get("bg_overlay", False) else None
    if overlay is not None:
        world_layers.append(overlay)

    # HUD (banner & subtitle) tetap diam -> di luar world, tak ikut zoom.
    hud_layers = []
    if is_broll:
        # b-roll: tanpa karakter, latar layar-penuh + subtitle
        log.info("  (adegan b-roll: %s)", bg_path.name)
    else:
        char_dir = pick_character_dir(cfg, headline)
        log.info("  (karakter: %s)", char_dir.name)
        world_layers += _character_layers(cfg, char_dir, cues, W, H, duration)
        if vid.get("headline_banner", True):
            try:
                hud_layers.append(_banner(cfg, headline, W, H, duration))
            except Exception as e:  # noqa: BLE001
                log.warning("Banner dilewati (%s).", e)

    if vid.get("subtitle"):
        try:
            hud_layers.append(_subtitle(cfg, scene["text"], W, H, duration))
        except Exception as e:  # noqa: BLE001
            log.warning("Subtitle dilewati (%s).", e)

    if camera_on:
        world = CompositeVideoClip(world_layers, size=(W, H)).with_duration(duration)
        # Composite ini punya MASK (layer karakter/overlay transparan). Bila di-resize
        # dengan fungsi-waktu (punch-in), .size dievaluasi di t=0 sedangkan ukuran frame
        # berubah tiap saat -> ketika dikomposit ulang, blit mask gagal dan SELURUH frame
        # jadi HITAM. Background sudah menutup layar penuh sehingga world efektif opaque,
        # jadi membuang mask aman dan menghilangkan bug "video hitam".
        world = world.without_mask()
        try:
            world = (
                world.resized(_camera_zoom_fn(cfg, seed, duration))
                .with_position(("center", "center"))
                .with_duration(duration)
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Zoom kamera dilewati (%s).", e)
        final_layers = [world, *hud_layers]
    else:
        final_layers = [*world_layers, *hud_layers]

    scene_clip = CompositeVideoClip(final_layers, size=(W, H)).with_audio(audio)
    out = workdir / f"scene_{idx:02d}.mp4"
    scene_clip.write_videofile(
        str(out), fps=vid["fps"], codec="libx264",
        audio_codec="aac", logger=None,
    )
    scene_clip.close()
    audio.close()
    kind = "b-roll" if is_broll else "anchor"
    log.info("Adegan %d (%s) selesai: %s (%.1fs)", idx, kind, out.name, duration)
    return out


if __name__ == "__main__":
    cfg = load_config()
    wd = resolve("output/_render_test")
    render_scene(cfg, {"speaker": "Anchor", "text": "Good evening, here is the world news.",
                       "background": "studio", "type": "anchor"}, 0, wd,
                 headline="Breaking: test")
    render_scene(cfg, {"speaker": "Narrator", "text": "Crowds gathered in the city as the protest grew.",
                       "background": "protest", "type": "reenactment"}, 1, wd)
