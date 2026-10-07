import os, json, wave, subprocess
import numpy as np
import yt_dlp
from faster_whisper import WhisperModel

d = r"C:/Users/Thabang/Desktop/ai bin/7678657278400040213_yt"
v = "7678657278400040213"
url = f"https://www.tiktok.com/@satriaabaharii/video/{v}"

o = {"outtmpl": os.path.join(d, v + ".%(ext)s"),
     "extractor_args": {"tiktok": {"webpage_download": ["true"]}},
     "cookiefile": None, "quiet": True, "no_warnings": True, "retries": 5}
i = yt_dlp.YoutubeDL(o).extract_info(url, download=True)

m = {k: i.get(k) for k in ("id", "title", "description", "uploader", "uploader_id",
                           "upload_date", "timestamp", "duration", "view_count",
                           "like_count", "comment_count", "repost_count",
                           "save_count", "share_count", "track", "width", "height")}
m["source_url"] = url
m["asr_model"] = "small"
m["asr_language"] = "id"
with open(os.path.join(d, v + ".info.json"), "w", encoding="utf-8") as f:
    json.dump(m, f, indent=2, ensure_ascii=False)
print("META dur", m["duration"], "views", m["view_count"], "track", m["track"])

a = next(os.path.join(d, f) for f in sorted(os.listdir(d))
         if f.startswith(v) and f.endswith((".m4a", ".mp3", ".webm", ".opus", ".aac")))
w = os.path.join(d, v + "_16k.wav")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", a,
                "-ar", "16000", "-ac", "1", "-f", "wav", w], check=True)
with wave.open(w, "rb") as f:
    pcm = f.readframes(f.getnframes())
arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

mo = WhisperModel("small", device="cpu", compute_type="int8")


def run(vad):
    sg, inf = mo.transcribe(arr, beam_size=5, vad_filter=vad, language="id")
    return [(round(s.start, 2), round(s.end, 2), s.text.strip()) for s in sg], inf


ra, _ = run(True)
rb, _ = run(False)
rows = rb if len(rb) > len(ra) else ra
with open(os.path.join(d, v + "_transcript.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(f"[{int(a//60):02d}:{a%60:05.2f} --> {int(b//60):02d}:{b%60:05.2f}] {t}"
                      for a, b, t in rows))
print("SEGS", len(rows))
for a, b, t in rows[:10]:
    print(f"[{a:6.2f}] {t}")