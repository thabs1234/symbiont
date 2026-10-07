#!/usr/bin/env python3
"""Scrape-to-build for one video. Referenced by the A2A tool `scrape_build`.

Usage:  python build.py url=<tiktok-id-or-url>

Downloads with yt-dlp, writes info.json, decodes 16k mono wav, runs faster-whisper.
Prints the transcript; a video with no speech (music-only) legitimately yields none.

Run with:  uv run --python 3.12 --with faster-whisper --with yt-dlp --with numpy python build.py url=<id>
"""
import os, sys, json, re, wave, subprocess
from datetime import date
from urllib.parse import urlsplit
import numpy as np
import yt_dlp

BIN = r"C:/Users/Thabang/Desktop/ai bin"

# Strict allowlist: yt-dlp canonical IDs, or bare numeric TikTok IDs.
# Rejects anything with path separators, backslashes, dots, slashes, etc.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Exact trusted hostnames. Classification never uses substring matching, so
# lookalike/suffix hosts (e.g. youtube.com.evil.invalid) are rejected.
_YT_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
}
_TT_HOSTS = {
    "tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com",
}


def safe_id(raw):
    """Validate a candidate video id against the filename-safe regex. Fail hard."""
    if not raw or not _SAFE_ID.fullmatch(raw):
        sys.exit(f"unsafe/filename-incompatible id: {raw!r}")
    return raw


def parse_url(arg):
    """Return (url, platform) for any supported input; raise ValueError if unsupported.

    Bare numeric ids are treated as TikTok (mobile canonical redirector).
    URLs are parsed with urllib.parse.urlsplit and classified by exact
    hostname allowlist; substring matching is rejected to avoid lookalike
    hosts, suffix injection, and SSRF via untrusted routing to yt-dlp.
    """
    arg = arg.strip()
    if arg.isdigit():
        # m.tiktok.com/v/<id> redirects to the canonical post and needs no
        # @handle. Try that first so a bare id works without TIKTOK_HANDLE.
        url = f"https://m.tiktok.com/v/{arg}"
        return url, "tiktok"
    if not arg.startswith(("http://", "https://")):
        raise ValueError(arg)
    parts = urlsplit(arg)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme: {scheme}")
    # Reject userinfo (user:pass@) - never accepted for trusted hosts.
    if parts.username or parts.password:
        raise ValueError("userinfo not allowed")
    host = parts.hostname
    if host is None:
        raise ValueError("missing hostname")
    host = host.lower()
    if host in _TT_HOSTS:
        return arg, "tiktok"
    if host in _YT_HOSTS:
        return arg, "youtube"
    raise ValueError(f"unsupported source: {arg}")


def resolve(arg):
    """Resolve an arg (url= or bare numeric id) to (url, platform, safe_id)."""
    arg = arg.strip()
    for p in ("url=", "id=", "video="):
        if arg.startswith(p):
            arg = arg[len(p):]
    arg = arg.strip().strip('"').strip("'")

    platform = "tiktok"
    try:
        url, platform = parse_url(arg)
    except ValueError:
        sys.exit(f"cannot parse: {arg!r} (expected a url or a numeric video id)")

    # Use yt-dlp's canonical info to get a stable id, but do NOT download.
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_args": {"tiktok": {"webpage_download": ["true"]}},
        "cookiefile": None,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as y:
        info = y.extract_info(url, download=False)

    vid = info.get("id") or url.rstrip("/").split("/")[-1].split("?")[0]
    vid = safe_id(vid)
    return url, platform, vid


def find_media(out, vid):
    """Find a video file (mp4/mkv/mov/m4v) and/or an audio file for ffmpeg."""
    exts = (".mp4", ".mkv", ".mov", ".m4v", ".m4a", ".mp3", ".webm", ".opus", ".aac", ".wav")
    files = [f for f in sorted(os.listdir(out)) if f.startswith(vid) and f.endswith(exts)]
    video_exts = (".mp4", ".mkv", ".mov", ".m4v")
    audio_exts = (".m4a", ".mp3", ".webm", ".opus", ".aac", ".wav")
    vid_file = next((os.path.join(out, f) for f in files if f.endswith(video_exts)), None)
    aud_file = next((os.path.join(out, f) for f in files if f.endswith(audio_exts)), None)
    return vid_file, aud_file, files


def wav_from_video(video_path, wav_path):
    """Extract 16k mono wav from a video file via ffmpeg."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video_path,
                    "-vn", "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
                   check=True)


def wav_from_audio(audio_path, wav_path):
    """Extract 16k mono wav from an audio file via ffmpeg."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", audio_path,
                    "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
                   check=True)


def decode_wav(wav_path):
    """Decode a wav file to numpy float32 array (16k mono)."""
    with wave.open(wav_path, "rb") as w:
        pcm = w.readframes(w.getnframes())
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return arr


def transcribe(arr):
    """Run faster-whisper base (multilingual) on a float32 array. Returns (rows, lang, prob)."""
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segs, minfo = model.transcribe(arr, beam_size=5, vad_filter=True)
    rows = [(round(s.start, 2), round(s.end, 2), s.text.strip()) for s in segs]
    lang = getattr(minfo, "language", None) or "unknown"
    prob = getattr(minfo, "language_probability", None)
    return rows, lang, prob


def fmt_ts(st, en):
    return f"[{int(st//60):02d}:{st%60:05.2f} --> {int(en//60):02d}:{en%60:05.2f}]"


def build_full_md(meta, transcript_text, rows, out, vid, platform, lang, prob, asr_status, media_files, wav_path):
    """Build the full_build.md artifact content per G1 definition of done."""
    dur = meta.get("duration")
    dur_str = f"{dur}s" if dur is not None else None

    def cell(v):
        # None -> UNKNOWN (never invent a value for an absent null).
        if v is None:
            return "UNKNOWN"
        return str(v).replace("\n", " ").replace("|", "\\|")

    # (field, value, source): source is "yt-dlp", "creator", or UNKNOWN.
    # Upload date is included only if yt-dlp supplies it.
    meta_rows = [
        ("Title", meta.get("title"), "yt-dlp"),
        ("Creator/uploader", meta.get("uploader"), "yt-dlp"),
        ("Uploader ID", meta.get("uploader_id"), "yt-dlp"),
        ("Upload date", meta.get("upload_date"), "yt-dlp"),
        ("Duration", dur_str, "yt-dlp"),
        ("Views", meta.get("view_count"), "yt-dlp"),
        ("Likes", meta.get("like_count"), "yt-dlp"),
        ("Comments", meta.get("comment_count"), "yt-dlp"),
        ("Reposts", meta.get("repost_count"), "yt-dlp"),
        ("Saves", meta.get("save_count"), "yt-dlp"),
        ("Shares", meta.get("share_count"), "yt-dlp"),
        ("Track", meta.get("track"), "yt-dlp"),
        ("Creator caption", meta.get("description"), "creator"),
    ]

    lines = []
    lines.append(f"# {vid} — Full Build")
    lines.append("")
    lines.append("## Source")
    lines.append(f"- Platform: {platform}")
    lines.append(f"- URL: {meta.get('source_url', '')}")
    lines.append(f"- yt-dlp canonical ID: `{vid}`")
    lines.append(f"- Extraction status: {meta.get('extraction_status', 'ok')}")
    lines.append("")

    lines.append("## Metadata (per-field sourced)")
    lines.append("")
    lines.append("| Field | Value | Source |")
    lines.append("|---|---|---|")
    for field, value, source in meta_rows:
        lines.append(f"| {field} | {cell(value)} | {source} |")
    lines.append("")

    lines.append("## Creator caption (verbatim)")
    desc = meta.get("description")
    lines.append(desc if desc else "(no description / caption unavailable)")
    lines.append("")

    lines.append("## ASR")
    lines.append("- Model: faster-whisper base (multilingual, no language argument)")
    lines.append(f"- Detected language: {lang}")
    if prob is not None:
        lines.append(f"- Language probability: {prob:.3f}")
    else:
        lines.append("- Language probability: UNKNOWN")
    lines.append(f"- Segment count: {len(rows)}")
    lines.append(f"- ASR status: {asr_status}")
    lines.append("")

    lines.append("## Transcript")
    lines.append("```")
    if transcript_text:
        lines.append(transcript_text)
    else:
        lines.append("(empty — no speech segments)")
    lines.append("```")
    lines.append("")

    lines.append("## Artifacts")
    for m in media_files:
        lines.append(f"- {os.path.basename(m)}")
    if wav_path:
        lines.append(f"- {os.path.basename(wav_path)}")
    lines.append(f"- {vid}.info.json")
    lines.append(f"- {vid}_transcript.txt")
    lines.append("")

    lines.append("## Verifier note")
    lines.append("This script does NO external research. Substantive creator claims")
    lines.append("(counts, statements, endorsements) are UNVERIFIED — recorded from the")
    lines.append("creator's caption/metadata only, not independently checked.")
    lines.append("")

    return "\n".join(lines)


def append_scrape_md(vid, platform, meta, status):
    """Append one compact entry to BIN/video_scrape.md; create header if absent.

    Append-only: if the exact video ID already occurs in an entry heading, the
    file is left untouched (no bytes rewritten/removed). Otherwise append a
    `## YYYY-MM-DD — <id>` heading + bullet block. Today's date comes from the
    stdlib (datetime.date.today), not a non-portable shell `date` call.
    """
    path = os.path.join(BIN, "video_scrape.md")
    today = date.today().isoformat()

    def val(v):
        return "UNKNOWN" if v is None else v

    def sanitize(v):
        """Collapse whitespace to single spaces; escape pipe chars so
        a value cannot inject fake markdown table rows/headings."""
        if v is None:
            return "UNKNOWN"
        return " ".join(str(v).split()).replace("|", "\\|")

    title = sanitize(meta.get("title"))
    uploader = sanitize(meta.get("uploader"))
    views = val(meta.get("view_count"))
    likes = val(meta.get("like_count"))
    comment_count = val(meta.get("comment_count"))
    upload_date = val(meta.get("upload_date"))
    dur = meta.get("duration")
    dur_s = f"{dur}s" if dur is not None else "UNKNOWN"
    url = sanitize(meta.get("source_url", ""))

    entry_lines = [
        f"## {today} — {vid}",
        f"- URL: {url}",
        f"- Platform: {platform}",
        f"- Title: {title}",
        f"- Uploader: {uploader}",
        f"- Views: {views}",
        f"- Likes: {likes}",
        f"- Comments: {comment_count}",
        f"- Upload date: {upload_date}",
        f"- Duration: {dur_s}",
        f"- Status: {status}",
        "",
    ]
    entry_text = "\n".join(entry_lines)

    # Duplicate guard: if this exact id already has an entry heading, skip
    # without mutating any bytes.
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()
        if re.search(rf"^## \d{{4}}-\d{{2}}-\d{{2}} — {re.escape(vid)}$",
                     existing, re.M):
            return
    else:
        existing = None

    with open(path, "a", encoding="utf-8") as f:
        if existing is None:
            f.write("# video_scrape log\n\n")
        elif existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(entry_text)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    url, platform, vid = resolve(sys.argv[1])
    out = os.path.join(BIN, f"{vid}_yt")
    full_path = os.path.join(BIN, f"{vid}_full_build.md")

    # Refuse rerun before any download/write so we never partially overwrite
    # existing <id>.info.json / transcript and then fail midway.
    if os.path.exists(full_path):
        sys.exit(f"full build already exists, refusing rerun to avoid partial overwrite: {full_path}")

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
    meta["extraction_status"] = "ok"
    with open(os.path.join(out, f"{vid}.info.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print("META:", json.dumps(meta, ensure_ascii=False)[:500])

    vid_file, aud_file, media_files = find_media(out, vid)
    if not vid_file and not aud_file:
        print("NO_MEDIA: no video or audio file found to transcribe")
        txt = ""
        rows = []
        lang = "unknown"
        prob = None
        asr_status = "UNAVAILABLE (no media to transcribe)"
        wav_path = None
        media_files_abs = []
    else:
        wav = os.path.join(out, f"{vid}_16k.wav")
        if aud_file:
            wav_from_audio(aud_file, wav)
        else:
            wav_from_video(vid_file, wav)
        media_files_abs = [os.path.join(out, m) for m in media_files]

        arr = decode_wav(wav)
        rms = float(np.sqrt((arr ** 2).mean()))
        peak = float(np.abs(arr).max())
        print(f"AUDIO: {os.path.basename(vid_file or aud_file)}  {len(arr)/16000:.2f}s  peak={peak:.3f}  rms={rms:.3f}")

        rows, lang, prob = transcribe(arr)

        if not rows:
            asr_status = "UNKNOWN — ASR returned no segments; this does not establish no speech"
            print(asr_status)
        else:
            asr_status = f"OK ({len(rows)} segments)"
            print(f"LANG: {lang} p={prob:.3f}" if prob is not None else f"LANG: {lang}")

        txt = "\n".join(f"{fmt_ts(st, en)} {tx}" for st, en, tx in rows)
        with open(os.path.join(out, f"{vid}_transcript.txt"), "w", encoding="utf-8") as f:
            f.write(txt)
        wav_path = wav

    print("=== TRANSCRIPT ===")
    print(txt or "(none)")

    # --- Generate full_build.md ---
    md = build_full_md(meta, txt, rows, out, vid, platform, lang, prob, asr_status, media_files_abs, wav_path)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"FULL_BUILD: {full_path}")

    # --- Append to video_scrape.md only after successful artifact generation ---
    append_scrape_md(vid, platform, meta, asr_status)
    print(f"SCRAPE_APPEND: {os.path.join(BIN, 'video_scrape.md')}")

    print(f"ARTIFACTS: {out}")
    print(f"NOT SENT: {vid} | {meta.get('title', '')} | {lang} | {asr_status} | {full_path}")
    print(f"COPY-READY / NOT SENT: {vid} {full_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
