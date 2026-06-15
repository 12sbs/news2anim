"""Buat naskah video dari artikel berita — DUA TAHAP.

Tahap A (treatment): ringkasan naratif yang SETIA pada fakta berita.
Tahap B (scenes)   : treatment dipecah menjadi adegan untuk video,
                     boleh berisi "reka adegan" (reenactment) dari kejadian
                     yang DISEBUTKAN berita — tanpa menambah fakta baru.

Output generate_script():
{
  "title": "...",
  "treatment": "<paragraf naratif>",
  "scenes": [
     {"speaker": "Anchor", "text": "...", "background": "studio", "type": "anchor"},
     {"speaker": "Narrator", "text": "...", "background": "city", "type": "reenactment"}
  ]
}

ATURAN KERAS (di-prompt): hanya gunakan fakta yang ADA di artikel.
Dilarang mengarang nama, kutipan, angka, atau kejadian. Tetap pada topik.
"""
from __future__ import annotations

import json
import re

import requests

from utils import load_config, log

# ---------------------------------------------------------------- prompts

TREATMENT_SYSTEM = """You are a factual news scriptwriter for an international audience.
You will receive ONE news article. Write a clear, engaging narration script in {lang}.

STRICT RULES:
- Use ONLY facts that appear in the article. Do NOT invent names, quotes, numbers,
  places, or events. Do NOT add opinions or speculation.
- Stay strictly on the topic of THIS article. Never drift to unrelated subjects.
- Neutral, professional news tone. Clear sentences for text-to-speech.
- Target about {words} words so the final video lasts at least two minutes.
- Structure: a hook, the key facts (who/what/when/where/why), relevant context
  that is present in the article, and a short closing.
- Do NOT include stage directions, sound effects, music cues, camera notes,
  bracketed text, or speaker labels (no "Narrator:", no "[music]", no "(sfx)").
  Write ONLY the words that will be spoken aloud, as plain flowing prose.

Return ONLY the narration text (no headings, no bullet points, no notes)."""

SCENES_SYSTEM = """You are a storyboard editor. You receive a finished narration script
(the "treatment") and must split it into video scenes in {lang}.

Return ONLY valid JSON:
{{"title": "...", "scenes": [
  {{"speaker": "Anchor", "text": "...", "background": "studio", "type": "anchor"}}
]}}

RULES:
- Keep the text faithful to the treatment. You may lightly rephrase for flow,
  but do NOT add new facts, names, quotes, or events.
- "speaker": "Anchor" for news-desk delivery, "Narrator" for voice-over during
  a reenactment, "Reporter" for field reporting. Use them naturally.
- "type": "anchor" (at the news desk) or "reenactment" (visualizing an event
  that the article describes). {reenact}
- "background": ONE lowercase keyword for the setting (e.g. studio, city,
  street, building, protest, court, map). Choose something the article implies.
- Produce between 6 and {max_scenes} scenes. Each scene 1-3 sentences.
- Reenactment scenes must depict ONLY events explicitly described in the article."""


# ---------------------------------------------------------------- ollama

def _ollama(cfg: dict, system: str, user: str, json_mode: bool) -> str | None:
    sc = cfg["script"]
    payload = {
        "model": sc["model"],
        "stream": False,
        "options": {"temperature": 0.4},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        payload["format"] = "json"
    try:
        r = requests.post(f"{sc['ollama_url']}/api/chat", json=payload, timeout=300)
        r.raise_for_status()
        return r.json()["message"]["content"]
    except Exception as e:  # noqa: BLE001
        log.warning("Ollama gagal (%s).", e)
        return None


_SPEAKER_LABEL = re.compile(
    r"^\s*(narrator|anchor|reporter|host|voice ?over|vo)\s*:\s*", re.IGNORECASE
)
_CUE_PAREN = re.compile(
    r"\((?:[^)]*?(?:music|sound|sfx|fades?|applause|cheers|noise|effect)[^)]*?)\)",
    re.IGNORECASE,
)


def clean_narration(text: str) -> str:
    """Buang arahan panggung/sfx/label pembicara agar bersih untuk TTS."""
    # buang seluruh segmen dalam kurung siku [ ... ]
    text = re.sub(r"\[[^\]]*\]", " ", text)
    # buang kurung biasa yang berisi isyarat audio/visual
    text = _CUE_PAREN.sub(" ", text)
    # bersihkan per-baris: hapus label pembicara di awal baris
    lines = []
    for line in text.splitlines():
        line = _SPEAKER_LABEL.sub("", line).strip()
        if line:
            lines.append(line)
    text = " ".join(lines)
    return re.sub(r"\s+", " ", text).strip()


def _extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- tahap A

def generate_treatment(cfg: dict, article: dict) -> str:
    sc = cfg["script"]
    lang = sc.get("language", "English")
    system = TREATMENT_SYSTEM.format(lang=lang, words=sc.get("target_words", 380))
    user = (
        f"ARTICLE TITLE: {article['title']}\n\n"
        f"ARTICLE BODY:\n{article['summary']}\n\n"
        f"Write the narration now, in {lang}."
    )
    if sc.get("use_ollama"):
        out = _ollama(cfg, system, user, json_mode=False)
        if out and len(out.strip()) > 80:
            return clean_narration(out)
    # fallback: pakai isi artikel apa adanya (tetap on-topic)
    log.info("Treatment fallback (tanpa Ollama).")
    return clean_narration(article["summary"])


# ---------------------------------------------------------------- tahap B

# kata kunci -> latar (cocokkan dgn file di assets/backgrounds/<keyword>.png)
_BG_KEYWORDS = [
    ("protest", ["protest", "demonstrat", "rally", "march"]),
    ("court", ["court", "trial", "judge", "verdict", "lawsuit"]),
    ("war", ["war", "military", "troops", "strike", "missile", "soldier"]),
    ("flood", ["flood", "storm", "rain", "hurricane", "typhoon"]),
    ("fire", ["fire", "wildfire", "blaze", "burn"]),
    ("election", ["election", "vote", "ballot", "campaign", "poll"]),
    ("economy", ["economy", "market", "trade", "inflation", "stock", "deal"]),
    ("city", ["city", "street", "town", "building", "downtown"]),
    ("map", ["country", "region", "border", "nation", "international"]),
]


def _guess_background(text: str) -> str:
    low = text.lower()
    for bg, kws in _BG_KEYWORDS:
        if any(k in low for k in kws):
            return bg
    return "studio"


def treatment_to_scenes(cfg: dict, article: dict, treatment: str) -> dict:
    """Pecah treatment secara DETERMINISTIK menjadi adegan.

    Semua kalimat naskah masuk (durasi penuh terjaga, 100% setia teks).
    Adegan diberi label anchor/reenactment bergantian + latar ditebak dari isi.
    """
    sc = cfg["script"]
    max_scenes = sc.get("max_scenes", 14)
    allow_reenact = sc.get("allow_reenactment", True)

    sentences = re.split(r"(?<=[.!?])\s+", treatment)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 15]
    if not sentences:
        sentences = [treatment.strip()]

    # kelompokkan agar total adegan <= max_scenes (tanpa membuang teks)
    import math
    group = max(1, math.ceil(len(sentences) / max_scenes))
    chunks = [
        " ".join(sentences[i : i + group])
        for i in range(0, len(sentences), group)
    ]

    scenes = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            # adegan pembuka selalu di meja berita
            scenes.append({"speaker": "Anchor", "text": chunk,
                           "background": "studio", "type": "anchor"})
            continue
        is_reenact = allow_reenact and (i % 2 == 1)
        scenes.append({
            "speaker": "Narrator" if is_reenact else "Anchor",
            "text": chunk,
            "background": _guess_background(chunk) if is_reenact else "studio",
            "type": "reenactment" if is_reenact else "anchor",
        })
    return {"title": article["title"], "scenes": scenes}


# ---------------------------------------------------------------- validasi

def _validate(scenario: dict, cfg: dict) -> dict:
    scenes = scenario.get("scenes") or []
    clean = []
    valid_speakers = set(cfg["tts"]["voices"].keys())
    for sc in scenes:
        text = clean_narration(sc.get("text") or "")
        if not text:
            continue
        speaker = sc.get("speaker", "Narrator") or "Narrator"
        if speaker not in valid_speakers:
            speaker = "Narrator" if "Narrator" in valid_speakers else "default"
        clean.append(
            {
                "speaker": speaker,
                "text": text,
                "background": (sc.get("background") or "studio").strip().lower(),
                "type": sc.get("type", "anchor"),
            }
        )
    clean = clean[: cfg["script"]["max_scenes"]]
    return {
        "title": scenario.get("title", "World News"),
        "treatment": scenario.get("treatment", ""),
        "scenes": clean,
    }


# ---------------------------------------------------------------- orkestra

def generate_script(cfg: dict, article: dict) -> dict:
    log.info("Tahap A: menyusun treatment (naskah setia fakta)...")
    treatment = generate_treatment(cfg, article)
    log.info("Treatment (%d kata):\n%s", len(treatment.split()), treatment[:400] + "...")

    log.info("Tahap B: memecah treatment menjadi adegan...")
    scenario = treatment_to_scenes(cfg, article, treatment)
    scenario["treatment"] = treatment
    scenario.setdefault("title", article["title"])

    scenario = _validate(scenario, cfg)
    log.info("Skenario final: %d adegan", len(scenario["scenes"]))
    return scenario


if __name__ == "__main__":
    cfg = load_config()
    demo = {
        "title": "Sample: Coastal city hit by severe flooding",
        "summary": (
            "A severe storm caused major flooding in a coastal city on Monday. "
            "Authorities said water levels rose by more than one metre in several "
            "districts. Hundreds of residents were evacuated to shelters. "
            "Local officials deployed rescue teams and warned of more rain ahead."
        ),
    }
    out = generate_script(cfg, demo)
    print(json.dumps(out, ensure_ascii=False, indent=2))
