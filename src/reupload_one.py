"""Upload ulang SATU video yang sudah terlanjur gagal (recovery sekali-jalan).

Karena cluster sudah ditandai 'selesai' (anti-duplikasi), pipeline normal tak
akan memprosesnya lagi. Skrip ini membaca hasil di folder output lalu mengupload
lewat jalur tahan-gagal (upload_resilient) sehingga metadata otomatis diperbaiki.

Pakai:
  .venv/bin/python src/reupload_one.py [folder_output]
Default folder: video Iran yang gagal pada 18 Jun 2026.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from upload import upload_resilient
from utils import load_config, log, resolve

DEFAULT_DIR = "output/How_Trumps_memo_of_understanding_with_Iran_compare"


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    workdir = Path(arg)
    if not workdir.is_absolute():
        workdir = resolve(arg)

    final = workdir / "final.mp4"
    meta_path = workdir / "metadata.json"
    thumb = workdir / "thumbnail.jpg"

    if not final.exists():
        log.error("final.mp4 tidak ada di %s", workdir)
        return 1
    if not meta_path.exists():
        log.error("metadata.json tidak ada di %s", workdir)
        return 1

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    cfg = load_config()

    log.info("Re-upload: %s", meta.get("title", "(tanpa judul)"))
    vid_id, meta, repaired, _status = upload_resilient(
        cfg, final, meta, thumb_path=thumb if thumb.exists() else None
    )

    if repaired:
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("metadata.json diperbarui (hasil self-heal).")

    if vid_id:
        log.info("Sukses re-upload: https://youtu.be/%s", vid_id)
        return 0
    log.error("Re-upload gagal.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
