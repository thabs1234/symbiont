#!/usr/bin/env python3
"""Scrape-to-build for one video. Referenced by the A2A tool `scrape_build`.

Usage:  python build.py url=<tiktok-id-or-url>

Downloads with yt-dlp, writes info.json, decodes 16k mono wav, runs faster-whisper.
Prints the transcript; a video with no speech (music-only) legitimately yields none.

Run with:  uv run --python 3.12 --with faster-whisper --with yt-dlp --with numpy python build.py url=<id>
"""
import os, sys, json, wave, subprocess
import numpy as np
import yt_dlp

BIN = r"C:/Users/Thabang/Desktop/ai bin"


def resolve(arg):
    arg = arg.strip()
    for p in ("url=", "id=", "video="):
        if arg.startswith(p):
            arg = arg[len(p):]
    arg = arg.strip().strip('"').strip("'")
    if arg.startswith("http"):
        return arg, arg.rstrip("/").split("/")[-1].split("?")[0]
    if arg.isdigit():
        # TikTok 404s a bare /video/<id>; the @handle is required. Caller must
        # pass the full URL, or set TIKTOK_HANDLE for a bare id.
        handle = os.environ.get("TIKTOK_HANDLE", "").lstrip("@")
        if not handle:
            sys.exit(f"bare id {arg} needs a handle: set TIKTOK_HANDLE=<handle>, "
                     f"or pass url=https://www.tiktok.com/@<handle>/video/{arg}")
        return f"https://www.tiktok.com/@{handle}/video/{arg}", arg
    sys.exit(f"cannot parse: {arg!r} (expected a url or a numeric video id)")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    url, vid = resolve(sys.argv[1])
    out = os.path.join(BIN, f"{vid}_yt")
    os.makedirs(out, exist_ok=True)

    opts = {
        "outtmpl": os.path.join(out, f"{vid}.%(ext)s"),
        "extractor_args": {"tiktok": {"webpage_download": ["true"]}},
        "cookiefile": None,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    meta = {k: info.get(k) for k in ("id", "title", "description", "uploader",
                                    "uploader_id", "upload_date", "timestamp", "duration",
                                    "view_count", "like_count", "comment_count",
                                    "repost_count", "save_count", "share_count", "track")}
    meta["source_url"] = url
    with open(os.path.join(out, f"{vid}.info.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print("META:", json.dumps(meta, ensure_ascii=False)[:500])

    audio = next((os.path.join(out, f) for f in sorted(os.listdir(out))
                  if f.startswith(vid) and f.endswith((".m4a", ".mp3", ".webm", ".opus", ".aac"))), None)
    if not audio:
        print("NO_AUDIO: metadata only, no track to transcribe")
        return 0

    wav = os.path.join(out, f"{vid}_16k.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", audio,
                    "-ar", "16000", "-ac", "1", "-f", "wav", wav], check=True)
    with wave.open(wav, "rb") as w:
        pcm = w.readframes(w.getnframes())
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    rms = float(np.sqrt((arr ** 2).mean()))
    print(f"AUDIO: {os.path.basename(audio)}  {len(arr)/16000:.2f}s  peak={float(np.abs(arr).max()):.3f}  rms={rms:.3f}")

    from faster_whisper import WhisperModel
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segs, minfo = model.transcribe(arr, beam_size=5, vad_filter=True)
    rows = [(round(s.start, 2), round(s.end, 2), s.text.strip()) for s in segs]

    if not rows:
        # Distinguish "no speech" from "broken pipeline": a loud track with almost
        # no energy in the speech band is music, not a failure.
        win = 1024
        fr = arr[: len(arr) // win * win].reshape(-1, win) * np.hanning(win)
        S = np.abs(np.fft.rfft(fr, axis=1)) ** 2
        f = np.fft.rfftfreq(win, 1 / 16000)
        bass = float(S[:, (f >= 50) & (f < 300)].mean())
        speech = float(S[:, (f >= 300) & (f < 3400)].mean())
        ratio = bass / speech if speech else float("inf")
        print(f"NO_SPEECH: 0 segments. bass={bass:.4g} speech_band={speech:.4g} "
              f"ratio={ratio:.1f}x -> {'MUSIC (expected)' if ratio > 5 else 'SPEECH MISSED (investigate)'}")

    txt = "\n".join(f"[{int(st//60):02d}:{st%60:05.2f} --> {int(en//60):02d}:{en%60:05.2f}] {tx}"
                    for st, en, tx in rows)
    with open(os.path.join(out, f"{vid}_transcript.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(f"LANG: {minfo.language} p={minfo.language_probability:.3f}")
    print("=== TRANSCRIPT ===")
    print(txt or "(none)")
    print(f"ARTIFACTS: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
