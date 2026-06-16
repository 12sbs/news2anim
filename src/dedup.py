"""Anti-duplikasi LINTAS-SUMBER.

Mencegah berita yang sama dibuat ulang menjadi video, meskipun datang dari
portal berita yang berbeda (judul & kata berbeda, tapi peristiwa sama).

Cara kerja:
- Tiap berita diringkas menjadi "signature": kumpulan kata kunci penting +
  entitas (nama berhuruf kapital).
- Berita baru dibandingkan dengan semua berita yang pernah diproses memakai
  kemiripan Jaccard (kata kunci & entitas) + kemiripan judul.
- Bila kemiripan melewati ambang -> dianggap DUPLIKAT, video tidak dibuat ulang.

Signature disimpan di state file yang sama (output/state.json -> "stories").
Tanpa library berat (murni Python).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from utils import load_state, log, save_state

# kata umum yang tidak membedakan topik
STOPWORDS = set(
    """the a an and or but for nor so yet of to in on at by with from as is are was
    were be been being has have had do does did will would shall should can could
    may might must this that these those it its他 he she they them his her their our
    your you we i my me not no over after before into out up down new news say says
    said report reports reported according amid over under than then also more most
    one two three first second world today day week year years time people government
    official officials country countries city state president minister told reuters
    bbc guardian npr aljazeera al jazeera""".split()
)


def _entities(text: str) -> set[str]:
    """Ambil entitas sebagai token kapital INDIVIDUAL (nama orang/tempat/organisasi).

    Memecah 'US President Donald Trump' -> {donald, trump} agar cocok dengan
    'Donald Trump' dari sumber lain. Token >=3 huruf, bukan stopword.
    """
    words = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", text)
    return {w.lower() for w in words if w.lower() not in STOPWORDS}


def _keywords(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z]{4,}", text.lower())
    return {t for t in tokens if t not in STOPWORDS}


def signature(article: dict) -> dict:
    """Buat signature berita untuk pembandingan."""
    title = article.get("title", "")
    summary = article.get("summary", "")
    # batasi summary agar entitas/keyword fokus ke inti berita
    head = summary[:600]
    kw = _keywords(title + " " + head)
    ents = _entities(title + " " + head)
    return {
        "id": article.get("id", ""),
        "title": title,
        "norm_title": re.sub(r"[^a-z0-9 ]", "", title.lower()).strip(),
        "keywords": sorted(kw),
        "entities": sorted(ents),
    }


def _overlap(a: set, b: set) -> float:
    """Overlap coefficient (containment): |A∩B| / min(|A|,|B|).

    Lebih cocok dari Jaccard saat panjang dokumen berbeda jauh (artikel penuh
    vs ringkasan) — yang penting apakah inti yang kecil termuat di yang besar.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def similarity(sig_a: dict, sig_b: dict) -> float:
    """Skor kemiripan 0..1 antara dua signature berita."""
    ea, eb = set(sig_a["entities"]), set(sig_b["entities"])
    ka, kb = set(sig_a["keywords"]), set(sig_b["keywords"])
    ent = _overlap(ea, eb)
    kw = _overlap(ka, kb)
    title = SequenceMatcher(None, sig_a["norm_title"], sig_b["norm_title"]).ratio()
    shared_ent = len(ea & eb)

    score = 0.50 * ent + 0.30 * kw + 0.20 * title
    # Pengaman: butuh minimal 2 entitas bersama agar overlap entitas dipercaya
    # (mencegah cocok palsu hanya karena 1 nama umum yang sama).
    if shared_ent < 2:
        score *= 0.5
    return min(score, 1.0)


def is_duplicate(cfg: dict, article: dict) -> tuple[bool, str, float]:
    """Cek apakah berita ini duplikat dari yang sudah diproses.

    Return (duplikat?, judul_yang_cocok, skor).
    """
    thr = cfg.get("dedup", {}).get("similarity_threshold", 0.5)
    sig = signature(article)
    state = load_state(cfg)
    best_score, best_title = 0.0, ""
    for past in state.get("stories", []):
        s = similarity(sig, past)
        if s > best_score:
            best_score, best_title = s, past.get("title", "")
    return (best_score >= thr, best_title, round(best_score, 3))


def record_story(cfg: dict, article: dict) -> None:
    """Simpan signature berita yang sudah dibuat videonya."""
    sig = signature(article)
    state = load_state(cfg)
    state.setdefault("stories", [])
    state["stories"].append(sig)
    # batasi histori agar file tidak membengkak
    state["stories"] = state["stories"][-1000:]
    # jaga kompatibilitas dgn id-based dedup
    state.setdefault("processed_ids", [])
    if sig["id"] not in state["processed_ids"]:
        state["processed_ids"].append(sig["id"])
        state["processed_ids"] = state["processed_ids"][-1000:]
    save_state(cfg, state)


if __name__ == "__main__":
    # uji cepat: dua berita peristiwa SAMA dari sumber berbeda
    from utils import load_config

    cfg = load_config()
    a = {
        "id": "a1",
        "title": "Trump says deal to end war with Iran already signed",
        "summary": "US President Donald Trump announced a deal to end the war with "
        "Iran has been signed at the G7 summit. The Strait of Hormuz will reopen.",
    }
    b = {
        "id": "b2",
        "title": "Iran-US agreement signed, Trump confirms end of conflict",
        "summary": "Donald Trump confirmed that an agreement with Iran was signed, "
        "ending the conflict. Officials said the Strait of Hormuz reopens Friday.",
    }
    c = {
        "id": "c3",
        "title": "South African jazz pianist Abdullah Ibrahim dies aged 91",
        "summary": "The celebrated jazz musician Abdullah Ibrahim has died at 91, "
        "his family said. He was a towering figure in South African music.",
    }
    print("sig A entities:", signature(a)["entities"])
    print("A vs B (sama):", round(similarity(signature(a), signature(b)), 3))
    print("A vs C (beda):", round(similarity(signature(a), signature(c)), 3))
