#!/usr/bin/env sh
# Rendert die naechsten Themen aus der Warteschlange und plant sie auf YouTube ein.
#
# Aufruf:   ./scripts/daily_run.sh
# Anpassen: TOPICS_PER_RUN=2 PUBLISH_AT=09:00,17:00 ./scripts/daily_run.sh
#
# Abgearbeitete Themen wandern nach tasks-done.jsonl, damit ein taeglicher
# Cron-Lauf ohne Zutun weiterlaeuft und keine Wiederholungen erzeugt.
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"

UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"
TASK_FILE="${TASK_FILE:-tasks.jsonl}"
DONE_FILE="${DONE_FILE:-tasks-done.jsonl}"
TOPICS_PER_RUN="${TOPICS_PER_RUN:-3}"
PUBLISH_AT="${PUBLISH_AT:-08:00,13:00,18:00}"

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

RUN_FILE=$(mktemp "${TMPDIR:-/tmp}/mpt-run.XXXXXX")
REST_FILE=$(mktemp "${TMPDIR:-/tmp}/mpt-rest.XXXXXX")
trap 'rm -f "$RUN_FILE" "$REST_FILE"' EXIT

# Leerzeilen ignorieren, damit eine haendisch editierte Liste nicht zu
# leeren Durchlaeufen fuehrt.
grep -v '^[[:space:]]*$' "$TASK_FILE" > "$REST_FILE" || true
head -n "$TOPICS_PER_RUN" "$REST_FILE" > "$RUN_FILE"

if [ ! -s "$RUN_FILE" ]; then
  echo "Warteschlange $TASK_FILE ist leer, nichts zu tun."
  exit 0
fi

echo "=== $(date '+%Y-%m-%d %H:%M') $(wc -l < "$RUN_FILE" | tr -d ' ') Video(s) erzeugen ==="
# Kurzformat-Einstellungen: Zoom gegen den Diashow-Eindruck, 4-Sekunden-Schnitte
# fuer den Rhythmus, grosse Untertitel oberhalb der Plattform-Bedienelemente und
# eine leicht beschleunigte Stimme. Wort-fuer-Wort-Untertitel lassen sich nur
# ueber [ui] in der config.toml setzen, die CLI kennt dafuer keinen Schalter.
"$UV_BIN" run --no-sync python cli.py \
  --batch-file "$RUN_FILE" \
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

# Erst nach dem Rendern aus der Warteschlange nehmen. Gescheiterte Themen
# stehen danach in $DONE_FILE und koennen von dort zurueckkopiert werden.
cat "$RUN_FILE" >> "$DONE_FILE"
tail -n +"$((TOPICS_PER_RUN + 1))" "$REST_FILE" > "$TASK_FILE"
echo "Warteschlange: $(grep -c '' "$TASK_FILE" || true) Thema/Themen uebrig"

echo "=== $(date '+%Y-%m-%d %H:%M') Hochladen und einplanen ==="
"$UV_BIN" run --no-sync python scripts/youtube_upload.py \
  --scan --limit "$TOPICS_PER_RUN" --publish-at "$PUBLISH_AT"

echo "=== $(date '+%Y-%m-%d %H:%M') fertig ==="
