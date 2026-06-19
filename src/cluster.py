"""Clustering peristiwa: kelompokkan artikel BARU yang membahas kejadian SAMA.

Tujuan: satu peristiwa -> satu video, dengan fakta dari BANYAK sumber digabung
(lihat merge.py). Mencegah membuat video terpisah untuk berita yang sama.

Memakai ulang signature/similarity dari dedup.py:
- `cluster_articles`  : single-link (transitif) atas batch artikel satu siklus.
- `cluster_signature` : signature gabungan satu cluster (utk cek lintas-siklus).
- `is_cluster_covered`: apakah peristiwa ini sudah pernah dibuat videonya.
- `record_cluster`    : simpan signature cluster + tandai semua id anggota.
"""
from __future__ import annotations

from dedup import signature, similarity
from utils import load_state, log, save_state


# ---------------------------------------------------------------- union-find

class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


# ---------------------------------------------------------------- clustering

def cluster_articles(cfg: dict, articles: list[dict]) -> list[list[dict]]:
    """Kelompokkan artikel jadi cluster peristiwa (single-link/transitif).

    Dua artikel disatukan bila similarity >= cluster.similarity_threshold.
    Transitif: A~B dan B~C -> {A,B,C} meski A tidak langsung mirip C.
    """
    n = len(articles)
    if n <= 1:
        return [list(articles)] if articles else []

    thr = cfg.get("cluster", {}).get("similarity_threshold", 0.55)
    sigs = [signature(a) for a in articles]

    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if similarity(sigs[i], sigs[j]) >= thr:
                uf.union(i, j)

    groups: dict[int, list[dict]] = {}
    for idx, art in enumerate(articles):
        groups.setdefault(uf.find(idx), []).append(art)

    clusters: list[list[dict]] = []
    for members in groups.values():
        # artikel terpanjang (paling kaya fakta) jadi primer -> deterministik
        members.sort(key=lambda a: len(a.get("summary", "")), reverse=True)
        clusters.append(members)

    # cluster dengan sumber terbanyak / teks terbanyak dulu (korroborasi tertinggi)
    clusters.sort(
        key=lambda c: (len(c), sum(len(a.get("summary", "")) for a in c)),
        reverse=True,
    )
    log.info(
        "Clustering: %d artikel -> %d peristiwa (%s)",
        n, len(clusters), ", ".join(str(len(c)) for c in clusters),
    )
    return clusters


# ---------------------------------------------------------------- signature

def cluster_signature(cluster: list[dict]) -> dict:
    """Signature satu cluster: dibangun dari judul terlengkap + gabungan summary.

    Memakai gabungan teks semua anggota -> entitas/kata kunci kaya, sehingga
    pengecekan 'sudah pernah dibuat' lintas-siklus lebih andal.
    """
    if not cluster:
        return signature({"id": "", "title": "", "summary": ""})
    # judul terpanjang = paling informatif
    title = max((a.get("title", "") for a in cluster), key=len, default="")
    merged_summary = " ".join(a.get("summary", "") for a in cluster)[:1500]
    synthetic = {
        "id": cluster[0].get("id", ""),
        "title": title,
        "summary": merged_summary,
    }
    return signature(synthetic)


# ---------------------------------------------------------------- lintas-siklus

def is_cluster_covered(cfg: dict, cluster: list[dict]) -> tuple[bool, str, float]:
    """Apakah peristiwa ini sudah pernah dibuat videonya pada siklus sebelumnya.

    Bandingkan signature gabungan cluster vs semua signature di state['stories'].
    Return (sudah?, judul_yang_cocok, skor).
    """
    thr = cfg.get("dedup", {}).get("similarity_threshold", 0.5)
    sig = cluster_signature(cluster)
    state = load_state(cfg)
    best_score, best_title = 0.0, ""
    for past in state.get("stories", []):
        s = similarity(sig, past)
        if s > best_score:
            best_score, best_title = s, past.get("title", "")
    return (best_score >= thr, best_title, round(best_score, 3))


def record_cluster(cfg: dict, cluster: list[dict]) -> None:
    """Catat peristiwa yang sudah dibuat: signature gabungan + semua id anggota.

    Menggantikan dedup.record_story untuk jalur cluster. Selalu dipanggil pada
    jalur sukses MAUPUN gagal/skip agar peristiwa tak diproses ulang selamanya.
    """
    sig = cluster_signature(cluster)
    state = load_state(cfg)
    state.setdefault("stories", [])
    state["stories"].append(sig)
    state["stories"] = state["stories"][-1000:]

    state.setdefault("processed_ids", [])
    for a in cluster:
        nid = a.get("id", "")
        if nid and nid not in state["processed_ids"]:
            state["processed_ids"].append(nid)
    state["processed_ids"] = state["processed_ids"][-1000:]
    save_state(cfg, state)


# ---------------------------------------------------------------- uji cepat

if __name__ == "__main__":
    from utils import load_config

    cfg = load_config()
    arts = [
        {"id": "a1",
         "title": "Trump says deal to end war with Iran already signed",
         "summary": "US President Donald Trump announced a deal to end the war "
         "with Iran has been signed at the G7 summit. The Strait of Hormuz "
         "will reopen on Friday, officials said."},
        {"id": "b2",
         "title": "Iran-US agreement signed, Trump confirms end of conflict",
         "summary": "Donald Trump confirmed an agreement with Iran was signed, "
         "ending the conflict. Iranian officials said the Strait of Hormuz "
         "reopens Friday and oil shipments resume."},
        {"id": "c3",
         "title": "South African jazz pianist Abdullah Ibrahim dies aged 91",
         "summary": "The celebrated jazz musician Abdullah Ibrahim has died at "
         "91, his family said. He was a towering figure in South African music."},
    ]
    clusters = cluster_articles(cfg, arts)
    print(f"{len(arts)} artikel -> {len(clusters)} cluster")
    for i, c in enumerate(clusters):
        print(f"  cluster {i}: {[a['id'] for a in c]}")
        print(f"    judul-sig: {cluster_signature(c)['title'][:60]}")
