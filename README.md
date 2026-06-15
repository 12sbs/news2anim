# news2anim 🎬📰

Ubah **berita** menjadi **video animasi karakter 2D** secara **otomatis**, lalu **upload ke YouTube**.

Pipeline: `RSS berita → naskah (LLM) → suara (TTS) → lip-sync → render karakter → gabung video → upload YouTube`.

Semua komponen **gratis & bisa jalan lokal** (tanpa GPU). Karakter dianimasikan dengan teknik
**mouth-swap** (badan + bentuk mulut diganti mengikuti suara) — fully otomatis seperti Live2D sederhana.

> ✅ Sudah teruji menghasilkan video. Karakter dummy disediakan agar bisa langsung dicoba —
> tinggal ganti dengan karaktermu sendiri.

---

## 🧩 Cara kerja (alur data)

```
RSS feed ──► fetch_news ──► artikel
                              │  script_gen (Ollama / fallback)
                              ▼
                          skenario.json  { scenes: [{speaker, text, background}, ...] }
                              │
              per adegan:     │
                 teks ─Piper──► .wav ─Rhubarb──► cue mulut (A..X)
                              │
                 render ──► background + body + mulut(per waktu) + subtitle ──► scene_xx.mp4
                              │
                          compose ──► final.mp4 (+intro/outro +musik)
                              │
                          upload ──► YouTube
```

---

## 📦 Yang perlu di-install

### 1. Python + library
```bash
git clone https://github.com/<user>/news2anim.git
cd news2anim
python -m venv .venv && source .venv/bin/activate   # opsional
pip install -r requirements.txt
```

### 2. Binary eksternal

| Tool | Wajib? | Fungsi | Link |
|---|---|---|---|
| **ffmpeg** | ✅ Wajib | render video | `apt install ffmpeg` / [ffmpeg.org](https://ffmpeg.org) |
| **Piper** | ✅ Wajib | Text-to-Speech | [github.com/rhasspy/piper](https://github.com/rhasspy/piper) |
| **Rhubarb** | ⬜ Opsional | lip-sync akurat (ada fallback) | [github.com/DanielSWolf/rhubarb-lip-sync](https://github.com/DanielSWolf/rhubarb-lip-sync) |
| **Ollama** | ⬜ Opsional | naskah pintar (ada fallback) | [ollama.com](https://ollama.com) |

> Tanpa Rhubarb → mulut tetap bergerak (pola sederhana).
> Tanpa Ollama → naskah dibuat dengan pemecah kalimat sederhana.
> **Piper wajib** untuk suara. Pastikan `piper` ada di PATH atau set `tts.piper_bin` di config.

### 3. Model suara Indonesia (Piper)
Unduh dari [huggingface.co/rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/main/id/id_ID),
mis. `id_ID-fajri-medium.onnx` + file `.onnx.json`-nya, taruh di folder `models/`,
lalu sesuaikan `tts.voices` di `config.yaml`.

---

## 🚀 Coba cepat (dengan karakter dummy)

```bash
# 1. Buat aset dummy (karakter + background)
python assets/make_dummy_assets.py

# 2. Uji render satu adegan (butuh Piper + model suara)
python src/render.py

# 3. Jalankan pipeline penuh (tanpa upload)
python src/pipeline.py --no-upload
```

Hasil video ada di `output/<judul-berita>/final.mp4`.

---

## 🎨 Ganti dengan karaktermu sendiri

Letakkan di `assets/characters/host/` (atau folder lain, atur `character.dir` di config):

| File | Keterangan |
|---|---|
| `body.png` | tubuh + kepala, background **transparan** |
| `mouth_A.png` … `mouth_H.png`, `mouth_X.png` | 9 bentuk mulut |

**Konvensi penting:** setiap `mouth_*.png` harus punya **ukuran kanvas yang sama** dengan
`body.png`, dengan mulut digambar di posisi yang benar dan sisanya transparan. Dengan begitu
mulut otomatis pas saat ditumpuk. (Lihat `assets/make_dummy_assets.py` sebagai contoh.)

Bentuk mulut (standar Rhubarb / Preston Blair):
`A`=tutup (M,B,P) · `B`=sedikit buka · `C`=buka sedang · `D`=buka lebar ·
`E`=bulat (O) · `F`=mengerucut (U,W) · `G`=F/V · `H`=L · `X`=istirahat.

Background: taruh `assets/backgrounds/<keyword>.png`. `keyword` dicocokkan dengan field
`background` tiap adegan (mis. `studio.png`, `banjir.png`).

---

## 📺 Setup upload YouTube otomatis

1. Buka [Google Cloud Console](https://console.cloud.google.com) → buat project.
2. Aktifkan **YouTube Data API v3**.
3. Buat **OAuth Client ID** tipe **Desktop app** → unduh JSON → simpan sebagai
   `credentials/client_secret.json`.
4. Set di `config.yaml`: `youtube.enabled: true` dan `youtube.privacy` (private/unlisted/public).
5. Pertama kali jalan, browser akan minta login Google → token tersimpan di
   `credentials/token.json` (otomatis selanjutnya).

> ⚠️ Folder `credentials/` & `output/` di-ignore git (lihat `.gitignore`). Jangan commit rahasia.

---

## ⏰ Jalankan otomatis (terjadwal)

Contoh cron (tiap 3 jam):
```bash
0 */3 * * * cd /path/news2anim && /path/.venv/bin/python src/pipeline.py >> output/cron.log 2>&1
```

---

## ⚙️ Konfigurasi

Semua diatur di [`config.yaml`](config.yaml): feed berita, jumlah berita per run, model LLM,
suara per karakter, posisi/skala karakter, resolusi video, musik, dan opsi YouTube.

---

## 📁 Struktur

```
news2anim/
├── config.yaml              # semua pengaturan
├── requirements.txt
├── assets/
│   ├── make_dummy_assets.py # generator karakter & background contoh
│   ├── characters/host/     # body.png + mouth_*.png
│   └── backgrounds/         # studio.png, dst
├── src/
│   ├── fetch_news.py        # 1. ambil berita RSS
│   ├── script_gen.py        # 2. berita → skenario JSON (Ollama/fallback)
│   ├── tts.py               # 3. teks → suara (Piper)
│   ├── lipsync.py           # 4. suara → timing mulut (Rhubarb/fallback)
│   ├── render.py            # 5. render adegan (body + mulut + subtitle)
│   ├── compose.py           # 6. gabung adegan + musik
│   ├── upload.py            # 7. upload YouTube
│   ├── pipeline.py          # orkestrator 1→7
│   └── utils.py             # config, state, helper
├── credentials/             # client_secret.json, token.json (tidak di-commit)
└── output/                  # hasil video (tidak di-commit)
```

---

## ⚠️ Catatan etika & hukum

- Sebutkan **sumber berita** (otomatis dimasukkan ke deskripsi video).
- Hindari menyebarkan **hoaks** — pertimbangkan mode **review manual** sebelum publish
  (set `youtube.enabled: false` lalu cek `output/.../final.mp4` dulu).
- Patuhi hak cipta gambar/musik/berita yang kamu pakai. Gunakan aset bebas-royalti.

---

## 🛣️ Pengembangan lanjutan (ide)

- Karakter Live2D asli via renderer headless.
- AI image (Stable Diffusion) untuk background per-adegan otomatis.
- Beberapa karakter sekaligus (wawancara 2 orang di 1 frame).
- Thumbnail otomatis + judul clickbait yang aman.

Kontribusi & ide dipersilakan. Selamat berkarya! 🎉
