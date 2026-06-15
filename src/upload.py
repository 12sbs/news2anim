"""Upload video ke YouTube memakai YouTube Data API v3.

Butuh OAuth: file credentials/client_secret.json (dari Google Cloud Console).
Saat pertama jalan akan membuka browser untuk login; token disimpan ke
credentials/token.json sehingga selanjutnya otomatis.
"""
from __future__ import annotations

from pathlib import Path

from utils import load_config, log, resolve

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _get_service(cfg: dict):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    yt = cfg["youtube"]
    client_secret = resolve(yt["client_secret"])
    token_path = resolve(yt["token"])

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_secret.exists():
                raise FileNotFoundError(
                    f"client_secret.json tidak ada di {client_secret}. "
                    "Buat OAuth Client (Desktop) di Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secret), SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=creds)


def upload_video(
    cfg: dict,
    video_path: Path,
    title: str,
    description: str,
    tags: list[str] | None = None,
) -> str | None:
    yt = cfg["youtube"]
    if not yt.get("enabled"):
        log.info("YouTube upload dimatikan (youtube.enabled=false). Lewati.")
        return None

    from googleapiclient.http import MediaFileUpload

    service = _get_service(cfg)
    body = {
        "snippet": {
            "title": (yt.get("title_prefix", "") + title)[:100],
            "description": description + yt.get("description_footer", ""),
            "tags": tags or yt.get("tags", []),
            "categoryId": str(yt.get("category_id", "25")),
        },
        "status": {"privacyStatus": yt.get("privacy", "private")},
    }
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    log.info("Mengupload ke YouTube: %s", title)
    request = service.videos().insert(
        part="snippet,status", body=body, media_body=media
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("Upload %d%%", int(status.progress() * 100))
    vid_id = response.get("id")
    log.info("Selesai. https://youtu.be/%s", vid_id)
    return vid_id


if __name__ == "__main__":
    cfg = load_config()
    final = resolve("output/_final_test.mp4")
    if final.exists():
        upload_video(cfg, final, "Uji Coba news2anim", "Video uji coba.", ["test"])
    else:
        print("Tidak ada video final untuk diupload.")
