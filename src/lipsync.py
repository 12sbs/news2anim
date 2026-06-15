"""Lip-sync: ubah audio menjadi urutan bentuk mulut memakai Rhubarb.

Rhubarb menghasilkan "mouthCues" dengan 9 bentuk standar Preston Blair:
A B C D E F G H X  (X = diam/istirahat).
Tiap bentuk dipetakan ke file gambar mulut: mouth_A.png, mouth_B.png, ...
"""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

from utils import load_config, log, resolve

# Bentuk mulut Rhubarb -> nama file sprite
MOUTH_SHAPES = ["A", "B", "C", "D", "E", "F", "G", "H", "X"]


def _audio_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def get_mouth_cues(cfg: dict, wav_path: Path) -> list[dict]:
    """Kembalikan daftar cue: [{start, end, value}], value salah satu MOUTH_SHAPES.

    Bila Rhubarb tidak tersedia, fallback: buka-tutup mulut sederhana
    berbasis durasi (tetap menghasilkan animasi yang masuk akal).
    """
    wav_path = Path(wav_path)
    ls = cfg["lipsync"]
    from shutil import which

    if which(ls["rhubarb_bin"]):
        try:
            out = subprocess.run(
                [
                    ls["rhubarb_bin"],
                    "-f", "json",
                    "-r", ls.get("recognizer", "pocketSphinx"),
                    str(wav_path),
                ],
                check=True,
                capture_output=True,
            )
            data = json.loads(out.stdout.decode("utf-8"))
            return data.get("mouthCues", [])
        except Exception as e:  # noqa: BLE001
            log.warning("Rhubarb gagal (%s). Pakai fallback lip-sync.", e)

    return _fallback_cues(wav_path)


def _fallback_cues(wav_path: Path) -> list[dict]:
    """Animasi mulut sederhana: bergantian buka (C) dan tutup (X/A)."""
    dur = _audio_duration(wav_path)
    cues = []
    t = 0.0
    step = 0.12
    seq = ["C", "B", "D", "B"]  # pola buka mulut
    i = 0
    while t < dur:
        end = min(t + step, dur)
        # selipkan tutup mulut sesekali
        value = "X" if i % 4 == 3 else seq[i % len(seq)]
        cues.append({"start": round(t, 3), "end": round(end, 3), "value": value})
        t = end
        i += 1
    return cues


if __name__ == "__main__":
    cfg = load_config()
    wav = resolve("output/_tts_test.wav")
    if wav.exists():
        cues = get_mouth_cues(cfg, wav)
        log.info("%d cue mulut", len(cues))
        print(cues[:10])
    else:
        print("Jalankan tts.py dulu untuk membuat", wav)
