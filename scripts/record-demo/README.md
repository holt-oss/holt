# Demo recordings

Re-records the launch clips in `assets/` from a live Holt site with
Playwright's video capture. It uses an already-installed Chromium (the newest
cached headless shell) and never installs a browser.

```sh
# 1. record (raw .webm + cut lists in scripts/record-demo/out/)
HOLT_URL=https://HOLT_URL node scripts/record-demo/record.mjs            # all three
HOLT_URL=https://HOLT_URL node scripts/record-demo/record.mjs desktop    # or one

# 2. encode into assets/: demo.mp4, demo.gif (<8 MB), demo-phone.mp4, url-trick.mp4
scripts/record-demo/encode.sh
```

| Clip | Size | What it shows |
|---|---|---|
| `demo.mp4` / `demo.gif` | 1280×720 | landing → paste `https://github.com/pallets/flask` → report → starter issues → `/hacktoberfest` (Python) |
| `demo-phone.mp4` | 780×1688 (390×844 at 2×) | the same flow on a phone, for WhatsApp and Instagram stories |
| `url-trick.mp4` | 1280×720 | "change one word": github.com → our host, then the real report |

Notes:
- The script first makes **one** plain request to `/hacktoberfest?lang=python`,
  and if the find is queued it follows that single job until it is done. Don't
  loop on page loads: each load can start a find, and the server rate-limits
  anonymous work per IP.
- Long waits for data (a queued find, an uncached report) are recorded as cut
  lists and removed by `encode.sh`, keeping about 2 s of the progress state.
- The address bar in `url-trick` is drawn by the script (headless Chromium has
  no address bar); the page it lands on is real, via `/github.com/pallets/flask`.
- Needs `playwright-core` (set `PLAYWRIGHT_CORE` if it isn't resolvable) and
  `ffmpeg`.
