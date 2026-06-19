"""Gabung semua klip adegan + intro/outro + musik latar menjadi final.mp4."""
from __future__ import annotations

from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)

from utils import load_config, log, resolve


def compose(cfg: dict, scene_files: list[Path], out_path: Path) -> Path:
    vid = cfg["video"]
    clips: list = []

    intro = vid.get("intro")
    if intro and resolve(intro).exists():
        clips.append(VideoFileClip(str(resolve(intro))))

    for sf in scene_files:
        clips.append(VideoFileClip(str(sf)))

    outro = vid.get("outro")
    if outro and resolve(outro).exists():
        clips.append(VideoFileClip(str(resolve(outro))))

    if not clips:
        raise RuntimeError("Tidak ada klip untuk digabung.")

    final = concatenate_videoclips(clips, method="compose")

    # Musik latar (loop sepanjang video, volume rendah)
    music = vid.get("music")
    if music and resolve(music).exists():
        try:
            bg = AudioFileClip(str(resolve(music)))
            # potong/loop agar pas durasi
            if bg.duration < final.duration:
                from moviepy.audio.fx import AudioLoop

                bg = bg.with_effects([AudioLoop(duration=final.duration)])
            else:
                bg = bg.subclipped(0, final.duration)
            bg = bg.with_volume_scaled(vid.get("music_volume", 0.12))
            mixed = CompositeAudioClip([final.audio, bg])
            final = final.with_audio(mixed)
        except Exception as e:  # noqa: BLE001
            log.warning("Musik latar dilewati (%s).", e)

    # Logo channel overlay (pojok kanan-atas) bila ada
    logo = vid.get("logo")
    if logo and resolve(logo).exists():
        try:
            from PIL import Image

            W, H = vid["width"], vid["height"]
            with Image.open(resolve(logo)) as im:
                lw, lh = im.size
            target_h = max(1, int(H * vid.get("logo_scale", 0.10)))
            ratio = target_h / lh
            target_w = max(1, int(lw * ratio))
            margin = int(vid.get("logo_margin", 24))
            logo_clip = (
                ImageClip(str(resolve(logo)))
                .resized((target_w, target_h))
                .with_duration(final.duration)
                .with_opacity(float(vid.get("logo_opacity", 0.85)))
                .with_position((W - target_w - margin, margin))
            )
            audio = final.audio
            final = CompositeVideoClip([final, logo_clip], size=(W, H)).with_audio(audio)
        except Exception as e:  # noqa: BLE001
            log.warning("Logo overlay dilewati (%s).", e)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.write_videofile(
        str(out_path),
        fps=vid["fps"],
        codec="libx264",
        audio_codec="aac",
        logger=None,
    )
    final.close()
    for c in clips:
        c.close()
    log.info("Video final: %s", out_path)
    return out_path


if __name__ == "__main__":
    cfg = load_config()
    test_dir = resolve("output/_render_test")
    scenes = sorted(test_dir.glob("scene_*.mp4"))
    if scenes:
        compose(cfg, scenes, resolve("output/_final_test.mp4"))
    else:
        print("Tidak ada scene_*.mp4 di", test_dir)
