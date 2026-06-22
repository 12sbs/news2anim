"""Penjadwal upload bertahap (drip) di jam tayang prime.

Tujuan: saat kuota YouTube pulih, video tertunda TIDAK diunggah sekaligus,
melainkan 1 video per slot di jam-jam ramai menonton -> channel terlihat
natural & tiap video dapat impresi maksimal.

Mode ADAPTIF (config.upload_schedule.adaptive=true):
  Tarik komposisi NEGARA penonton channel dari YouTube Analytics (views per
  country) -> petakan tiap negara ke jam prime LOKAL-nya (prime_local_hours)
  -> konversi ke UTC pakai tabel offset -> akumulasi bobot per jam UTC ->
  pilih `slots_per_day` jam berbobot tertinggi.

Fallback (Analytics tak tersedia / scope belum diberikan / data belum cukup):
  pakai `preset_utc_hours` dari config (fokus US + UK).

Catatan: YouTube Analytics API TIDAK punya dimensi jam-dalam-sehari, sehingga
jam ramai disimpulkan dari negara penonton, bukan dibaca langsung.

Slot hasil hitung di-cache di state.json (`upload_slots`) dan diperbarui sekali
per hari (UTC) agar tidak memanggil Analytics tiap siklus.
"""
from __future__ import annotations

from datetime import datetime, timezone

from utils import load_state, log, save_state

# Offset UTC (jam) per kode negara ISO-3166 alpha-2. Dipakai memetakan jam prime
# lokal -> UTC. Cukup negara berbahasa Inggris/penonton berita dunia terbesar;
# negara tak terdaftar memakai DEFAULT_OFFSET. Negara multi-zona dipakai zona
# populasi terpadat (mis. US -> ET, AU -> AEST) — pendekatan praktis, bukan presisi.
COUNTRY_UTC_OFFSET: dict[str, float] = {
    "US": -5.0,   # Eastern (mayoritas penonton AS)
    "GB": 0.0,    # UK
    "CA": -5.0,   # Eastern Canada
    "IN": 5.5,    # India
    "AU": 10.0,   # Sydney/Melbourne (AEST)
    "IE": 0.0,    # Ireland
    "NZ": 12.0,   # New Zealand
    "ZA": 2.0,    # South Africa
    "NG": 1.0,    # Nigeria
    "PH": 8.0,    # Philippines
    "SG": 8.0,    # Singapore
    "PK": 5.0,    # Pakistan
    "DE": 1.0,    # Germany
    "FR": 1.0,    # France
    "NL": 1.0,    # Netherlands
    "BR": -3.0,   # Brazil
}
DEFAULT_OFFSET = 0.0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Analytics: komposisi negara penonton
# --------------------------------------------------------------------------
def country_weights(cfg: dict) -> dict[str, float] | None:
    """Bobot negara penonton (views) dari YouTube Analytics.

    Return {kode_negara: views} atau None bila tak tersedia (scope belum
    diberikan, paket belum terpasang, atau channel tanpa data). Pemanggil
    harus menangani None dengan fallback preset.
    """
    sched = cfg.get("upload_schedule", {})
    lookback = int(sched.get("analytics_lookback_days", 90))
    try:
        from upload import get_analytics_service  # lazy: hindari import siklik
    except Exception as e:  # noqa: BLE001
        log.info("[jadwal] Analytics tak tersedia (%s) -> pakai preset.", e)
        return None

    service = get_analytics_service(cfg)
    if service is None:
        return None

    end = _now_utc().date()
    start_ordinal = end.toordinal() - lookback
    start = datetime.fromordinal(start_ordinal).date()
    try:
        resp = (
            service.reports()
            .query(
                ids="channel==MINE",
                startDate=start.isoformat(),
                endDate=end.isoformat(),
                metrics="views",
                dimensions="country",
                sort="-views",
                maxResults=25,
            )
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        log.warning("[jadwal] query Analytics gagal (%s) -> pakai preset.", e)
        return None

    # Saring ke negara berbahasa-Inggris sehari-hari (bila daftar diisi di config).
    allow = {c.upper() for c in sched.get("english_countries", []) if c}
    rows = resp.get("rows") or []
    weights: dict[str, float] = {}
    for row in rows:
        try:
            country, views = row[0], float(row[1])
        except (IndexError, TypeError, ValueError):
            continue
        if allow and country.upper() not in allow:
            continue
        if views > 0:
            weights[country] = views
    if not weights:
        log.info(
            "[jadwal] Analytics tanpa data negara berbahasa-Inggris -> pakai preset."
        )
        return None
    return weights


# --------------------------------------------------------------------------
# Hitung slot jam (UTC)
# --------------------------------------------------------------------------
def _slots_from_weights(
    weights: dict[str, float], prime_local: list[int], n_slots: int
) -> list[int]:
    """Ubah bobot negara -> daftar jam UTC terbaik (panjang n_slots)."""
    hour_score: dict[int, float] = {h: 0.0 for h in range(24)}
    for country, w in weights.items():
        off = COUNTRY_UTC_OFFSET.get(country.upper(), DEFAULT_OFFSET)
        for lh in prime_local:
            utc_h = int(round(lh - off)) % 24
            hour_score[utc_h] += w
    # urutkan: skor tertinggi dulu; seri -> jam lebih awal agar deterministik
    ranked = sorted(hour_score.items(), key=lambda kv: (-kv[1], kv[0]))
    best = [h for h, s in ranked if s > 0][:n_slots]
    best.sort()
    return best


def _normalize_preset(preset: list[int], n_slots: int) -> list[int]:
    seen: list[int] = []
    for h in preset:
        h = int(h) % 24
        if h not in seen:
            seen.append(h)
    seen.sort()
    return seen[:n_slots]


def compute_slots(cfg: dict, force: bool = False) -> list[int]:
    """Daftar jam UTC (terurut) tempat upload boleh terjadi.

    Hasil di-cache di state['upload_slots'] dengan tanggal hitung; diperbarui
    sekali per hari UTC. `force=True` mengabaikan cache (mis. untuk uji).
    """
    sched = cfg.get("upload_schedule", {})
    n_slots = int(sched.get("slots_per_day", 11))
    preset = _normalize_preset(
        sched.get("preset_utc_hours", []) or list(range(24)), n_slots
    )

    today = _now_utc().date().isoformat()
    state = load_state(cfg)
    cache = state.get("upload_slots") or {}
    if not force and cache.get("date") == today and cache.get("hours"):
        return cache["hours"]

    hours = preset
    source = "preset"
    if sched.get("adaptive", True):
        weights = country_weights(cfg)
        if weights:
            adaptive_hours = _slots_from_weights(
                weights, sched.get("prime_local_hours", [17, 18, 19, 20, 21]),
                n_slots,
            )
            if adaptive_hours:
                hours = adaptive_hours
                source = "adaptif(negara)"
                top = sorted(weights.items(), key=lambda kv: -kv[1])[:5]
                log.info(
                    "[jadwal] negara teratas: %s",
                    ", ".join(f"{c}={int(v)}" for c, v in top),
                )

    state["upload_slots"] = {"date": today, "hours": hours, "source": source}
    save_state(cfg, state)
    log.info("[jadwal] slot upload (%s, UTC): %s", source, hours)
    return hours


# --------------------------------------------------------------------------
# Keputusan: apakah sekarang waktunya upload?
# --------------------------------------------------------------------------
def due_slot(
    cfg: dict, now: datetime | None = None, last_upload_ts: float | None = None
) -> tuple[bool, str]:
    """Apakah ADA slot prime yang jatuh tempo & belum terpakai sekarang?

    Return (boleh_upload, alasan). `boleh_upload=True` bila:
      - jam sekarang termasuk slot, DAN
      - slot itu belum dipakai hari ini (cek state['slots_used']), DAN
      - sudah lewat min_gap_hours sejak upload terakhir.

    Argumen `now`/`last_upload_ts` untuk uji deterministik; default real-time.
    """
    sched = cfg.get("upload_schedule", {})
    if not sched.get("enabled", True):
        return True, "penjadwalan dimatikan (upload langsung)"

    now = now or _now_utc()
    hours = compute_slots(cfg)
    cur_h = now.hour

    if cur_h not in hours:
        nxt = _next_slot_hour(hours, cur_h)
        return False, f"di luar slot prime; slot berikutnya jam {nxt:02d}:00 UTC"

    # cek jeda minimum sejak upload terakhir
    min_gap = float(sched.get("min_gap_hours", 1.5))
    state = load_state(cfg)
    last_ts = last_upload_ts
    if last_ts is None:
        last_ts = state.get("last_upload_ts")
    if last_ts:
        gap_h = (now.timestamp() - float(last_ts)) / 3600.0
        if gap_h < min_gap:
            return False, (
                f"baru upload {gap_h:.1f} jam lalu (< {min_gap} jam) -> tunggu"
            )

    # cek slot ini belum dipakai hari ini
    today = now.date().isoformat()
    used = state.get("slots_used") or {}
    if used.get("date") == today and cur_h in (used.get("hours") or []):
        return False, f"slot {cur_h:02d}:00 UTC sudah dipakai hari ini"

    return True, f"slot {cur_h:02d}:00 UTC siap"


def _next_slot_hour(hours: list[int], cur_h: int) -> int:
    later = [h for h in hours if h > cur_h]
    return later[0] if later else (hours[0] if hours else cur_h)


def mark_slot_used(cfg: dict, now: datetime | None = None) -> None:
    """Tandai slot jam sekarang sudah dipakai + catat last_upload_ts."""
    now = now or _now_utc()
    today = now.date().isoformat()
    state = load_state(cfg)
    used = state.get("slots_used") or {}
    if used.get("date") != today:
        used = {"date": today, "hours": []}
    if now.hour not in used["hours"]:
        used["hours"].append(now.hour)
    state["slots_used"] = used
    state["last_upload_ts"] = now.timestamp()
    save_state(cfg, state)


def slot_progress(cfg: dict, now: datetime | None = None) -> tuple[int, int]:
    """(tahap_terpakai_hari_ini, total_slot) untuk pesan 'tahap X/11'."""
    now = now or _now_utc()
    today = now.date().isoformat()
    n_slots = int(cfg.get("upload_schedule", {}).get("slots_per_day", 11))
    used = load_state(cfg).get("slots_used") or {}
    done = len(used.get("hours") or []) if used.get("date") == today else 0
    return done, n_slots
