"""Render satu adegan menjadi klip video.

Konvensi aset karakter (penting!):
- body.png       : gambar tubuh+kepala karakter (background transparan)
- mouth_X.png    : bentuk mulut, UKURAN KANVAS SAMA dengan body.png,
                   mulut digambar di posisi yang benar, sisanya transparan.
Dengan begitu mulut cukup ditempel di posisi & skala yang sama dengan body.
"""
from __future__ import annotations

from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
)
from PIL import Image

from lipsync import MOUTH_SHAPES, get_mouth_cues
from tts import synth
from utils import load_config, log, resolve


def _find_font(cfg: dict) -> str | None:
    """Cari font untuk subtitle: dari config, lalu font umum di sistem."""
    cfgfont = cfg["video"].get("subtitle_font")
    if cfgfont and Path(cfgfont).exists():
        return cfgfont
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def _find_background(cfg: dict, keyword: str) -> Path:
    """Cari assets/backgrounds/<keyword>.png, jika tak ada pakai default."""
    bg_dir = resolve("assets/backgrounds")
    for ext in (".png", ".jpg", ".jpeg"):
        cand = bg_dir / f"{keyword}{ext}"
        if cand.exists():
            return cand
    return resolve(cfg["video"]["background_default"])


def _load_mouths(char_dir: Path) -> dict[str, Path]:
    """Petakan tiap bentuk -> file. Jatuh ke mouth_X bila bentuk tak ada."""
    mouths = {}
    for shape in MOUTH_SHAPES:
        p = char_dir / f"mouth_{shape}.png"
        if p.exists():
            mouths[shape] = p
    if not mouths:
        raise FileNotFoundError(f"Tidak ada gambar mulut di {char_dir}")
    # default fallback
    default = mouths.get("X") or next(iter(mouths.values()))
    for shape in MOUTH_SHAPES:
        mouths.setdefault(shape, default)
    return mouths


def render_scene(cfg: dict, scene: dict, idx: int, workdir: Path) -> Path:
    """Hasilkan klip mp4 untuk satu adegan, kembalikan path-nya."""
    vid = cfg["video"]
    W, H = vid["width"], vid["height"]
    char = cfg["character"]
    char_dir = resolve(char["dir"])

    workdir.mkdir(parents=True, exist_ok=True)

    # 1) Suara
    wav = workdir / f"scene_{idx:02d}.wav"
    synth(cfg, scene["text"], wav, speaker=scene.get("speaker", "default"))

    # 2) Timing mulut
    cues = get_mouth_cues(cfg, wav)

    # 3) Klip audio + durasi
    audio = AudioFileClip(str(wav))
    duration = audio.duration

    # 4) Background (di-resize menutup layar)
    bg_path = _find_background(cfg, scene.get("background", "studio"))
    bg = ImageClip(str(bg_path)).resized((W, H)).with_duration(duration)

    # 5) Body karakter
    body_path = char_dir / "body.png"
    with Image.open(body_path) as im:
        bw, bh = im.size
    target_h = int(H * char["scale"])
    scale_ratio = target_h / bh
    target_w = int(bw * scale_ratio)
    pos_x = int(W * char["pos_x"] - target_w / 2)
    pos_y = int(H * char["pos_y"] - target_h / 2)

    body = (
        ImageClip(str(body_path))
        .resized((target_w, target_h))
        .with_duration(duration)
        .with_position((pos_x, pos_y))
    )

    # 6) Mulut: satu ImageClip per cue, posisi & skala SAMA dengan body
    mouths = _load_mouths(char_dir)
    mouth_clips = []
    mox = int(char.get("mouth_offset_x", 0) * scale_ratio)
    moy = int(char.get("mouth_offset_y", 0) * scale_ratio)
    for cue in cues:
        start = float(cue["start"])
        end = min(float(cue["end"]), duration)
        if end <= start:
            continue
        shape = cue.get("value", "X")
        mp = mouths.get(shape, mouths["X"])
        clip = (
            ImageClip(str(mp))
            .resized((target_w, target_h))
            .with_start(start)
            .with_duration(end - start)
            .with_position((pos_x + mox, pos_y + moy))
        )
        mouth_clips.append(clip)

    layers = [bg, body, *mouth_clips]

    # 7) Subtitle (opsional)
    if vid.get("subtitle"):
        try:
            from moviepy import TextClip

            txt = (
                TextClip(
                    text=scene["text"],
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
                .with_position(("center", int(H * 0.88)))
            )
            layers.append(txt)
        except Exception as e:  # noqa: BLE001
            log.warning("Subtitle dilewati (%s). Cek font/ImageMagick.", e)

    scene_clip = CompositeVideoClip(layers, size=(W, H)).with_audio(audio)

    out = workdir / f"scene_{idx:02d}.mp4"
    scene_clip.write_videofile(
        str(out),
        fps=vid["fps"],
        codec="libx264",
        audio_codec="aac",
        logger=None,
    )
    scene_clip.close()
    audio.close()
    log.info("Adegan %d selesai: %s (%.1fs)", idx, out.name, duration)
    return out


if __name__ == "__main__":
    cfg = load_config()
    demo_scene = {
        "speaker": "Host",
        "text": "Selamat datang di berita animasi. Ini adalah uji coba adegan.",
        "background": "studio",
    }
    render_scene(cfg, demo_scene, 0, resolve("output/_render_test"))
