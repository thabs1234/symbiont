#!/usr/bin/env python3
"""Full build for the Satria Bahari batch: re-download with the real handle,
re-transcribe with a multilingual model at language=id, write info.json.

Usage: uv run --python 3.12 --with faster-whisper --with yt-dlp --with numpy python _build_satria.py
"""
import os, re, wave, json, subprocess
import numpy as np
import yt_dlp
from faster_whisper import WhisperModel

BIN = r"C:/Users/Thabang/Desktop/ai bin"
HANDLE = "satriaabaharii"
LANG = "id"
MODEL = os.environ.get("ASR_MODEL", "small")

IDS = ["7661634936205626645", "7663455081668594965", "7663831861348650260",
       "7664570577079782677", "7665313898580528405", "7670882707370560788",
       "7674568455445564693", "7676823524031401236", "7678657278400040213",
       "7504263816645987602", "7591865156196486421"]

model = WhisperModel(MODEL, device="cpu", compute_type="int8")
print(f"MODEL={MODEL} LANG={LANG} N={len(IDS)}", flush=True)

for vid in IDS:
    url = f"https://www.tiktok.com/@{HANDLE}/video/{vid}"
    out = os.path.join(BIN, f"{vid}_yt")
    os.makedirs(out, exist_ok=True)
    print(f"\n########## {vid}", flush=True)
    try:
        opts = {
            "outtmpl": os.path.join(out, f"{vid}.%(ext)s"),
            "extractor_args": {"tiktok": {"webpage_download": ["true"]}},
            "cookiefile": None, "quiet": True, "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        meta = {k: info.get(k) for k in (
            "id", "title", "description", "uploader", "uploader_id", "upload_date",
            "timestamp", "duration", "view_count", "like_count", "comment_count",
            "repost_count", "save_count", "share_count", "track", "width", "height")}
        meta["source_url"] = url
        meta["asr_model"] = MODEL
        meta["asr_language"] = LANG
        with open(os.path.join(out, f"{vid}.info.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        print(f"  META dur={meta['duration']} views={meta['view_count']} "
              f"likes={meta['like_count']} track={meta['track']!r}", flush=True)

        audio = next((os.path.join(out, f) for f in sorted(os.listdir(out))
                      if f.startswith(vid) and f.endswith((".m4a", ".mp3", ".webm", ".opus", ".aac"))), None)
        if not audio:
            print("  NO_AUDIO", flush=True)
            continue

        wav = os.path.join(out, f"{vid}_16k.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", audio,
                        "-ar", "16000", "-ac", "1", "-f", "wav", wav], check=True)
        with wave.open(wav, "rb") as w:
            pcm = w.readframes(w.getnframes())
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

        def run(vad):
            sg, inf = model.transcribe(arr, beam_size=5, vad_filter=vad, language=LANG)
            return [(round(s.start, 2), round(s.end, 2), s.text.strip()) for s in sg], inf

        rows_vad, inf = run(True)
        rows_raw, _ = run(False)
        rows = rows_raw if len(rows_raw) > len(rows_vad) else rows_vad

        txt = "\n".join(f"[{int(st//60):02d}:{st%60:05.2f} --> {int(en//60):02d}:{en%60:05.2f}] {tx}"
                        for st, en, tx in rows)
        with open(os.path.join(out, f"{vid}_transcript.txt"), "w", encoding="utf-8") as f:
            f.write(txt)
        print(f"  ASR segs={len(rows)} lang={inf.language} p={inf.language_probability:.2f}", flush=True)
        for st, en, tx in rows[:8]:
            print(f"    [{st:6.2f}] {tx}", flush=True)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}", flush=True)

print("\nDONE", flush=True)
