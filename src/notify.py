"""Notifikasi Telegram (best-effort, non-blok).

Mengirim pesan ke chat Telegram lewat Bot API. Dipakai pipeline untuk
memberi tahu setiap siklus pencarian berita dan setiap hasil upload video.

Konfigurasi di config.yaml:

    notify:
      telegram:
        enabled: true
        bot_token: "123456:ABC-DEF..."   # dari @BotFather (atau env TELEGRAM_BOT_TOKEN)
        chat_id: "123456789"             # id chat/grup (atau env TELEGRAM_CHAT_ID)
      on_search: true            # kirim ringkasan tiap siklus pencarian berita
      on_upload: true            # kirim notifikasi tiap video terupload/gagal
      search_skip_if_empty: false  # true = jangan kirim bila tak ada peristiwa baru

Prinsip: GAGAL KIRIM TIDAK BOLEH menghentikan pipeline -> semua exception
ditelan + ditulis ke log. Bila token/chat_id kosong -> diam (return False).

CLI bantu onboarding (jalankan dari root project dengan .venv/bin/python):
    python src/notify.py --getid    # tampilkan chat_id dari pesan terbaru ke bot
    python src/notify.py --test     # kirim pesan tes
"""
from __future__ import annotations

import os
from html import escape

import requests

from utils import log


def _tg(cfg: dict) -> dict:
    return (cfg.get("notify", {}) or {}).get("telegram", {}) or {}


def _creds(cfg: dict) -> tuple[str, str]:
    """Token & chat_id; env var menang atas config (mudah dipakai di systemd)."""
    tg = _tg(cfg)
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg.get("bot_token", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID") or tg.get("chat_id", "")
    return str(token).strip(), str(chat).strip()


def esc(s) -> str:
    """Escape teks dinamis agar aman di parse_mode HTML."""
    return escape(str(s), quote=False)


def enabled(cfg: dict) -> bool:
    """True hanya bila diaktifkan DAN kredensial lengkap."""
    if not _tg(cfg).get("enabled", False):
        return False
    token, chat = _creds(cfg)
    return bool(token and chat)


def flag(cfg: dict, name: str, default: bool = True) -> bool:
    return bool((cfg.get("notify", {}) or {}).get(name, default))


def send(cfg: dict, text: str) -> bool:
    """Kirim pesan teks (HTML) ke Telegram. Best-effort: tak pernah raise."""
    if not enabled(cfg):
        return False
    token, chat = _creds(cfg)
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        if r.status_code != 200:
            log.warning("Telegram gagal kirim (%s): %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram gagal kirim (lanjut): %s", e)
        return False


def get_chat_ids(cfg: dict) -> list[tuple]:
    """Ambil chat_id dari getUpdates (butuh pesan terbaru ke bot). Onboarding."""
    token, _ = _creds(cfg)
    if not token:
        return []
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates", timeout=15
        )
        data = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("getUpdates gagal: %s", e)
        return []
    out = []
    for u in data.get("result", []):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat", {})
        cid = chat.get("id")
        if cid is not None:
            name = (
                chat.get("title")
                or chat.get("username")
                or chat.get("first_name", "")
            )
            pair = (cid, name)
            if pair not in out:
                out.append(pair)
    return out


if __name__ == "__main__":
    import sys

    from utils import load_config

    cfg = load_config(None)
    if "--getid" in sys.argv:
        ids = get_chat_ids(cfg)
        if not ids:
            print("Belum ada update. Kirim /start ke bot dulu, lalu ulangi.")
        for cid, name in ids:
            print(f"{cid}\t{name}")
    elif "--test" in sys.argv:
        ok = send(cfg, "✅ <b>news2anim</b>: tes notifikasi Telegram berhasil.")
        print("Terkirim." if ok else "GAGAL / notifikasi nonaktif (cek token+chat_id).")
    else:
        print("Pakai: python src/notify.py [--getid|--test]")
