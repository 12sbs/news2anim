"""Self-heal metadata upload YouTube.

Saat upload gagal karena metadata tak valid (mis. 'invalidDescription'),
modul ini: (1) mengurai error -> sebab + lokasi, (2) menentukan modul
penanggung jawab, (3) memperbaiki metadata, (4) memverifikasi hasilnya.
Tidak pernah raise: selalu kembalikan tuple agar pemanggil aman.
"""
from __future__ import annotations

import json
import re

from upload import _yt_safe
from utils import log

# Batas keras YouTube (description sebenarnya 5000; title 100).
MAX_TITLE = 100
MAX_DESC = 5000
MAX_TAG = 30
MAX_TAGS_TOTAL = 500

# Modul yang "bertanggung jawab" atas tiap jenis error -> dipakai utk log lokasi.
RESPONSIBLE = {
    "invalidDescription": "seo (description)",
    "invalidTitle": "seo (title)",
    "invalidTags": "seo (tags)",
    "invalidVideoMetadata": "seo (tags/metadata)",
}

# Error yang BISA diperbaiki dengan menyunting metadata.
FIXABLE = {"invalidDescription", "invalidTitle", "invalidTags", "invalidVideoMetadata"}
# Error SEMENTARA: bukan salah metadata, sembuh sendiri saat limit/kuota reset.
# Jangan dibuang -> video diantre untuk dicoba upload ulang siklus berikutnya.
RETRYABLE = {
    "uploadLimitExceeded",      # plafon jumlah upload harian channel tercapai
    "uploadRateLimitExceeded",  # terlalu banyak upload (mis. thumbnail) baru-baru ini
    "rateLimitExceeded",        # 429 umum
    "quotaExceeded",            # kuota API harian habis -> reset esok hari
    "backendError", "internalError", "serviceUnavailable",  # 5xx sisi YouTube
}
# Error PERMANEN: tak bisa diperbaiki metadata maupun ditunggu -> menyerah.
NON_FIXABLE = {
    "forbidden", "authError", "insufficientPermissions",
}

# control chars yang harus dibuang (sisakan \t \n \r).
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def is_fixable(reason: str) -> bool:
    return reason in FIXABLE


def is_non_fixable(reason: str) -> bool:
    return reason in NON_FIXABLE


def is_retryable(reason: str) -> bool:
    """Error sementara (limit/kuota/5xx) yang layak dicoba ulang nanti."""
    return reason in RETRYABLE


def parse_youtube_error(exc) -> list[dict]:
    """Urai googleapiclient HttpError -> [{reason, location, message}].

    Tahan banting: bila konten bukan JSON / tak lengkap, sintesis dari status
    HTTP. Selalu kembalikan minimal 1 entri.
    """
    out: list[dict] = []
    content = getattr(exc, "content", None)
    try:
        if isinstance(content, (bytes, bytearray)):
            content = content.decode("utf-8", "replace")
        data = json.loads(content) if content else {}
        for e in (data.get("error", {}) or {}).get("errors", []) or []:
            out.append({
                "reason": e.get("reason", ""),
                "location": e.get("location", ""),
                "message": e.get("message", ""),
            })
    except (ValueError, TypeError, AttributeError):
        pass

    if not out:
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "resp", None), "status", None)
        reason = {403: "forbidden", 429: "rateLimitExceeded",
                  400: "badRequest"}.get(status)
        if reason is None and isinstance(status, int) and status >= 500:
            reason = "backendError"
        out.append({
            "reason": reason or "unknown",
            "location": "",
            "message": str(exc)[:200],
        })
    return out


# ----------------------------------------------------------- handler perbaikan

def _repair_description(cfg: dict, meta: dict) -> tuple[dict, bool, str]:
    old = str(meta.get("description", ""))
    new = _CTRL.sub("", _yt_safe(old))[:MAX_DESC]
    if new == old:
        return (meta, False, "")
    meta["description"] = new
    return (meta, True, f"{RESPONSIBLE['invalidDescription']}: bersihkan '<>'/ctrl, potong {MAX_DESC}")


def _repair_title(cfg: dict, meta: dict) -> tuple[dict, bool, str]:
    old = str(meta.get("title", ""))
    new = _CTRL.sub("", _yt_safe(old)).strip()[:MAX_TITLE]
    if not new:
        new = "Berita Animasi"
    if new == old:
        return (meta, False, "")
    meta["title"] = new
    return (meta, True, f"{RESPONSIBLE['invalidTitle']}: bersihkan '<>'/ctrl, potong {MAX_TITLE}")


def _repair_tags(cfg: dict, meta: dict) -> tuple[dict, bool, str]:
    old = list(meta.get("tags", []) or [])
    clean: list[str] = []
    total = 0
    for t in old:
        ts = str(t)
        if "<" in ts or ">" in ts or len(ts) > MAX_TAG:
            continue
        # +1 perkiraan pemisah; jaga total di bawah anggaran YouTube.
        if total + len(ts) + 1 > MAX_TAGS_TOTAL:
            break
        clean.append(t)
        total += len(ts) + 1
    if clean == old:
        return (meta, False, "")
    meta["tags"] = clean
    return (meta, True, f"{RESPONSIBLE['invalidTags']}: buang tag '<>'/kepanjangan")


REPAIRS = {
    "invalidDescription": _repair_description,
    "invalidTitle": _repair_title,
    "invalidTags": _repair_tags,
    "invalidVideoMetadata": _repair_tags,
}


def repair_metadata(cfg: dict, meta: dict, errors: list[dict]) -> tuple[dict, bool, list[str]]:
    """Terapkan perbaikan utk tiap error. Return (meta, berubah?, catatan)."""
    meta = dict(meta)
    changed = False
    notes: list[str] = []
    for e in errors:
        reason = e.get("reason", "")
        fn = REPAIRS.get(reason)
        if fn is None:
            notes.append(f"tak ada perbaikan utk '{reason}'")
            continue
        meta, ch, note = fn(cfg, meta)
        if ch:
            changed = True
            if note:
                notes.append(note)
    return (meta, changed, list(dict.fromkeys(notes)))


def repair_all(cfg: dict, meta: dict) -> tuple[dict, bool, list[str]]:
    """Bersihkan SEMUA bidang (title/description/tags) tanpa menunggu error
    spesifik dari YouTube. Dipakai utk pre-flight & sebagai jaring pengaman
    agar verify_metadata pasti lolos sebelum menyerah."""
    meta = dict(meta)
    changed = False
    notes: list[str] = []
    for fn in (_repair_title, _repair_description, _repair_tags):
        meta, ch, note = fn(cfg, meta)
        if ch:
            changed = True
            if note:
                notes.append(note)
    return (meta, changed, list(dict.fromkeys(notes)))


def verify_metadata(meta: dict) -> tuple[bool, list[str]]:
    """Cek ulang aturan YouTube (langkah verifikasi & pre-flight)."""
    problems: list[str] = []
    title = str(meta.get("title", ""))
    desc = str(meta.get("description", ""))
    if not title.strip():
        problems.append("title kosong")
    if len(title) > MAX_TITLE:
        problems.append(f"title > {MAX_TITLE}")
    if "<" in title or ">" in title:
        problems.append("title memuat '<' / '>'")
    if len(desc) > MAX_DESC:
        problems.append(f"description > {MAX_DESC}")
    if "<" in desc or ">" in desc:
        problems.append("description memuat '<' / '>'")
    for t in meta.get("tags", []) or []:
        if "<" in str(t) or ">" in str(t):
            problems.append("tag memuat '<' / '>'")
            break
    return (not problems, problems)


if __name__ == "__main__":
    # Dry sim: tanpa jaringan. Tiru error 400 invalidDescription yang nyata.
    class _FakeErr(Exception):
        content = json.dumps({"error": {"errors": [{
            "message": "The request metadata specifies an invalid video description.",
            "domain": "youtube.video",
            "reason": "invalidDescription",
            "location": "body.snippet.description",
        }]}}).encode()
        status_code = 400

    meta = {
        "title": "Trump's Memo with Iran vs Obama Deal Explained",
        "description": "Sources:\n- NYT > World News: https://example.com",
        "tags": ["iran", "trump", "bad<tag>"],
    }
    errs = parse_youtube_error(_FakeErr())
    print("parsed:", errs)
    # 1) Perbaikan tertarget sesuai keluhan YouTube (di sini: description).
    fixed, changed, notes = repair_metadata({}, meta, errs)
    print("repair tertarget -> changed:", changed, "| notes:", notes)
    ok, probs = verify_metadata(fixed)
    print("verify setelah tertarget:", ok, "| problems:", probs)
    # 2) Jaring pengaman: bersihkan semua bidang (mis. tag ber-'<>').
    if not ok:
        fixed, ch2, notes2 = repair_all({}, fixed)
        print("repair menyeluruh -> changed:", ch2, "| notes:", notes2)
        ok, probs = verify_metadata(fixed)
    print("verify FINAL:", ok, "| problems:", probs)
    print(json.dumps(fixed, ensure_ascii=False, indent=2))
