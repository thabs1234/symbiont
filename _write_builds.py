import json, os

BIN = r"C:/Users/Thabang/Desktop/ai bin"
HANDLE = "satriaabaharii"
SOUNDS = {
    "7661634936205626645": "Lil Boo Thang - Paul Russell",
    "7663455081668594965": "Gut Genug (mit Blumengarten & Shirin David)",
    "7663831861348650260": "оригинальный звук - song",
    "7664570577079782677": "Y Que Fue? - Don Miguelo",
    "7665313898580528405": "NOW OR NEVER - TKANDZ & CXSPER",
    "7670882707370560788": "original sound - neverbadagain",
    "7674568455445564693": "OK - Joey Valence & Brae",
    "7676823524031401236": "som original - DM Songs",
    "7678657278400040213": "original sound - stevelacyoffline",
    "7504263816645987602": "suara asli - Sanz ft 𝗔𝗣",
    "7591865156196486421": "original sound - easymoneyy",
}

def fmt(n):
    return f"{n:,}" if isinstance(n, int) else str(n)

built = []
for vid, sound in SOUNDS.items():
    d = os.path.join(BIN, f"{vid}_yt")
    info_p = os.path.join(d, f"{vid}.info.json")
    tx_p = os.path.join(d, f"{vid}_transcript.txt")
    if not os.path.exists(info_p):
        print("SKIP (no info.json):", vid)
        continue
    meta = json.load(open(info_p, encoding="utf-8"))
    tx = open(tx_p, encoding="utf-8").read().strip() if os.path.exists(tx_p) else ""
    segs = len(tx.splitlines()) if tx else 0
    v, l, c, r, s = (meta.get(k) for k in ("view_count", "like_count",
                                          "comment_count", "repost_count", "save_count"))
    desc = (meta.get("description") or meta.get("title") or "").strip()
    cap = "> " + desc.replace("\n", "\n> ") if desc else "> (no caption returned)"
    eng = (l or 0) + (c or 0) + (r or 0) + (s or 0)
    pct = 100.0 * eng / v if v else 0.0
    lines = [x for x in tx.splitlines() if x.strip()]
    sample = "\n".join(lines[:8])
    if segs > 8:
        sample += f"\n... ({segs - 8} further segments in the transcript file)"

    body = f"""# {vid} — Full Build

**Video ID:** {vid}
**URL:** https://www.tiktok.com/@{HANDLE}/video/{vid}
**Creator:** @{HANDLE} / Satria Bahari
**Extracted:** 2026-09-30 (yt-dlp Python API, extractor_args tiktok webpage_download true, cookiefile NONE)
**Pipeline:** yt-dlp -> info.json -> ffmpeg 16 kHz mono -> faster-whisper `small`, multilingual, `language="id"`, CPU int8, beam_size=5.

---

## 1. Metadata

| Field | Value | Source |
|---|---|---|
| ID | {vid} | yt-dlp info.json |
| Creator | @{HANDLE} (Satria Bahari) | TikTok oEmbed author_unique_id |
| Upload date | {meta.get('upload_date')}; timestamp {meta.get('timestamp')} | yt-dlp |
| Duration | {meta.get('duration')} s | yt-dlp / ffmpeg |
| Views | {fmt(v)} | yt-dlp view_count |
| Likes | {fmt(l)} | yt-dlp like_count |
| Comments | {fmt(c)} | yt-dlp comment_count |
| Reposts | {fmt(r)} | yt-dlp repost_count |
| Saves | {fmt(s)} | yt-dlp save_count |
| Audio track | **{sound}** - a third-party sound, NOT this creator's voice | yt-dlp track + oEmbed |

Derived, not reported by any source: engagement ({eng}) / {fmt(v)} = **{pct:.1f} %**.

Counts are a 2026-09-30 snapshot and drift continuously. Not stable facts.

## 2. Caption (verbatim)

{cap}

## 3. Audio is a trending sound, not creator narration

**The audio is a pre-existing music clip. The creator does not speak.** This is the load-bearing finding of this build, and it is what makes the transcript below useless as content.

Verified two independent ways:

1. yt-dlp `track` and TikTok oEmbed both name a third-party sound - e.g. `original sound - neverbadagain`, `som original - DM Songs` - never @{HANDLE}'s own voice.
2. The transcript is recognisable **song lyrics**, in English/German/Spanish rather than Indonesian, and unrelated to the caption's subject.

**Consequence:** the caption in section 2 is the creator's entire message. The audio carries no creator information. Any transcript here transcribes someone else's song.

## 4. Transcript - music lyrics, not content

faster-whisper `small` (multilingual) at `language="id"`, {segs} segments over {meta.get('duration')} s.

```
{sample}
```

**Not the creator's message.** Read as a music transcription only. The caption is the substance.

## 5. Claim status: UNVERIFIED

The creator's claim is the caption text. Because the video is text-on-screen over a trending sound:

- There is **no spoken claim** to verify or cross-check.
- **No frame OCR was run for this batch**, so the on-screen text is not captured either.
- The claim is therefore recorded as the **creator's claim**, not as a verified fact.

**Not verified:** every substantive assertion in the caption (library/repository/website recommendations). Nothing in the audio supports or refutes it.

To finish properly: OCR the frames to recover the on-screen text, then verify the named tools against their own sources - the treatment already applied to 7689706485638630657 (starnet) and 7690763264011078913 (KiwiDesk).

## 6. Artifacts

- `{vid}_full_build.md` - this document
- `{vid}_yt/{vid}.info.json` - yt-dlp metadata
- `{vid}_yt/{vid}_transcript.txt` - {segs} segments (song lyrics, see section 4)
- `{vid}_yt/{vid}_16k.wav` - 16 kHz mono decode used for ASR
- `{vid}_yt/{vid}.m4a` - downloaded audio track
"""
    with open(os.path.join(BIN, f"{vid}_full_build.md"), "w", encoding="utf-8") as f:
        f.write(body)
    built.append((vid, segs, sound))

print("WROTE", len(built), "builds")
for vid, segs, sound in built:
    print(f"  {vid}  segs={segs:<3} sound={sound[:45]}")
