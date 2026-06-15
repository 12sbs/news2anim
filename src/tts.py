"""Text-to-Speech memakai Piper (lokal, gratis)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from utils import load_config, log, resolve


def synth(cfg: dict, text: str, out_wav: Path, speaker: str = "default") -> Path:
    """Ubah teks -> file WAV memakai Piper.

    Piper dipanggil: piper -m <model.onnx> -f <out.wav>  (teks via stdin)
    """
    tts = cfg["tts"]
    voices = tts["voices"]
    model = voices.get(speaker, voices.get("default"))
    model_path = resolve(model)

    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    if not model_path.exists():
        raise FileNotFoundError(
            f"Model suara tidak ada: {model_path}\n"
            "Unduh dari https://huggingface.co/rhasspy/piper-voices "
            "lalu taruh path-nya di config.yaml (tts.voices)."
        )

    cmd = [
        tts["piper_bin"],
        "-m", str(model_path),
        "-f", str(out_wav),
    ]
    log.info("TTS [%s]: %s", speaker, text[:60])
    subprocess.run(cmd, input=text.encode("utf-8"), check=True)
    return out_wav


if __name__ == "__main__":
    cfg = load_config()
    out = resolve("output/_tts_test.wav")
    synth(cfg, "Halo, ini uji coba suara berita animasi.", out)
    print("Tersimpan:", out)
