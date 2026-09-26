#!/usr/bin/env bash
# Turns the raw recordings from record.mjs into the files in assets/.
#   scripts/record-demo/encode.sh [OUT_DIR]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
raw="${1:-$here/out}"
assets="$(cd "$here/../.." && pwd)/assets"
mkdir -p "$assets"

# record.mjs writes <name>.cuts.json: [[from, to], ...] seconds of waiting to drop.
cutfilter() { # in.webm -> "fps=25,select=...,setpts=..." (or just fps=25)
  local cuts="${1%.webm}.cuts.json"
  node -e '
    const fs = require("fs");
    const cuts = fs.existsSync(process.argv[1]) ? JSON.parse(fs.readFileSync(process.argv[1], "utf8")) : [];
    const keep = ["gte(t,0.4)", ...cuts.map(([a, b]) => `not(between(t,${a.toFixed(2)},${b.toFixed(2)}))`)].join("*");
    const q = "\u0027"; // quote the expression: its commas would split the filtergraph
    process.stdout.write(`fps=25,select=${q}${keep}${q},setpts=N/25/TB`);
  ' "$cuts"
}

mp4() { # in out
  ffmpeg -hide_banner -loglevel error -y -i "$1" -vf "$(cutfilter "$1")" -c:v libx264 -preset slow -crf 24 \
    -pix_fmt yuv420p -movflags +faststart -an "$2"
}

gif() { # in out width fps
  ffmpeg -hide_banner -loglevel error -y -i "$1" \
    -vf "$(cutfilter "$1"),fps=$4,scale=$3:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
    "$2"
}

[ -f "$raw/demo-desktop.webm" ] && mp4 "$raw/demo-desktop.webm" "$assets/demo.mp4"
[ -f "$raw/demo-phone.webm" ] && mp4 "$raw/demo-phone.webm" "$assets/demo-phone.mp4"
[ -f "$raw/url-trick.webm" ] && mp4 "$raw/url-trick.webm" "$assets/url-trick.mp4"

if [ -f "$raw/demo-desktop.webm" ]; then
  # Keep the GIF under 8 MB: step down width and frame rate until it fits.
  for spec in "960 12" "880 10" "800 10" "720 8"; do
    set -- $spec
    gif "$raw/demo-desktop.webm" "$assets/demo.gif" "$1" "$2"
    size=$(stat -c %s "$assets/demo.gif")
    echo "demo.gif ${1}px ${2}fps: $((size / 1024)) KB"
    [ "$size" -lt $((8 * 1024 * 1024)) ] && break
  done
fi
for f in "$assets"/demo.mp4 "$assets"/demo-phone.mp4 "$assets"/url-trick.mp4; do
  [ -f "$f" ] && echo "$(basename "$f"): $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")s, $(( $(stat -c %s "$f") / 1024 )) KB"
done
