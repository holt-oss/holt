#!/usr/bin/env bash
# Turns the raw recordings from record.mjs into the files in assets/.
#   scripts/record-demo/encode.sh [OUT_DIR]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
raw="${1:-$here/out}"
assets="$(cd "$here/../.." && pwd)/assets"
mkdir -p "$assets"

mp4() { # in out
  ffmpeg -hide_banner -loglevel error -y -i "$1" -ss 0.4 -c:v libx264 -preset slow -crf 24 \
    -pix_fmt yuv420p -movflags +faststart -an "$2"
}

gif() { # in out width fps
  ffmpeg -hide_banner -loglevel error -y -ss 0.4 -i "$1" \
    -vf "fps=$4,scale=$3:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
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
ls -la "$assets"
