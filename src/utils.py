"""Utilitas bersama: config, path, logging, state."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import yaml

# Root project = folder di atas src/
ROOT = Path(__file__).resolve().parent.parent


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("news2anim")


log = setup_logging()


def load_config(path: str | None = None) -> dict:
    """Baca config.yaml."""
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


def resolve(p: str | os.PathLike) -> Path:
    """Path relatif terhadap ROOT project jika belum absolut."""
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)


# ---------------- State (berita yang sudah diproses) ----------------

def load_state(cfg: dict) -> dict:
    sf = resolve(cfg["automation"]["state_file"])
    if sf.exists():
        return json.loads(sf.read_text(encoding="utf-8"))
    return {"processed_ids": []}


def save_state(cfg: dict, state: dict) -> None:
    sf = resolve(cfg["automation"]["state_file"])
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_processed(cfg: dict, news_id: str) -> None:
    state = load_state(cfg)
    if news_id not in state["processed_ids"]:
        state["processed_ids"].append(news_id)
        # simpan maksimal 500 id terakhir
        state["processed_ids"] = state["processed_ids"][-500:]
        save_state(cfg, state)


def is_processed(cfg: dict, news_id: str) -> bool:
    return news_id in load_state(cfg).get("processed_ids", [])


# ---------------- Helper subprocess ----------------

def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Jalankan command eksternal, raise jika gagal."""
    log.info("$ %s", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, **kwargs)


def which(binary: str) -> bool:
    """Cek apakah binary tersedia di PATH."""
    from shutil import which as _which
    return _which(binary) is not None


def slugify(text: str, maxlen: int = 50) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in text)
    return "_".join(keep.split())[:maxlen] or "video"
