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

# Der Aufhaenger entscheidet ueber die ersten drei Sekunden, deshalb steht er
# als erste Regel. Die Wortgrenze haelt das Video im Shorts-Format.
SCRIPT_PROMPT="${SCRIPT_PROMPT:-Schreibe den Sprechtext fuer einen deutschen YouTube-Short von 30 bis 40 Sekunden, maximal 90 Woerter.
Satz 1 ist der Aufhaenger: eine ueberraschende Behauptung oder eine konkrete Zahl, die der Erwartung widerspricht. Keine Begruessung, keine Ankuendigung, kein Thema-nennen.
Dann genau drei Punkte, je ein bis zwei Saetze, jeder mit einer konkreten Zahl, Summe oder Zeitangabe.
Der letzte Satz ist eine einzelne konkrete Handlung, die man heute tun kann.
Kurze Hauptsaetze mit aktiven Verben, Anrede per du, keine Fuellwoerter, keine Fragen ans Publikum, keine Aufforderung zu abonnieren.
Gib ausschliesslich den Sprechtext aus, ohne Ueberschriften, Aufzaehlungszeichen oder Regieanweisungen.}"

if [ ! -f "$TASK_FILE" ]; then
  echo "Themenliste $TASK_FILE fehlt." >&2
  exit 1
fi

echo "=== $(date '+%Y-%m-%d %H:%M') Videos erzeugen ==="
# Kurzformat-Einstellungen: Zoom gegen den Diashow-Eindruck, 4-Sekunden-Schnitte
# für den Rhythmus, große Untertitel oberhalb der Plattform-Bedienelemente und
# eine leicht beschleunigte Stimme. Wort-für-Wort-Untertitel lassen sich nur
# über [ui] in der config.toml setzen, die CLI kennt dafür keinen Schalter.
"$UV_BIN" run --no-sync python cli.py \
  --batch-file "$TASK_FILE" \
  --video-language de-DE \
  --voice-name de-DE-KatjaNeural-Female \
  --voice-rate 1.1 \
  --video-aspect 9:16 \
  --video-clip-duration 4 \
  --video-transition-mode zoom-in \
  --match-materials-to-script \
  --font-size 80 \
  --stroke-width 4 \
  --subtitle-position custom \
  --custom-position 66 \
  --bgm-volume 0.12 \
  --n-threads 4 \
  --video-script-prompt "$SCRIPT_PROMPT"

echo "=== $(date '+%Y-%m-%d %H:%M') Hochladen ==="
"$UV_BIN" run --no-sync python scripts/youtube_upload.py \
  --scan --privacy "$PRIVACY" --limit "$UPLOAD_LIMIT"

echo "=== $(date '+%Y-%m-%d %H:%M') fertig ==="
