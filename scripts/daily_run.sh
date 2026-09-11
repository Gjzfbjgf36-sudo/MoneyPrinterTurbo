#!/usr/bin/env sh
# Erzeugt alle Videos aus tasks.jsonl und lädt sie danach zu YouTube hoch.
# Aufruf: ./scripts/daily_run.sh   (oder per cron, siehe README-Abschnitt)
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"

UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"
TASK_FILE="${TASK_FILE:-tasks.jsonl}"
PRIVACY="${PRIVACY:-private}"
UPLOAD_LIMIT="${UPLOAD_LIMIT:-5}"

if [ ! -f "$TASK_FILE" ]; then
  echo "Themenliste $TASK_FILE fehlt." >&2
  exit 1
fi

echo "=== $(date '+%Y-%m-%d %H:%M') Videos erzeugen ==="
"$UV_BIN" run --no-sync python cli.py \
  --batch-file "$TASK_FILE" \
  --video-language de-DE \
  --voice-name de-DE-KatjaNeural-Female \
  --video-aspect 9:16 \
  --video-clip-duration 6 \
  --video-transition-mode none \
  --n-threads 4 \
  --font-size 70 \
  --stroke-width 3.5 \
  --bgm-volume 0.12 \
  --video-script-prompt "Schreibe ein Skript fuer einen deutschen YouTube-Short von 35 bis 45 Sekunden, also maximal 100 Woerter. Der erste Satz ist der Aufhaenger und nennt sofort den ueberraschenden Kern, ohne Begruessung. Danach genau drei kurze Punkte, jeder mit einer konkreten Zahl. Kurze Hauptsaetze, Anrede per du. Kein Fazit, keine Aufforderung zu abonnieren. Gib ausschliesslich den Sprechtext aus."

echo "=== $(date '+%Y-%m-%d %H:%M') Hochladen ==="
"$UV_BIN" run --no-sync python scripts/youtube_upload.py \
  --scan --privacy "$PRIVACY" --limit "$UPLOAD_LIMIT"

echo "=== $(date '+%Y-%m-%d %H:%M') fertig ==="
