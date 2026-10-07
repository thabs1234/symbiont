# goals.md — shared objectives

One goal, both agents. Status is owned by whichever agent is currently working it; flip the flag and
add a log line in `collective.md`.

## G1 — TikTok/YouTube scrape → full build pipeline  ·  `ACTIVE`

**Goal:** turn a pasted video URL into a verified artifact set, with a real transcript and the
claims in it checked against source, not restated from the caption.

**Definition of done, per URL:**
1. `Desktop/ai bin/<ID>_full_build.md` — metadata, timestamped transcript, creator breakdown.
2. `Desktop/ai bin/video_scrape.md` appended in the established format, blockers logged.
3. Every number in the artifact either comes from a tool or is labelled as the creator's claim.
   (wifit3 is the worked example: caption said 968 stars, GitHub API said 1,544 — both recorded.)
4. Terse one-line WhatsApp summary, `hermes send`, exit code 0.

**Known working:** last run 2026-09-29 on TikTok `7689682288673705268` (`@git.radar` / wifit3).
yt-dlp Python API with `extractor_args={'tiktok':{'webpage_download':['true']}}` and `cookiefile: NONE`
extracts without cookies or 403. No subs on that video, so local faster-whisper filled the gap.

**A2A client:** `a2a_client.py` built (CLI + module). Agents use `python a2a_client.py claim|done|send|status` instead of raw `curl`.
