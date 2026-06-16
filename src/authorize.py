"""Otorisasi YouTube SEKALI -> hasilkan credentials/token.json.

Jalankan di komputer yang PUNYA BROWSER (laptop sendiri paling mudah):
    python src/authorize.py

Langkah:
1. Pastikan credentials/client_secret.json sudah ada (dari Google Cloud Console,
   OAuth Client ID tipe "Desktop app").
2. Skrip membuka browser -> login Google -> izinkan akses -> token tersimpan.
3. Salin credentials/token.json ke server/VPS bila pipeline jalan di sana.

Setelah token.json ada, set youtube.enabled: true di config.yaml.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from utils import load_config, log, resolve

# longgarkan pengecekan scope (Google kadang menambah openid)
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# scope upload = cukup untuk mengunggah video
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
REDIRECT = "http://localhost:8080/"
TMP = "credentials/.oauth_tmp.json"


def _check_secret(client_secret):
    if client_secret.exists():
        return True
    log.error("client_secret.json TIDAK ADA di: %s", client_secret)
    print(
        "\nBuat dulu:\n"
        "1) https://console.cloud.google.com -> buat project\n"
        "2) Aktifkan 'YouTube Data API v3'\n"
        "3) APIs & Services -> Credentials -> Create Credentials ->\n"
        "   OAuth client ID -> Application type: Desktop app\n"
        "4) Download JSON -> simpan sebagai credentials/client_secret.json\n"
    )
    return False


def _save(creds, token_path):
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    log.info("Berhasil! Token tersimpan: %s", token_path)
    print("\n✅ Otorisasi selesai. Set youtube.enabled: true di config.yaml.")


def browser_flow(client_secret, token_path):
    """Untuk komputer dgn browser: server lokal otomatis."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=8080, open_browser=True)
    _save(creds, token_path)


def manual_flow(client_secret, token_path, code_arg: str | None):
    """Server TANPA browser (Codespaces/VPS): DUA langkah via argumen --code.

    Langkah 1 (tanpa --code): cetak URL otorisasi + simpan code_verifier.
    Langkah 2 (dengan --code): tukar kode -> token.json.
    """
    from urllib.parse import parse_qs, urlparse

    from google_auth_oauthlib.flow import Flow

    def _new_flow():
        f = Flow.from_client_secrets_file(
            str(client_secret), scopes=SCOPES, redirect_uri=REDIRECT
        )
        # Matikan PKCE -> penukaran kode tidak butuh code_verifier yg cocok,
        # jadi alur 2-langkah tidak rewel meski dijalankan terpisah.
        f.autogenerate_code_verifier = False
        f.code_verifier = None
        return f

    # ---------- Langkah 1: cetak URL ----------
    if not code_arg:
        flow = _new_flow()
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        print("\n" + "=" * 70)
        print("LANGKAH 1: buka URL ini di browser, login, IZINKAN:\n")
        print(auth_url)
        print("\nLANGKAH 2: browser dialihkan ke http://localhost:8080/?code=...")
        print("(halaman GAGAL dibuka itu NORMAL). Salin URL lengkap dari address")
        print("bar, lalu jalankan lagi perintah ini dengan --code:\n")
        print('  python src/authorize.py --manual --code "<TEMPEL_URL_DI_SINI>"')
        print("=" * 70)
        return

    # ---------- Langkah 2: tukar kode ----------
    flow = _new_flow()
    code = code_arg
    if "code=" in code_arg:
        code = parse_qs(urlparse(code_arg).query).get("code", [code_arg])[0]
    flow.fetch_token(code=code)
    _save(flow.credentials, token_path)


def main():
    ap = argparse.ArgumentParser(description="Otorisasi YouTube -> token.json")
    ap.add_argument("--manual", action="store_true",
                    help="mode tanpa browser (Codespaces/VPS): salin-tempel kode")
    ap.add_argument("--code", default=None,
                    help="(langkah 2) URL/kode hasil otorisasi untuk ditukar token")
    args = ap.parse_args()

    cfg = load_config()
    yt = cfg["youtube"]
    client_secret = resolve(yt["client_secret"])
    token_path = resolve(yt["token"])

    if not _check_secret(client_secret):
        sys.exit(1)
    try:
        if args.manual or args.code:
            manual_flow(client_secret, token_path, args.code)
        else:
            browser_flow(client_secret, token_path)
    except ImportError:
        log.error("Library belum terpasang. Jalankan: pip install -r requirements.txt")
        sys.exit(1)


if __name__ == "__main__":
    main()
