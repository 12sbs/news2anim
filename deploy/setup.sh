#!/usr/bin/env bash
# ============================================================================
#  news2anim — setup turnkey (VPS Ubuntu/Debian)
#
#  Pasang SEMUA komponen, unduh model, lalu nyalakan service 24/7 (mode --watch).
#  Jalankan:  sudo bash deploy/setup.sh
#
#  IDEMPOTEN — aman dijalankan ulang; yang sudah ada dilewati.
# ============================================================================
set -euo pipefail

# ----------------------------------------------------------------------------
#  Variabel yang bisa diubah (ganti versi/model di sini)
# ----------------------------------------------------------------------------
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"       # model LLM naskah (aman utk RAM ~8GB)
RHUBARB_VER="${RHUBARB_VER:-1.13.0}"             # versi Rhubarb lip-sync
PIPER_VOICE="${PIPER_VOICE:-en_US-lessac-medium}"  # nama model suara Piper

# Lokasi sumber model suara Piper (HuggingFace rhasspy/piper-voices)
PIPER_VOICE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

# ----------------------------------------------------------------------------
#  Deteksi path & user (skrip dijalankan via sudo -> kembalikan ke user asli)
# ----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

RUN_USER="${SUDO_USER:-$(id -un)}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
VENV="$PROJECT_DIR/.venv"

c_green="\033[1;32m"; c_yellow="\033[1;33m"; c_red="\033[1;31m"; c_reset="\033[0m"
say()  { echo -e "${c_green}==>${c_reset} $*"; }
warn() { echo -e "${c_yellow}!! ${c_reset} $*"; }
err()  { echo -e "${c_red}XX ${c_reset} $*" >&2; }

# Jalankan perintah sebagai user asli (bukan root)
as_user() { sudo -u "$RUN_USER" -H "$@"; }

if [[ "$(id -u)" -ne 0 ]]; then
  err "Skrip ini butuh root. Jalankan: sudo bash deploy/setup.sh"
  exit 1
fi

say "Project : $PROJECT_DIR"
say "User    : $RUN_USER ($RUN_HOME)"
say "Model   : ollama=$OLLAMA_MODEL  rhubarb=$RHUBARB_VER  piper=$PIPER_VOICE"
echo

# ============================================================================
#  Langkah 1 — Paket sistem (apt)
# ============================================================================
say "[1/7] Memasang paket sistem (ffmpeg, python, git, curl, wget, unzip)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  ffmpeg python3 python3-venv python3-pip git curl wget unzip ca-certificates

# ============================================================================
#  Langkah 2 — Virtualenv + requirements + Piper TTS (pip)
# ============================================================================
say "[2/7] Menyiapkan virtualenv (.venv) + dependensi Python..."
if [[ ! -d "$VENV" ]]; then
  as_user python3 -m venv "$VENV"
else
  warn ".venv sudah ada — dilewati pembuatan."
fi
as_user "$VENV/bin/pip" install --upgrade pip wheel
as_user "$VENV/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
# Piper TTS (suara). Paket pip menyediakan binary 'piper' di .venv/bin/.
as_user "$VENV/bin/pip" install piper-tts
# Buat 'piper' tersedia global agar config (tts.piper_bin: piper) jalan
# baik dari service maupun saat uji manual.
ln -sf "$VENV/bin/piper" /usr/local/bin/piper
say "Piper terpasang: $(/usr/local/bin/piper --version 2>/dev/null || echo 'ok')"

# ============================================================================
#  Langkah 3 — Ollama + model LLM
# ============================================================================
say "[3/7] Memasang Ollama + model $OLLAMA_MODEL..."
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
else
  warn "Ollama sudah terpasang — dilewati instalasi."
fi
# Pastikan service ollama hidup sebelum pull
systemctl enable --now ollama 2>/dev/null || true
# Tunggu API siap (maks ~30 dtk)
for _ in $(seq 1 30); do
  curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1 && break
  sleep 1
done
if as_user ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL%%:*}"; then
  warn "Model $OLLAMA_MODEL sudah ada — dilewati pull."
else
  as_user ollama pull "$OLLAMA_MODEL"
fi

# ============================================================================
#  Langkah 4 — Rhubarb lip-sync -> /usr/local/bin
# ============================================================================
say "[4/7] Memasang Rhubarb lip-sync v$RHUBARB_VER..."
if command -v rhubarb >/dev/null 2>&1; then
  warn "Rhubarb sudah terpasang ($(command -v rhubarb)) — dilewati."
else
  RB_ZIP="/tmp/rhubarb-${RHUBARB_VER}.zip"
  RB_URL="https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v${RHUBARB_VER}/Rhubarb-Lip-Sync-${RHUBARB_VER}-Linux.zip"
  wget -qO "$RB_ZIP" "$RB_URL"
  rm -rf /opt/rhubarb
  mkdir -p /opt/rhubarb
  # Zip berisi folder Rhubarb-Lip-Sync-<ver>-Linux/ (binary + res/)
  unzip -q "$RB_ZIP" -d /tmp/rhubarb-extract
  mv /tmp/rhubarb-extract/Rhubarb-Lip-Sync-*/* /opt/rhubarb/
  chmod +x /opt/rhubarb/rhubarb
  # Symlink: rhubarb mencari folder res/ relatif ke path asli binary -> tetap ketemu.
  ln -sf /opt/rhubarb/rhubarb /usr/local/bin/rhubarb
  rm -rf "$RB_ZIP" /tmp/rhubarb-extract
  say "Rhubarb: $(/usr/local/bin/rhubarb --version 2>/dev/null | head -1 || echo ok)"
fi

# ============================================================================
#  Langkah 5 — Model suara Piper -> models/
# ============================================================================
say "[5/7] Mengunduh model suara Piper ($PIPER_VOICE)..."
MODELS_DIR="$PROJECT_DIR/models"
as_user mkdir -p "$MODELS_DIR"
for ext in onnx onnx.json; do
  dst="$MODELS_DIR/${PIPER_VOICE}.${ext}"
  if [[ -s "$dst" ]]; then
    warn "${PIPER_VOICE}.${ext} sudah ada — dilewati."
  else
    as_user wget -qO "$dst" "${PIPER_VOICE_URL}/${PIPER_VOICE}.${ext}"
  fi
done
chown -R "$RUN_USER":"$RUN_USER" "$MODELS_DIR"

# ============================================================================
#  Langkah 6 — Cek kredensial YouTube (peringatan bila hilang)
# ============================================================================
say "[6/7] Memeriksa kredensial YouTube..."
CRED_DIR="$PROJECT_DIR/credentials"
miss=0
for f in client_secret.json token.json; do
  if [[ ! -s "$CRED_DIR/$f" ]]; then
    warn "credentials/$f TIDAK ADA."
    miss=1
  fi
done
if [[ "$miss" -eq 1 ]]; then
  warn "Upload YouTube TIDAK akan jalan sampai kedua file disalin ke credentials/."
  warn "Salin dari mesin lama:  scp credentials/*.json $RUN_USER@<VPS_IP>:$CRED_DIR/"
  warn "Untuk uji tanpa upload:  $VENV/bin/python src/pipeline.py --no-upload"
else
  say "Kredensial YouTube lengkap."
fi

# ============================================================================
#  Langkah 7 — Service systemd (mode --watch, 24/7)
# ============================================================================
say "[7/7] Memasang service systemd news2anim (mode --watch)..."
UNIT=/etc/systemd/system/news2anim.service
TEMPLATE="$SCRIPT_DIR/news2anim.service"
if [[ -f "$TEMPLATE" ]]; then
  # render template (ganti placeholder) -> unit file
  sed -e "s#__USER__#$RUN_USER#g" \
      -e "s#__PROJECT_DIR__#$PROJECT_DIR#g" \
      -e "s#__VENV__#$VENV#g" \
      "$TEMPLATE" > "$UNIT"
else
  warn "Template news2anim.service tidak ada -> tulis unit inline."
  cat > "$UNIT" <<EOF
[Unit]
Description=news2anim — auto news-to-animation pipeline (watch mode)
After=network-online.target ollama.service
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$VENV/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$VENV/bin/python src/pipeline.py --watch
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF
fi

systemctl daemon-reload
systemctl enable --now news2anim

# Watchdog (jaring pengaman di atas systemd) — pasang cron ROOT tiap 5 menit
WATCHDOG="$SCRIPT_DIR/watchdog.sh"
if [[ -f "$WATCHDOG" ]]; then
  chmod +x "$WATCHDOG"
  CRON_LINE="*/5 * * * * $WATCHDOG >> /var/log/news2anim_watchdog.log 2>&1"
  if ! (crontab -l 2>/dev/null | grep -Fq "$WATCHDOG"); then
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    say "Watchdog cron terpasang (cek tiap 5 menit)."
  else
    warn "Watchdog cron sudah ada — dilewati."
  fi
fi

echo
say "Selesai! 🎉 Service news2anim aktif (auto-restart, 24/7)."
echo "  Log langsung : journalctl -u news2anim -f"
echo "  Status       : systemctl status news2anim"
echo "  Stop/start   : sudo systemctl stop|start news2anim"
echo "  Watchdog log : /var/log/news2anim_watchdog.log"
echo
if [[ "$miss" -eq 1 ]]; then
  warn "INGAT: kredensial YouTube belum lengkap -> video dibuat tapi belum ter-upload."
fi
