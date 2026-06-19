"""Upload video ke YouTube memakai YouTube Data API v3.

Butuh OAuth: file credentials/client_secret.json (dari Google Cloud Console).
Saat pertama jalan akan membuka browser untuk login; token disimpan ke
credentials/token.json sehingga selanjutnya otomatis.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from utils import load_config, log, resolve

# Google kadang menambah/mengubah scope (mis. openid) -> jangan gagal karenanya.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# youtube.upload = unggah video; youtube = set thumbnail kustom (butuh re-auth sekali).
# Saat re-auth (flow pertama) minta KEDUANYA agar thumbnail ikut aktif.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def _yt_safe(text: str) -> str:
    """YouTube menolak '<' / '>' di title & description (invalidTitle/invalidDescription).
    Ganti dengan look-alike Unicode agar teks tetap terbaca, bukan dibuang."""
    return text.replace("<", "‹").replace(">", "›")


def _token_scopes(token_path: Path) -> list[str]:
    """Scope yang BENAR-BENAR ada di token.json (hindari invalid_scope saat refresh).

    Token lama mungkin hanya punya 'youtube.upload'. Memuat creds dengan superset
    SCOPES membuat refresh menolak (invalid_scope) -> upload pun mati. Maka muat
    sesuai scope token; upload tetap jalan, thumbnail aktif otomatis usai re-auth.
    """
    try:
        d = json.loads(token_path.read_text(encoding="utf-8"))
        sc = d.get("scopes") or ([d["scope"]] if d.get("scope") else None)
        if sc:
            return sc
    except Exception:  # noqa: BLE001
        pass
    return SCOPES


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
        creds = Credentials.from_authorized_user_file(
            str(token_path), _token_scopes(token_path)
        )

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
            "title": _yt_safe((yt.get("title_prefix", "") + title)[:100]),
            "description": _yt_safe(description + yt.get("description_footer", "")),
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


def set_thumbnail(cfg: dict, video_id: str, thumb_path: Path) -> bool:
    """Pasang thumbnail kustom pada video. Return True bila sukses.

    Butuh scope 'youtube' (bukan hanya youtube.upload) + channel terverifikasi.
    Bila gagal -> log + return False (pemanggil tidak boleh berhenti karenanya).
    """
    thumb_path = Path(thumb_path)
    if not thumb_path.exists():
        log.warning("Thumbnail tidak ada: %s", thumb_path)
        return False
    from googleapiclient.http import MediaFileUpload

    service = _get_service(cfg)
    media = MediaFileUpload(str(thumb_path), mimetype="image/jpeg")
    service.thumbnails().set(videoId=video_id, media_body=media).execute()
    log.info("Thumbnail dipasang utk %s", video_id)
    return True


def upload_resilient(
    cfg: dict,
    video_path: Path,
    meta: dict,
    thumb_path: Path | None = None,
    max_attempts: int = 3,
) -> tuple[str | None, dict, bool, str]:
    """Upload tahan-gagal (self-heal).

    Alur: deteksi gagal -> identifikasi sebab+lokasi -> perbaiki metadata
    modul terkait -> verifikasi -> retry otomatis. Semua tahap dicatat dgn
    prefix '[self-heal]'.

    Return (video_id|None, meta_terkoreksi, repaired, status) dengan status:
      - "ok"       : berhasil (video_id terisi)
      - "retry"    : gagal SEMENTARA (limit/kuota/5xx) -> layak diantre & diulang
      - "failed"   : gagal permanen / menyerah -> jangan diulang
      - "disabled" : upload YouTube dimatikan di config
    """
    import repair

    yt = cfg["youtube"]
    if not yt.get("enabled"):
        log.info("YouTube upload dimatikan (youtube.enabled=false). Lewati.")
        return (None, meta, False, "disabled")

    from googleapiclient.errors import HttpError

    meta = dict(meta)
    repaired = False
    status = "failed"  # default bila menyerah tanpa sebab yang lebih spesifik

    # Pre-flight: bersihkan SEMUA bidang sebelum hit API bila sudah jelas tak valid.
    ok, problems = repair.verify_metadata(meta)
    if not ok:
        log.warning("[self-heal] pre-flight menemukan masalah: %s", problems)
        meta, ch, notes = repair.repair_all(cfg, meta)
        if ch:
            repaired = True
            log.info("[self-heal] pre-flight perbaikan: %s", notes)

    last_sig = None
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        sig = (meta.get("title"), meta.get("description"), tuple(meta.get("tags") or []))
        if sig == last_sig:
            log.warning("[self-heal] body tak berubah dari percobaan lalu -> berhenti.")
            break
        last_sig = sig

        log.info("[self-heal] percobaan upload %d/%d", attempt, max_attempts)
        try:
            vid_id = upload_video(
                cfg, video_path,
                title=meta["title"],
                description=meta["description"],
                tags=meta.get("tags"),
            )
            if vid_id and thumb_path and yt.get("thumbnail"):
                try:
                    set_thumbnail(cfg, vid_id, Path(thumb_path))
                except Exception as e:  # noqa: BLE001
                    log.error("[self-heal] set thumbnail gagal (lanjut): %s", e)
            return (vid_id, meta, repaired, "ok")
        except HttpError as e:
            errors = repair.parse_youtube_error(e)
            log.error("[self-heal] upload gagal: %s", errors)
            # Cek SEMENTARA dulu: retry segera tak menolong (limit belum reset) ->
            # tandai 'retry' agar pemanggil mengantre & mencoba lagi siklus berikut.
            if any(repair.is_retryable(x["reason"]) for x in errors):
                reasons = [x["reason"] for x in errors]
                log.error("[self-heal] error sementara %s -> antre upload ulang nanti.", reasons)
                status = "retry"
                break
            if any(repair.is_non_fixable(x["reason"]) for x in errors):
                log.error("[self-heal] ada error non-fixable -> berhenti (tak bisa diperbaiki metadata).")
                break
            if not any(repair.is_fixable(x["reason"]) for x in errors):
                log.error("[self-heal] tak ada error yang bisa diperbaiki -> berhenti.")
                break
            meta, changed, notes = repair.repair_metadata(cfg, meta, errors)
            if not changed:
                log.error("[self-heal] perbaikan tak mengubah apa pun -> berhenti.")
                break
            repaired = True
            log.info("[self-heal] perbaikan diterapkan: %s", notes)
            ok, problems = repair.verify_metadata(meta)
            if not ok:
                # Jaring pengaman: bersihkan semua bidang yg masih bermasalah.
                log.warning("[self-heal] masih ada masalah: %s -> bersihkan menyeluruh.", problems)
                meta, _, more = repair.repair_all(cfg, meta)
                if more:
                    log.info("[self-heal] perbaikan menyeluruh: %s", more)
                ok, problems = repair.verify_metadata(meta)
                if not ok:
                    log.error("[self-heal] verifikasi GAGAL pasca-perbaikan: %s", problems)
                    break
            log.info("[self-heal] verifikasi OK -> coba upload ulang.")
        except Exception as e:  # noqa: BLE001
            log.error("[self-heal] error non-HTTP saat upload: %s", e)
            break

    log.error("[self-heal] menyerah setelah %d percobaan.", attempt)
    return (None, meta, repaired, status)


if __name__ == "__main__":
    cfg = load_config()
    final = resolve("output/_final_test.mp4")
    if final.exists():
        upload_video(cfg, final, "Uji Coba news2anim", "Video uji coba.", ["test"])
    else:
        print("Tidak ada video final untuk diupload.")
