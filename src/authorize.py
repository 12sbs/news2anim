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

import sys

from utils import load_config, log, resolve

# scope upload = cukup untuk mengunggah video
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    cfg = load_config()
    yt = cfg["youtube"]
    client_secret = resolve(yt["client_secret"])
    token_path = resolve(yt["token"])

    if not client_secret.exists():
        log.error("client_secret.json TIDAK ADA di: %s", client_secret)
        print(
            "\nBuat dulu:\n"
            "1) https://console.cloud.google.com -> buat project\n"
            "2) Aktifkan 'YouTube Data API v3'\n"
            "3) APIs & Services -> Credentials -> Create Credentials ->\n"
            "   OAuth client ID -> Application type: Desktop app\n"
            "4) Download JSON -> simpan sebagai credentials/client_secret.json\n"
        )
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        log.error("Library belum terpasang. Jalankan: pip install -r requirements.txt")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    # port tetap 8080 -> tambahkan http://localhost:8080/ sebagai Authorized
    # redirect URI bila diminta. Di laptop, browser akan terbuka otomatis.
    creds = flow.run_local_server(port=8080, open_browser=True)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    log.info("Berhasil! Token tersimpan: %s", token_path)
    print("\n✅ Otorisasi selesai. Sekarang set youtube.enabled: true di config.yaml.")


if __name__ == "__main__":
    main()
