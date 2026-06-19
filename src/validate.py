"""QA berlapis: jaga mutu sebelum upload.

Empat gerbang dipanggil pipeline:
  A. qa_script      - panjang, on-topic, koheren (juri LLM) + scan kata terlarang/kebijakan.
  B. qa_clip        - ukuran, durasi cocok audio, stream audio+video ada, tidak
                      gelap/blank, + moderasi visual AI (opsional).
  C. qa_final       - video final: durasi minimal + stream audio+video ada.
  D. sanitize_meta  - sensor kata terlarang di judul/deskripsi/tag.

Semua degrade anggun: bila alat (ffmpeg/Ollama) tidak ada, cek terkait
DILEWATI (dianggap lolos) agar pipeline tidak crash — bukan menahan video
hanya karena alat bantu mati.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
from pathlib import Path

import requests

from utils import log


# ---------------------------------------------------------------- helper media

def probe_duration(path: Path) -> float:
    """Durasi media (detik) via ffprobe. 0.0 bila gagal/tidak ada ffprobe."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return 0.0


def stream_kinds(path: Path) -> set[str]:
    """Jenis stream pada media: subset dari {'video','audio'}. Kosong bila gagal."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return {ln.strip() for ln in out.stdout.splitlines() if ln.strip()}
    except Exception:  # noqa: BLE001
        return set()


def scan_text_safety(cfg: dict, text: str) -> list[str]:
    """Cari kata terlarang / frasa pelanggaran kebijakan dalam teks."""
    q = cfg.get("qa", {})
    low = (text or "").lower()
    reasons: list[str] = []
    for w in q.get("banned_words", []):
        if w and w.lower() in low:
            reasons.append(f"kata terlarang '{w}'")
    for p in q.get("policy_terms", []):
        if p and p.lower() in low:
            reasons.append(f"frasa kebijakan '{p}'")
    return reasons


_VISION_SYSTEM = (
    "You are a content-safety reviewer for a news channel. Look at the image. "
    'Return ONLY JSON: {"safe": true/false, "reason": "short"}. '
    "Unsafe = graphic gore, explicit sexual content, or hateful symbols. "
    "Normal news scenes (crowds, buildings, maps, officials) are SAFE."
)


def _vision_moderate(cfg: dict, png_bytes: bytes) -> tuple[bool, str]:
    """Moderasi 1 frame via model vision Ollama. Fail-open bila tak tersedia."""
    model = cfg.get("qa", {}).get("vision_model", "")
    if not model:
        return True, ""
    import base64

    sc = cfg["script"]
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0},
        "messages": [
            {"role": "system", "content": _VISION_SYSTEM},
            {"role": "user", "content": "Is this image safe?",
             "images": [base64.b64encode(png_bytes).decode("ascii")]},
        ],
    }
    try:
        r = requests.post(f"{sc['ollama_url']}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        content = r.json()["message"]["content"]
        m = re.search(r"\{.*\}", content, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        if data.get("safe", True):
            return True, ""
        return False, data.get("reason", "ditolak moderasi visual")
    except Exception as e:  # noqa: BLE001
        log.warning("Moderasi visual dilewati (%s).", e)
        return True, ""


def _grab_frame(path: Path, t: float) -> bytes | None:
    """Ambil 1 frame pada detik t sebagai PNG (bytes). None bila gagal."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path),
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
            capture_output=True, check=True,
        )
        return out.stdout or None
    except Exception:  # noqa: BLE001
        return None


def _frame_stats(png_bytes: bytes) -> tuple[float, float] | None:
    """(rata-rata kecerahan, deviasi) frame grayscale 0..255."""
    try:
        from PIL import Image, ImageStat

        im = Image.open(io.BytesIO(png_bytes)).convert("L")
        st = ImageStat.Stat(im)
        return st.mean[0], st.stddev[0]
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- juri (Ollama)

_JUDGE_SYSTEM = """You are a strict QA editor for a factual news video channel.
You receive the source article and the narration script built from it.
Judge the script. Return ONLY valid JSON:
{"ok": true/false, "faithful": true/false, "on_topic": true/false,
 "coherent": true/false, "reason": "short reason"}

Set ok=false if the script invents facts not in the article, drifts off-topic,
is incoherent, or is too short to be a real news segment. Be conservative:
only fail for clear problems."""


def _judge(cfg: dict, article: dict, scenario: dict) -> dict | None:
    sc = cfg["script"]
    treatment = scenario.get("treatment", "")
    # naskah panjang: juri harus melihat keseluruhan, bukan hanya pembuka
    slc = cfg.get("qa", {}).get("judge_max_chars", 1500)
    user = (
        f"ARTICLE TITLE: {article.get('title','')}\n\n"
        f"ARTICLE BODY:\n{article.get('summary','')[:slc]}\n\n"
        f"NARRATION SCRIPT:\n{treatment[:slc]}"
    )
    payload = {
        "model": sc["model"],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
        "messages": [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": user},
        ],
    }
    try:
        r = requests.post(f"{sc['ollama_url']}/api/chat", json=payload, timeout=180)
        r.raise_for_status()
        content = r.json()["message"]["content"]
        m = re.search(r"\{.*\}", content, re.DOTALL)
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # noqa: BLE001
        log.warning("Juri naskah dilewati (Ollama gagal: %s).", e)
        return None


# ---------------------------------------------------------------- Gerbang A

def qa_script(cfg: dict, article: dict, scenario: dict) -> tuple[bool, list[str]]:
    """Gerbang A: nilai naskah. Return (lolos, daftar_alasan_gagal)."""
    q = cfg.get("qa", {})
    reasons: list[str] = []

    scenes = scenario.get("scenes") or []
    if len(scenes) < q.get("min_scenes", 4):
        reasons.append(f"adegan terlalu sedikit ({len(scenes)})")

    words = len((scenario.get("treatment") or "").split())
    if words < q.get("min_script_words", 120):
        reasons.append(f"naskah terlalu pendek ({words} kata)")
    max_words = q.get("max_script_words", 0)
    if max_words and words > max_words:
        reasons.append(f"naskah terlalu panjang ({words} kata > {max_words})")

    if any(not (s.get("text") or "").strip() for s in scenes):
        reasons.append("ada adegan tanpa teks")

    # keamanan teks: kata terlarang / frasa pelanggaran kebijakan (naskah + adegan)
    safety = scan_text_safety(cfg, scenario.get("treatment", ""))
    for s in scenes:
        safety += scan_text_safety(cfg, s.get("text", ""))
    reasons += list(dict.fromkeys(safety))

    # juri LLM (opsional, hanya bila Ollama hidup)
    if q.get("use_judge", True) and cfg["script"].get("use_ollama"):
        verdict = _judge(cfg, article, scenario)
        if verdict is not None and not verdict.get("ok", True):
            why = verdict.get("reason", "naskah ditolak juri")
            if not verdict.get("faithful", True):
                why = "tidak setia fakta: " + why
            elif not verdict.get("on_topic", True):
                why = "keluar topik: " + why
            reasons.append(why)

    return (not reasons, reasons)


# ---------------------------------------------------------------- Gerbang B

def qa_clip(cfg: dict, clip_path: Path, wav_path: Path | None
            ) -> tuple[bool, list[str]]:
    """Gerbang B: cek satu klip adegan."""
    q = cfg.get("qa", {})
    reasons: list[str] = []
    clip_path = Path(clip_path)

    if not clip_path.exists():
        return (False, ["klip tidak ada"])
    size = clip_path.stat().st_size
    if size < q.get("min_clip_bytes", 20000):
        reasons.append(f"file klip terlalu kecil ({size} byte)")

    vdur = probe_duration(clip_path)
    if vdur <= 0:
        reasons.append("durasi klip tidak terbaca")
    elif wav_path and Path(wav_path).exists():
        adur = probe_duration(Path(wav_path))
        tol = q.get("clip_dur_tolerance", 0.7)
        if adur > 0 and abs(vdur - adur) > tol:
            reasons.append(
                f"durasi klip {vdur:.1f}s tidak cocok audio {adur:.1f}s"
            )

    # cek gelap/blank: ambil frame paling terang dari beberapa sampel
    if vdur > 0:
        best_mean, best_std = 0.0, 0.0
        for frac in (0.15, 0.5, 0.85):
            stats = None
            png = _grab_frame(clip_path, max(0.0, vdur * frac))
            if png:
                stats = _frame_stats(png)
            if stats:
                best_mean = max(best_mean, stats[0])
                best_std = max(best_std, stats[1])
        # hanya menilai bila ada frame yang berhasil dibaca
        if (best_mean or best_std):
            if best_mean < q.get("blank_luma_min", 12):
                reasons.append(f"frame terlalu gelap (luma {best_mean:.1f})")
            elif best_std < q.get("blank_std_min", 3):
                reasons.append(f"frame polos/blank (std {best_std:.1f})")

    # stream audio + video harus ada (tolak klip rusak/diam)
    kinds = stream_kinds(clip_path)
    if kinds:
        if "video" not in kinds:
            reasons.append("klip tanpa stream video")
        if "audio" not in kinds:
            reasons.append("klip tanpa stream audio")

    # moderasi visual AI (opsional, bila qa.vision_model di-set)
    if vdur > 0 and q.get("vision_model"):
        png = _grab_frame(clip_path, max(0.0, vdur * 0.5))
        if png:
            ok_v, why = _vision_moderate(cfg, png)
            if not ok_v:
                reasons.append("moderasi visual: " + (why or "tidak aman"))

    return (not reasons, reasons)


# ---------------------------------------------------------------- Gerbang C

def qa_final(cfg: dict, final_path: Path) -> tuple[bool, list[str]]:
    """Gerbang C: video final cukup panjang + utuh (ada video & audio)."""
    reasons: list[str] = []
    final_path = Path(final_path)
    min_dur = cfg["video"].get("min_duration_sec", 0)
    dur = probe_duration(final_path)
    if min_dur and dur and dur < min_dur:
        reasons.append(
            f"durasi final {dur:.0f}s < target {min_dur}s "
            "(naikkan script.target_words / max_scenes)"
        )
    kinds = stream_kinds(final_path)
    if kinds:
        if "video" not in kinds:
            reasons.append("video final tanpa stream video")
        if "audio" not in kinds:
            reasons.append("video final tanpa stream audio")
    return (not reasons, reasons)


# ---------------------------------------------------------------- Gerbang D

def sanitize_metadata(cfg: dict, meta: dict) -> tuple[dict, bool, list[str]]:
    """Gerbang D: sensor kata terlarang. Return (meta_bersih, berubah?, alasan)."""
    banned = [w.lower().strip() for w in cfg.get("qa", {}).get("banned_words", []) if w]
    if not banned:
        return (meta, False, [])

    reasons: list[str] = []
    changed = False

    def _scrub(text: str) -> str:
        nonlocal changed
        for w in banned:
            pat = re.compile(re.escape(w), re.IGNORECASE)
            if pat.search(text):
                text = pat.sub("[redacted]", text)
                changed = True
                reasons.append(f"sensor '{w}'")
        return text

    meta["title"] = _scrub(str(meta.get("title", "")))
    meta["description"] = _scrub(str(meta.get("description", "")))
    clean_tags = []
    for t in meta.get("tags", []):
        tl = str(t).lower()
        if any(w in tl for w in banned):
            changed = True
            reasons.append(f"buang tag '{t}'")
            continue
        clean_tags.append(t)
    meta["tags"] = clean_tags

    return (meta, changed, list(dict.fromkeys(reasons)))


if __name__ == "__main__":
    from utils import load_config

    cfg = load_config()
    # uji Gerbang D (murni, tanpa media)
    m = {"title": "How to make a bomb at home", "description": "safe news",
         "tags": ["news", "how to make a bomb"]}
    out, ch, why = sanitize_metadata(cfg, m)
    print("changed:", ch, "| reasons:", why)
    print(json.dumps(out, ensure_ascii=False, indent=2))
