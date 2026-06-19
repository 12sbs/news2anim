"""Orkestrator utama: berita -> video -> (upload).

Jalankan:  python src/pipeline.py
Argumen opsional:
  --no-upload    paksa tidak upload meski config youtube.enabled=true
  --config PATH  pakai file config lain
"""
from __future__ import annotations

import argparse
import json as _json
import re
import sys
from pathlib import Path

import time

from cluster import cluster_articles, is_cluster_covered, record_cluster
from compose import compose
from fetch_news import fetch_articles
from merge import merge_cluster
import notify
from render import render_scene
from script_gen import fix_script, generate_script
from thumbnail import generate_thumbnail
from validate import qa_clip, qa_final, qa_script, sanitize_metadata
from seo import generate_metadata
from upload import upload_resilient
from utils import load_config, load_state, log, mark_processed, resolve, save_state, slugify


def _download_broll(article: dict, workdir: Path) -> None:
    """Unduh foto artikel sebagai b-roll (workdir/broll.<ext>)."""
    url = article.get("image_url")
    if not url:
        return
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (news2anim bot)"}
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        ext = ".jpg"
        ct = r.headers.get("Content-Type", "")
        if "png" in ct:
            ext = ".png"
        elif "webp" in ct:
            ext = ".webp"
        (workdir / f"broll{ext}").write_bytes(r.content)
        log.info("Foto artikel diunduh untuk b-roll.")
    except Exception as e:  # noqa: BLE001
        log.warning("Gagal unduh foto artikel: %s", e)


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


def _qa_on(cfg: dict) -> bool:
    return cfg.get("qa", {}).get("enabled", True)


def _write_review(workdir: Path, reasons: list[str]) -> None:
    """Tulis REVIEW_NEEDED.txt berisi alasan video perlu ditinjau manual."""
    lines = ["VIDEO INI BUTUH TINJAUAN MANUAL — upload dilewati.", "", "Alasan:"]
    lines += [f"- {r}" for r in reasons]
    (workdir / "REVIEW_NEEDED.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _simplify_scene(scene: dict) -> dict:
    """Eskalasi Gerbang B: pangkas teks adegan agar render lebih ringan/stabil."""
    s = dict(scene)
    text = s.get("text", "")
    parts = re.split(r"(?<=[.!?])\s+", text)
    s["text"] = " ".join(parts[:2]).strip() or text[:160]
    return s


def _build_script_with_qa(
    cfg: dict, article: dict
) -> tuple[dict | None, list[str]]:
    """Naskah + Gerbang A (retry). Return (scenario|None, alasan_gagal)."""
    scenario = generate_script(cfg, article)
    if not scenario["scenes"]:
        return None, ["skenario kosong"]
    if not _qa_on(cfg):
        return scenario, []

    ok, reasons = qa_script(cfg, article, scenario)
    max_retries = cfg.get("qa", {}).get("max_script_retries", 2)
    attempt = 0
    while not ok and attempt < max_retries:
        attempt += 1
        log.warning(
            "Gerbang A gagal (%s). Perbaiki naskah %d/%d.",
            "; ".join(reasons), attempt, max_retries,
        )
        scenario = fix_script(cfg, article, scenario, reasons)
        if not scenario["scenes"]:
            return None, ["skenario kosong saat perbaikan"]
        ok, reasons = qa_script(cfg, article, scenario)
    if not ok:
        return None, reasons
    return scenario, []


def _render_scene_with_qa(
    cfg: dict, scene: dict, idx: int, workdir: Path, headline: str,
    needs_review: list[str],
) -> Path | None:
    """Render 1 adegan + Gerbang B (re-render -> eskalasi -> drop)."""
    max_retries = cfg.get("qa", {}).get("max_scene_retries", 2)
    wav = workdir / f"scene_{idx:02d}.wav"
    cur = dict(scene)
    for attempt in range(max_retries + 1):
        clip = None
        try:
            clip = render_scene(cfg, cur, idx, workdir, headline=headline)
        except Exception as e:  # noqa: BLE001
            log.error("Adegan %d gagal render (percobaan %d): %s", idx, attempt + 1, e)
        if clip is not None:
            if not _qa_on(cfg):
                return clip
            ok, reasons = qa_clip(cfg, clip, wav)
            if ok:
                if attempt:
                    log.info("Adegan %d lolos QA setelah diulang.", idx)
                return clip
            log.warning("Gerbang B adegan %d gagal (%s).", idx, "; ".join(reasons))
        # eskalasi: sederhanakan teks sebelum percobaan terakhir
        if attempt == max_retries - 1:
            cur = _simplify_scene(cur)
            log.info("Eskalasi adegan %d: teks disederhanakan.", idx)
    needs_review.append(f"adegan {idx} di-drop (mutu rendah)")
    log.error("Adegan %d di-drop setelah %d percobaan.", idx, max_retries + 1)
    return None


def _select_clusters(cfg: dict, clusters: list[list[dict]]) -> list[list[dict]]:
    """Pilih cluster yang LAYAK dibuat video pada siklus ini.

    - Buang peristiwa yang sudah pernah dibuat (lintas-siklus) -> tandai processed.
    - Buang peristiwa dgn sumber < min_sources_for_publish (kecuali allow_single_source);
      anggota TIDAK ditandai processed agar siklus berikut bisa dapat sumber tambahan.
    - Batasi jumlah video per siklus (kualitas > kuantitas). Sisanya dibiarkan
      untuk dipertimbangkan siklus berikutnya.
    """
    pub = cfg.get("publish", {})
    min_sources = pub.get("min_sources_for_publish", 1)
    allow_single = pub.get("allow_single_source", True)
    max_videos = pub.get("max_videos_per_cycle", 2)

    selected: list[list[dict]] = []
    for cluster in clusters:
        covered, title, score = is_cluster_covered(cfg, cluster)
        if covered:
            log.info("Peristiwa SUDAH dibuat (skor %.2f): %s -> skip.", score, title[:50])
            for a in cluster:
                mark_processed(cfg, a.get("id", ""))
            continue
        if len(cluster) < min_sources and not allow_single:
            log.info(
                "Peristiwa hanya %d sumber (< %d) -> tunggu korroborasi.",
                len(cluster), min_sources,
            )
            continue
        selected.append(cluster)
    return selected[:max_videos]


def _cleanup_intermediates(workdir: Path) -> None:
    """Hapus berkas kerja besar setelah final.mp4 jadi; sisakan artefak audit.

    Tujuan: cegah disk penuh di mode 24/7. final.mp4 + thumbnail + json/teks
    audit dipertahankan; scene_*.mp4/wav, ai_*.png, broll.*, thumb_bg.png dibuang.
    """
    keep = {"final.mp4", "thumbnail.jpg", "metadata.json", "scenes.json",
            "treatment.txt", "REVIEW_NEEDED.txt"}
    try:
        for f in workdir.iterdir():
            if f.is_file() and f.name not in keep:
                try:
                    f.unlink()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as e:  # noqa: BLE001
        log.warning("Cleanup intermediate gagal (lanjut): %s", e)


def _free_mb(path: Path) -> float:
    """Ruang bebas (MB) pada filesystem yang memuat path."""
    try:
        import shutil as _sh
        return _sh.disk_usage(str(path)).free / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return float("inf")


def _prune_old_output(cfg: dict) -> None:
    """Jaga disk tetap lega untuk operasi 24/7 tanpa pengawasan.

    Dua lapis:
      1) Retensi umur: hapus folder video > keep_output_days.
      2) Emergency: bila ruang bebas < min_free_mb, hapus folder TERTUA satu per
         satu sampai sehat (sisakan minimal 5 terbaru). Melengkapi watchdog cron.
    """
    import shutil
    base = resolve("output")
    if not base.exists():
        return

    # Folder yang masih menunggu upload ulang JANGAN dihapus (artefaknya dipakai).
    protected = _pending_slugs(cfg)

    # --- lapis 1: berdasarkan umur ---
    days = cfg.get("automation", {}).get("keep_output_days", 7)
    if days and days > 0:
        cutoff = time.time() - days * 86400
        for d in base.iterdir():
            if not d.is_dir() or d.name in protected:
                continue
            try:
                if d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
                    log.info("Retensi: hapus output lama (%s)", d.name)
            except Exception as e:  # noqa: BLE001
                log.warning("Gagal hapus output lama %s: %s", d.name, e)

    # --- lapis 2: emergency berdasarkan ruang bebas ---
    min_free = cfg.get("automation", {}).get("min_free_mb", 900)
    keep_min = cfg.get("automation", {}).get("keep_min_videos", 5)
    while _free_mb(base) < min_free:
        dirs = sorted(
            (d for d in base.iterdir() if d.is_dir() and d.name not in protected),
            key=lambda p: p.stat().st_mtime,
        )
        if len(dirs) <= keep_min:
            log.warning(
                "Disk menipis (%.0fMB) tapi tersisa <=%d video -> stop prune.",
                _free_mb(base), keep_min,
            )
            break
        oldest = dirs[0]
        log.warning("Disk menipis -> hapus output tertua: %s", oldest.name)
        shutil.rmtree(oldest, ignore_errors=True)


def _notify_search(cfg: dict, n_articles: int, n_events: int, n_selected: int) -> None:
    """Telegram: bukti sistem hidup tiap siklus pencarian berita."""
    if not notify.flag(cfg, "on_search", True):
        return
    if n_selected == 0 and notify.flag(cfg, "search_skip_if_empty", False):
        return
    notify.send(
        cfg,
        "🔍 <b>news2anim — siklus pencarian</b>\n"
        f"📰 {n_articles} artikel diambil\n"
        f"🧩 {n_events} peristiwa terdeteksi\n"
        f"🎬 {n_selected} dipilih untuk dibuat video",
    )


def _notify_upload_ok(
    cfg: dict, title: str, vid_id: str, n_sources: int, final: Path
) -> None:
    if not notify.flag(cfg, "on_upload", True):
        return
    notify.send(
        cfg,
        "✅ <b>Video terupload</b>\n"
        f"{notify.esc(title)}\n"
        f"🔗 https://youtu.be/{vid_id}\n"
        f"📡 {n_sources} sumber · ⏱ {_video_duration(final):.0f} detik",
    )


def _notify_upload_fail(cfg: dict, title: str, err: str) -> None:
    if not notify.flag(cfg, "on_upload", True):
        return
    notify.send(
        cfg,
        "⚠️ <b>Upload gagal</b>\n"
        f"{notify.esc(title)}\n"
        f"{notify.esc(err[:300])}",
    )


def _notify_event_start(cfg: dict, title: str, n_sources: int) -> None:
    """Telegram: sebuah peristiwa mulai digarap jadi video."""
    if not notify.flag(cfg, "on_event_start", True):
        return
    notify.send(
        cfg,
        "🎬 <b>Mulai garap video</b>\n"
        f"{notify.esc(title)}\n"
        f"📡 {n_sources} sumber",
    )


def _notify_stage(cfg: dict, title: str, stage: str) -> None:
    """Telegram: progres tahap besar (naskah siap, render selesai, mulai upload)."""
    if not notify.flag(cfg, "on_progress", True):
        return
    notify.send(
        cfg,
        f"⏳ <b>{notify.esc(stage)}</b>\n"
        f"{notify.esc(title)}",
    )


def _notify_event_fail(cfg: dict, title: str, reason: str) -> None:
    """Telegram: peristiwa gagal di tengah proses (bukan upload YouTube)."""
    if not notify.flag(cfg, "on_fail", True):
        return
    notify.send(
        cfg,
        "❌ <b>Proses gagal</b>\n"
        f"{notify.esc(title)}\n"
        f"{notify.esc(reason[:300])}",
    )


def process_cluster(cfg: dict, cluster: list[dict], allow_upload: bool) -> Path | None:
    """Buat satu video dari satu peristiwa (gabungan banyak sumber)."""
    merged = merge_cluster(cfg, cluster)
    log.info(
        "=== Memproses peristiwa: %s (%d sumber) ===",
        merged["title"][:70], len(cluster),
    )
    _notify_event_start(cfg, merged["title"], len(cluster))
    needs_review: list[str] = []

    # 1) Naskah panjang (2 tahap) + Gerbang A (juri LLM + retry)
    scenario, reasons = _build_script_with_qa(cfg, merged)
    slug = slugify(merged["title"])
    workdir = resolve("output") / slug
    workdir.mkdir(parents=True, exist_ok=True)
    if scenario is None:
        _write_review(workdir, ["Gerbang A (naskah): " + r for r in reasons])
        record_cluster(cfg, cluster)
        log.error("Naskah gagal QA -> peristiwa dilewati.")
        _notify_event_fail(
            cfg, merged["title"],
            "Naskah gagal QA (Gerbang A): " + "; ".join(reasons),
        )
        return None
    _notify_stage(cfg, merged["title"], "Naskah siap")

    # Simpan naskah untuk audit (treatment + scenes)
    if cfg["script"].get("save_treatment") and scenario.get("treatment"):
        (workdir / "treatment.txt").write_text(
            scenario["treatment"], encoding="utf-8"
        )
    (workdir / "scenes.json").write_text(
        _json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 2) Unduh foto artikel (b-roll) bila ada & diizinkan
    if cfg["video"].get("use_article_image", True):
        _download_broll(merged, workdir)

    # 3) Render tiap adegan + Gerbang B (re-render -> eskalasi -> drop)
    headline = scenario.get("title", merged["title"])
    scene_files = []
    for i, scene in enumerate(scenario["scenes"]):
        clip = _render_scene_with_qa(cfg, scene, i, workdir, headline, needs_review)
        if clip is not None:
            scene_files.append(clip)

    if not scene_files:
        _write_review(workdir, needs_review or ["semua adegan gagal render"])
        record_cluster(cfg, cluster)
        log.error("Semua adegan gagal -> peristiwa dilewati. Tidak upload.")
        _notify_event_fail(
            cfg, merged["title"], "Semua adegan gagal render -> tidak upload.",
        )
        return None

    # 4) Gabung + Gerbang C (durasi minimal -> recompose 1x)
    final = workdir / "final.mp4"
    compose(cfg, scene_files, final)
    if _qa_on(cfg):
        ok, c_reasons = qa_final(cfg, final)
        if not ok and cfg.get("qa", {}).get("recompose_if_short", True):
            log.warning("Gerbang C gagal (%s). Recompose 1x.", "; ".join(c_reasons))
            compose(cfg, scene_files, final)
            ok, c_reasons = qa_final(cfg, final)
        if not ok:
            needs_review += ["Gerbang C (durasi): " + r for r in c_reasons]
    log.info("Durasi video: %.1f detik", _video_duration(final))
    _notify_stage(
        cfg, merged["title"],
        f"Render + gabung selesai ({len(scene_files)} adegan · "
        f"{_video_duration(final):.0f} dtk)",
    )

    # 5) Metadata SEO + Gerbang D (sanitasi kata terlarang)
    meta = generate_metadata(cfg, merged, scenario)
    if _qa_on(cfg):
        meta, changed, why = sanitize_metadata(cfg, meta)
        if changed:
            log.warning("Gerbang D: metadata disensor (%s).", "; ".join(why))
    (workdir / "metadata.json").write_text(
        _json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 6) Thumbnail otomatis (non-blok)
    thumb = None
    if cfg.get("youtube", {}).get("thumbnail", False):
        try:
            thumb = generate_thumbnail(cfg, merged, scenario, final, workdir)
        except Exception as e:  # noqa: BLE001
            log.warning("Thumbnail gagal (lanjut): %s", e)

    # 7) Keputusan upload — 24/7 OTOMATIS
    #    - Warning lunak (Gerbang B/C/D): publish bila publish_on_warnings.
    #    - Kegagalan safety (Gerbang A) sudah disaring di atas (scenario None).
    publish_on_warnings = cfg.get("qa", {}).get("publish_on_warnings", True)
    if needs_review:
        _write_review(workdir, needs_review)
        if not publish_on_warnings:
            log.warning(
                "QA menandai %d masalah -> upload DILEWATI. Lihat %s",
                len(needs_review), workdir / "REVIEW_NEEDED.txt",
            )
            _notify_event_fail(
                cfg, meta["title"],
                f"QA menandai {len(needs_review)} masalah -> upload DILEWATI: "
                + "; ".join(needs_review),
            )
            record_cluster(cfg, cluster)
            return final
        log.warning(
            "QA menandai %d masalah -> tetap publish (publish_on_warnings).",
            len(needs_review),
        )

    if allow_upload and cfg["youtube"].get("enabled"):
        _notify_stage(cfg, meta["title"], "Mulai upload ke YouTube")
        try:
            vid_id, meta, repaired, status = upload_resilient(
                cfg, final, meta, thumb_path=thumb
            )
            if repaired:
                # metadata diperbaiki otomatis -> simpan versi yang benar.
                (workdir / "metadata.json").write_text(
                    _json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                _notify_stage(cfg, meta["title"], "Metadata diperbaiki otomatis (self-heal)")
            if vid_id:
                _notify_upload_ok(cfg, meta["title"], vid_id, len(cluster), final)
            elif status == "retry":
                # Gagal SEMENTARA (limit/kuota YouTube). Video sudah jadi -> jangan
                # dibuang; antre untuk dicoba upload ulang di siklus berikutnya.
                _queue_pending(cfg, workdir.name, meta["title"], len(cluster))
                _notify_stage(
                    cfg, meta["title"],
                    "Upload ditunda (limit YouTube) — diantre, dicoba lagi otomatis",
                )
            else:
                _notify_upload_fail(cfg, meta["title"], "Upload gagal setelah self-heal")
        except Exception as e:  # noqa: BLE001
            log.error("Upload gagal: %s", e)
            _notify_upload_fail(cfg, meta["title"], str(e))
    else:
        log.info("Upload dilewati (mode --no-upload atau youtube.enabled=false).")

    # 8) Catat peristiwa (anti-duplikasi lintas-siklus + tandai semua sumber)
    record_cluster(cfg, cluster)

    # 9) Bersihkan berkas kerja besar (24/7: jaga disk tetap lega)
    _cleanup_intermediates(workdir)

    log.info("=== Selesai: %s ===", final)
    return final


# ----------------------------------------------------------------------------
# Antrean upload tertunda (pending-upload queue)
#
# Saat upload gagal SEMENTARA (limit/kuota YouTube), video yang sudah dirender
# tak boleh hilang. Slug folder-nya diantre di state.json -> tiap siklus dicoba
# upload ulang (HANYA upload, pakai final.mp4/metadata.json/thumbnail.jpg yang
# memang disimpan _cleanup_intermediates) sampai limit reset. Render TIDAK
# diulang, jadi murah.
# ----------------------------------------------------------------------------
def _pending_slugs(cfg: dict) -> set[str]:
    return {p.get("slug") for p in load_state(cfg).get("pending_uploads", [])}


def _queue_pending(cfg: dict, slug: str, title: str, n_sources: int) -> None:
    """Tambah video ke antrean upload (idempoten per slug)."""
    state = load_state(cfg)
    pend = state.setdefault("pending_uploads", [])
    if any(p.get("slug") == slug for p in pend):
        return
    pend.append({"slug": slug, "title": title, "n_sources": n_sources})
    save_state(cfg, state)
    log.info("Antrean upload: '%s' ditambahkan (total %d).", slug, len(pend))


def _dequeue_pending(cfg: dict, slug: str) -> None:
    state = load_state(cfg)
    pend = state.get("pending_uploads", [])
    new = [p for p in pend if p.get("slug") != slug]
    if len(new) != len(pend):
        state["pending_uploads"] = new
        save_state(cfg, state)


def _retry_pending_uploads(cfg: dict, allow_upload: bool) -> None:
    """Coba upload ulang video yang tertunda akibat limit. Dipanggil di awal
    siklus agar backlog diprioritaskan sebelum produksi video baru."""
    if not (allow_upload and cfg["youtube"].get("enabled")):
        return
    pending = load_state(cfg).get("pending_uploads", [])
    if not pending:
        return
    log.info("Antrean upload tertunda: %d video -> coba lagi.", len(pending))
    base = resolve("output")
    for item in list(pending):
        slug = item.get("slug", "")
        workdir = base / slug
        final = workdir / "final.mp4"
        meta_path = workdir / "metadata.json"
        thumb = workdir / "thumbnail.jpg"
        title = item.get("title", slug)
        if not final.exists() or not meta_path.exists():
            log.warning("Pending '%s': artefak hilang -> buang dari antrean.", slug)
            _dequeue_pending(cfg, slug)
            _notify_upload_fail(cfg, title, "Artefak video sudah terhapus, tak bisa upload ulang.")
            continue
        try:
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log.warning("Pending '%s': metadata rusak (%s) -> buang.", slug, e)
            _dequeue_pending(cfg, slug)
            continue
        vid_id, meta, repaired, status = upload_resilient(
            cfg, final, meta, thumb_path=thumb if thumb.exists() else None
        )
        if repaired:
            meta_path.write_text(
                _json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if vid_id:
            _dequeue_pending(cfg, slug)
            _notify_upload_ok(cfg, meta["title"], vid_id, item.get("n_sources", 1), final)
            log.info("Pending '%s' berhasil diupload.", slug)
        elif status == "retry":
            # Limit masih aktif -> percuma lanjut item lain siklus ini. Berhenti,
            # sisa antrean tetap tersimpan untuk siklus berikutnya.
            log.info("Pending '%s' masih kena limit -> tunda sisa antrean.", slug)
            break
        else:
            _dequeue_pending(cfg, slug)
            _notify_upload_fail(cfg, meta["title"], "Upload ulang gagal (permanen).")


def run_once(cfg: dict, allow_upload: bool) -> int:
    """Satu siklus: ambil berita -> cluster peristiwa -> pilih -> proses.

    Kembalikan jumlah video yang dibuat.
    """
    _prune_old_output(cfg)
    _retry_pending_uploads(cfg, allow_upload)
    articles = fetch_articles(cfg)
    clusters = cluster_articles(cfg, articles) if articles else []
    selected = _select_clusters(cfg, clusters) if clusters else []
    _notify_search(cfg, len(articles), len(clusters), len(selected))
    if not articles:
        log.info("Tidak ada berita baru.")
        return 0
    if not selected:
        log.info("Tidak ada peristiwa baru yang memenuhi syarat.")
        return 0

    made = 0
    for cluster in selected:
        try:
            if process_cluster(cfg, cluster, allow_upload):
                made += 1
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            log.error("Gagal memproses peristiwa: %s", e)
            # best-effort: judul dari item pertama cluster (tanpa merge ulang)
            _ctitle = (cluster[0].get("title") if cluster else "") or "(tak diketahui)"
            _notify_event_fail(cfg, _ctitle, f"Crash saat memproses: {e}")
            # anti poison-loop: tandai agar tak diproses ulang selamanya
            try:
                record_cluster(cfg, cluster)
            except Exception:  # noqa: BLE001
                pass
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
            try:
                made = run_once(cfg, allow_upload)
            except KeyboardInterrupt:
                raise
            except Exception as e:  # noqa: BLE001
                # service 24/7: satu siklus gagal tidak boleh mematikan loop
                log.error("Siklus gagal total: %s", e)
                made = 0
            log.info("Siklus selesai (%d video). Tidur %d detik...", made, interval)
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("Mode watch dihentikan.")
        sys.exit(0)


if __name__ == "__main__":
    main()
