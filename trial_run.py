"""Trial run end-to-end: 1 video, upload PRIVATE, override in-memory.

Tidak mengubah config.yaml produksi. Dipakai untuk uji coba setelah fix bug
'video hitam'. Mengirim link via Telegram (notify) seperti produksi.
"""
import sys
sys.path.insert(0, "src")

from utils import load_config, log
from pipeline import run_once

cfg = load_config()

# --- override khusus uji coba (in-memory) ---
cfg["youtube"]["privacy"] = "private"          # link untuk review, bukan publik
cfg.setdefault("publish", {})
cfg["publish"]["max_videos_per_cycle"] = 1     # cukup satu video
cfg["publish"]["allow_single_source"] = True   # pastikan ada kandidat
cfg["publish"]["min_sources_for_publish"] = 1

log.info("=== TRIAL RUN: privacy=private, 1 video, allow_single_source ===")
made = run_once(cfg, allow_upload=True)
log.info("=== TRIAL SELESAI: %d video dibuat ===", made)
