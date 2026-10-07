#!/usr/bin/env python3
"""Transcribe orphan audio on disk, language-aware.

Usage: uv run --python 3.12 --with faster-whisper --with numpy python _batch_asr.py
Set ASR_LANG=id to force a language; otherwise whisper auto-detects.
"""
import os, re, wave, subprocess
import numpy as np
from faster_whisper import WhisperModel

BIN = r"C:/Users/Thabang/Desktop/ai bin"
media = (".mp3", ".m4a", ".mp4", ".wav")
data_ext = (".md", ".txt", ".vtt", ".srt", ".json")
force = os.environ.get("ASR_LANG") or None

files = os.listdir(BIN)
idx = {}
for f in files:
    m = re.search(r"(\d{15,25})", f)
    if m:
        idx.setdefault(m.group(1), []).append(f)

targets = []
for f in sorted(files):
    if os.path.splitext(f)[1].lower() not in media:
        continue
    m = re.search(r"(\d{15,25})", f)
    vid = m.group(1) if m else None
    sib = idx.get(vid, []) if vid else [f]
    if not any(os.path.splitext(s)[1].lower() in data_ext for s in sib):
        targets.append((vid, f))

print(f"ORPHANS: {len(targets)}  force_lang={force}", flush=True)
model = WhisperModel("base", device="cpu", compute_type="int8")

for vid, fn in targets:
    src = os.path.join(BIN, fn)
    out = os.path.join(BIN, f"{vid}_yt")
    os.makedirs(out, exist_ok=True)
    wav = os.path.join(out, f"{vid}_16k.wav")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                        "-ar", "16000", "-ac", "1", "-f", "wav", wav], check=True)
        with wave.open(wav, "rb") as w:
            pcm = w.readframes(w.getnframes())
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        dur = len(arr) / 16000

        # VAD over-trims these music-bed clips (1 segment per 60s). Run both and
        # keep whichever yields more text; fall back to the VAD pass on a tie so
        # genuine silence still comes out empty.
        def run(vad):
            kw = dict(beam_size=5, vad_filter=vad)
            if force:
                kw["language"] = force
            sg, inf = model.transcribe(arr, **kw)
            return [(round(s.start, 2), round(s.end, 2), s.text.strip()) for s in sg], inf

        rows_vad, info = run(True)
        rows_raw, _ = run(False)
        rows, info = (rows_raw, info) if len(rows_raw) > len(rows_vad) else (rows_vad, info)

        txt = "\n".join(f"[{int(st//60):02d}:{st%60:05.2f} --> {int(en//60):02d}:{en%60:05.2f}] {tx}"
                        for st, en, tx in rows)
        with open(os.path.join(out, f"{vid}_transcript.txt"), "w", encoding="utf-8") as fh:
            fh.write(txt)

        print(f"\n### {vid}  {fn}  {dur:.1f}s  segs={len(rows)}  "
              f"lang={info.language} p={info.language_probability:.2f}", flush=True)
        for st, en, tx in rows[:6]:
            print(f"    [{st:6.2f}] {tx}", flush=True)
        if len(rows) > 6:
            print(f"    ... {len(rows)-6} more", flush=True)
    except Exception as e:
        print(f"\n### {vid}  FAILED: {type(e).__name__}: {e}", flush=True)

print("\nDONE", flush=True)
