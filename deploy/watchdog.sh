#!/usr/bin/env bash
# ============================================================================
#  Watchdog news2anim — jaring pengaman SWA-PULIH di atas systemd.
#
#  systemd sudah auto-restart bila service CRASH (Restart=always). Watchdog ini
#  menangani kegagalan yang tidak bisa diselesaikan systemd sendiri, agar sistem
#  bisa jalan 24/7 TANPA pengawasan manusia:
#
#    1) service news2anim ter-stop          -> restart
#    2) ollama mati                         -> restart
#    3) DISK menipis (root / atau SSD)      -> prune output lama + bersih cache
#    4) ollama SEGFAULT (lib AVX512 buggy)  -> hapus lib bermasalah + restart
#
#  Pasang via cron ROOT (lihat deploy/setup.sh atau install manual):
#     */5 * * * * /home/ubuntu/news2anim/deploy/watchdog.sh >> /var/log/news2anim_watchdog.log 2>&1
# ============================================================================
set -uo pipefail

SERVICE="news2anim"
OUTPUT_DIR="/mnt/data/news2anim/output"       # output video (di SSD)
OLLAMA_LIB="/usr/local/lib/ollama"            # lokasi lib ggml/cuda ollama
MIN_FREE_MB=900                               # ambang minimal ruang bebas (root & SSD)
ts() { date '+%F %T'; }

# --- util: ruang bebas (MB) pada mount yang memuat path $1 ---
free_mb() { df -Pm "$1" 2>/dev/null | awk 'NR==2{print $4}'; }

# ---------------------------------------------------------------- 1) service
if ! systemctl is-active --quiet "$SERVICE"; then
  echo "$(ts) [$SERVICE] tidak aktif -> restart"
  systemctl restart "$SERVICE" || echo "$(ts) [$SERVICE] gagal restart"
fi

# ---------------------------------------------------------------- 2) ollama
if systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
  if ! systemctl is-active --quiet ollama; then
    echo "$(ts) [ollama] tidak aktif -> restart"
    systemctl restart ollama || echo "$(ts) [ollama] gagal restart"
  fi
fi

# ---------------------------------------------------------------- 3) disk guard
disk_cleanup() {
  echo "$(ts) [disk] cleanup ringan (apt cache, journal, blob partial ollama)"
  apt-get clean 2>/dev/null || true
  journalctl --vacuum-size=20M 2>/dev/null || true
  find /usr/share/ollama/.ollama/models/blobs -name '*partial*' -delete 2>/dev/null || true
  find /mnt/data/ollama/models/blobs -name '*partial*' -delete 2>/dev/null || true
}

prune_output() {
  # hapus folder video TERTUA satu per satu sampai ruang sehat (sisakan min 5 terbaru)
  [ -d "$OUTPUT_DIR" ] || return 0
  while :; do
    local free; free=$(free_mb "$OUTPUT_DIR"); [ -z "$free" ] && break
    [ "$free" -ge "$MIN_FREE_MB" ] && break
    local count; count=$(find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l)
    [ "$count" -le 5 ] && { echo "$(ts) [disk] tersisa <=5 video, stop prune (free=${free}MB)"; break; }
    local oldest; oldest=$(find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
                            | sort -n | head -1 | cut -d' ' -f2-)
    [ -z "$oldest" ] && break
    echo "$(ts) [disk] free=${free}MB < ${MIN_FREE_MB}MB -> hapus output tertua: $(basename "$oldest")"
    rm -rf "$oldest"
  done
}

ROOT_FREE=$(free_mb /)
SSD_FREE=$(free_mb /mnt/data)
if { [ -n "$ROOT_FREE" ] && [ "$ROOT_FREE" -lt "$MIN_FREE_MB" ]; } || \
   { [ -n "$SSD_FREE" ]  && [ "$SSD_FREE" -lt "$MIN_FREE_MB" ]; }; then
  echo "$(ts) [disk] menipis (root=${ROOT_FREE:-?}MB ssd=${SSD_FREE:-?}MB) -> bersih + prune"
  disk_cleanup
  prune_output
fi

# ---------------------------------------------------------------- 4) ollama self-heal (segfault)
# Lib AVX512 'sapphirerapids' / cuda* bisa muncul lagi setelah ollama auto-update
# dan bikin inference SEGFAULT di server CPU-only. Deteksi dari journal lalu pulihkan.
if journalctl -u ollama --since "-6min" 2>/dev/null | grep -qi "segmentation fault\|general protection"; then
  echo "$(ts) [ollama] terdeteksi segfault -> hapus lib bermasalah + restart"
  rm -f  "$OLLAMA_LIB"/libggml-cpu-sapphirerapids.so 2>/dev/null || true
  rm -rf "$OLLAMA_LIB"/cuda_v12 "$OLLAMA_LIB"/cuda_v13 "$OLLAMA_LIB"/vulkan 2>/dev/null || true
  systemctl restart ollama || echo "$(ts) [ollama] gagal restart pasca-segfault"
fi

exit 0
