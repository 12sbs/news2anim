"""Orkestrator utama: berita -> video -> (upload).

Jalankan:  python src/pipeline.py
Argumen opsional:
  --no-upload    paksa tidak upload meski config youtube.enabled=true
  --config PATH  pakai file config lain
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import time

from compose import compose
from dedup import is_duplicate, record_story
from fetch_news import fetch_articles
from render import render_scene
from script_gen import generate_script
from seo import generate_metadata
from upload import upload_video
from utils import load_config, log, mark_processed, resolve, slugify


def _video_duration(path: Path) -> float:
    """Durasi video (detik) via ffprobe."""
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return 0.0


def process_article(cfg: dict, article: dict, allow_upload: bool) -> Path | None:
    log.info("=== Memproses: %s ===", article["title"][:70])

    # 0) Anti-duplikasi LINTAS-SUMBER: berita sama (sumber beda) -> jangan buat ulang
    dup, matched, score = is_duplicate(cfg, article)
    if dup:
        log.info("DUPLIKAT (skor %.2f) dari: %s -> dilewati.", score, matched[:60])
        mark_processed(cfg, article["id"])
        return None

    # 1) Naskah (2 tahap: treatment -> scenes)
    scenario = generate_script(cfg, article)
    if not scenario["scenes"]:
        log.warning("Skenario kosong, lewati.")
        return None

    slug = slugify(article["title"])
    workdir = resolve("output") / slug
    workdir.mkdir(parents=True, exist_ok=True)

    # Simpan naskah untuk ditinjau (treatment + scenes)
    if cfg["script"].get("save_treatment") and scenario.get("treatment"):
        (workdir / "treatment.txt").write_text(
            scenario["treatment"], encoding="utf-8"
        )
    import json as _json
    (workdir / "scenes.json").write_text(
        _json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 2) Render tiap adegan
    scene_files = []
    for i, scene in enumerate(scenario["scenes"]):
        try:
            scene_files.append(render_scene(cfg, scene, i, workdir))
        except Exception as e:  # noqa: BLE001
            log.error("Adegan %d gagal: %s", i, e)

    if not scene_files:
        log.error("Semua adegan gagal, batal.")
        return None

    # 3) Gabung
    final = workdir / "final.mp4"
    compose(cfg, scene_files, final)

    # Cek durasi minimal
    dur = _video_duration(final)
    min_dur = cfg["video"].get("min_duration_sec", 0)
    if min_dur and dur < min_dur:
        log.warning(
            "Durasi %.1fs < target %ds. Naikkan script.target_words / max_scenes "
            "atau pakai model Ollama lebih besar.", dur, min_dur
        )
    else:
        log.info("Durasi video: %.1f detik", dur)

    # 4) Metadata SEO (judul + deskripsi + tags)
    meta = generate_metadata(cfg, article, scenario)
    (workdir / "metadata.json").write_text(
        _json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 5) Upload (opsional)
    if allow_upload and cfg["youtube"].get("enabled"):
        try:
            upload_video(
                cfg, final,
                title=meta["title"],
                description=meta["description"],
                tags=meta["tags"],
            )
        except Exception as e:  # noqa: BLE001
            log.error("Upload gagal: %s", e)

    # 6) Catat signature berita (untuk anti-duplikasi lintas-sumber)
    record_story(cfg, article)
    log.info("=== Selesai: %s ===", final)
    return final


def run_once(cfg: dict, allow_upload: bool) -> int:
    """Satu siklus: ambil berita baru -> proses. Kembalikan jumlah video dibuat."""
    articles = fetch_articles(cfg)
    if not articles:
        log.info("Tidak ada berita baru.")
        return 0
    made = 0
    for article in articles:
        try:
            if process_article(cfg, article, allow_upload):
                made += 1
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            log.error("Gagal memproses artikel: %s", e)
    return made


def main():
    ap = argparse.ArgumentParser(description="news2anim pipeline")
    ap.add_argument("--config", default=None)
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--watch", action="store_true",
                    help="pantau feed terus-menerus, proses berita baru otomatis")
    args = ap.parse_args()

    cfg = load_config(args.config)
    allow_upload = not args.no_upload

    if not args.watch:
        run_once(cfg, allow_upload)
        return

    interval = cfg["automation"].get("poll_interval_sec", 600)
    log.info("Mode WATCH aktif. Cek feed tiap %d detik. Ctrl+C untuk berhenti.", interval)
    try:
        while True:
            made = run_once(cfg, allow_upload)
            log.info("Siklus selesai (%d video). Tidur %d detik...", made, interval)
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("Mode watch dihentikan.")
        sys.exit(0)


if __name__ == "__main__":
    main()
