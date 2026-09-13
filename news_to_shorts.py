#!/usr/bin/env python3
"""Recherchiert aktuelle Tech-/KI-News und schreibt daraus ein MoneyPrinterTurbo-Batch.

MoneyPrinterTurbo selbst hat keinen Web-Zugang: der Claude-Code-Adapter ruft die
CLI mit `--tools ""` auf, damit sie ausschliesslich Text erzeugt. Dieses Skript
setzt deshalb eine eigene Recherche-Stufe davor. Es ruft die `claude` CLI mit
aktivierter Websuche auf, laesst sie fertige Skripte schreiben und giesst das
Ergebnis in ein Batch-Manifest, das `cli.py --batch-file` direkt verarbeitet.

Weil `video_script` gesetzt ist, ueberspringt MoneyPrinterTurbo seine eigene
Skript-Generierung. Die Fakten stammen damit aus der Recherche und nicht aus dem
Trainingsstand des Modells.

Beispiel:
    uv run python news_to_shorts.py --count 3
    uv run python cli.py --batch-file .\\shorts.json --stop-at script
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Die Render-Einstellungen sind fuer 9:16-Shorts (YouTube Shorts / TikTok)
# abgestimmt und gelten fuer jeden Task gleich. Der Recherche-Schritt liefert
# nur video_subject und video_script dazu.
SHORTS_PRESET: dict = {
    "video_aspect": "9:16",
    "video_fit_mode": "cover",
    "video_language": "de-DE",
    "video_source": "pexels",
    "video_concat_mode": "random",
    # ZoomIn ist keine Ueberblendung, sondern ein durchgehender Zoom von 1,0
    # auf 1,2 ueber den ganzen Clip. Stockmaterial steht oft still; die
    # staendige Bewegung nimmt dem Ergebnis den Diashow-Eindruck.
    "video_transition_mode": "ZoomIn",
    "video_clip_duration": 2,
    # Leichte Beschleunigung der Clips: merklich straffer, ohne dass die
    # Bewegung im Bild unnatuerlich wirkt.
    "video_clip_speed": 1.08,
    "match_materials_to_script": True,
    "video_count": 1,
    # Die "Multilingual"-Stimmen sind Microsofts neuere Generation und klingen
    # weniger abgelesen. Vergleichen mit scripts/voice_samples.py; je Kanal
    # ueberschreibbar in channels/<name>/channel.json.
    "voice_name": "de-DE-FlorianMultilingualNeural-Male",
    "voice_rate": 1.2,
    "voice_volume": 1.0,
    "bgm_type": "random",
    "bgm_volume": 0.12,
    "subtitle_enabled": True,
    # Sitzt ueber der UI-Leiste von TikTok und YouTube Shorts, die den unteren
    # Rand verdeckt.
    "subtitle_position": "two_thirds_bottom",
    "subtitle_display_mode": "word_by_word",
    "subtitle_animation": "pop_spring",
    "font_name": "BeVietnamPro-Bold.ttf",
    "font_size": 84,
    "text_fore_color": "#FFFFFF",
    "text_background_color": False,
    "stroke_color": "#000000",
    "stroke_width": 3.0,
    "n_threads": 4,
}

RESEARCH_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "videos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "video_subject": {"type": "string"},
                    "video_script": {"type": "string"},
                    "quellen": {"type": "array", "items": {"type": "string"}},
                    "datum": {"type": "string"},
                },
                "required": ["video_subject", "video_script", "quellen", "datum"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["videos"],
    "additionalProperties": False,
}


# Felder, die ein Kanal in seiner channel.json ueberschreiben darf. Stimme und
# Schnitt sind Geschmack, kein Programmablauf: wer sie hier im Code aendert,
# bekommt beim naechsten Update einen Merge-Konflikt.
CHANNEL_OVERRIDES = (
    "voice_name",
    "voice_rate",
    "video_clip_duration",
    "video_clip_speed",
    "video_transition_mode",
    "subtitle_position",
    "subtitle_display_mode",
    "subtitle_animation",
    "font_name",
    "font_size",
    "stroke_width",
    "text_fore_color",
    "text_background_color",
    "bgm_volume",
)


def preset_for_channel(channel: str | None) -> dict:
    """Das Kurzformat, ueberschrieben mit den Einstellungen des Kanals."""
    preset = dict(SHORTS_PRESET)
    if not channel:
        return preset

    config_file = ROOT / "channels" / channel / "channel.json"
    if not config_file.exists():
        raise SystemExit(f"Kanal {channel!r} hat keine channel.json.")
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"channel.json von {channel!r} ist kein gueltiges JSON: {exc}")

    for field in CHANNEL_OVERRIDES:
        if field in config:
            preset[field] = config[field]
    return preset


def build_research_prompt(count: int, days: int, topic: str) -> str:
    return f"""Recherchiere mit der Websuche {count} aktuelle Meldungen aus dem Bereich {topic}
aus den letzten {days} Tagen. Schreibe zu jeder ein fertiges Skript fuer ein
vertikales Short-Video.

Vorgehen:
1. Suche nach aktuellen Meldungen und oeffne die Quellen, um die Details zu pruefen.
2. Verwende nur Fakten, die du in den Quellen wirklich gelesen hast. Erfinde keine
   Zahlen, Daten, Zitate oder Firmennamen. Wenn ein Detail unklar bleibt, lass es weg.
3. Nimm keine Meldung, die du nicht mit mindestens einer belastbaren Quelle belegen kannst.

Fuer jedes Video:
- video_subject: der Titel der Meldung, kurz und konkret.
- video_script: der gesprochene Text, 55 bis 70 Woerter. Beide Grenzen gelten:
  gemessen entspricht das 23 bis 29 Sekunden. Kuerzer wirkt duenn, weil fuer
  die drei Aussagen kein Platz bleibt; laenger wird abgebrochen, und ein Short,
  das zu Ende gesehen wird, wird weiter ausgespielt. Zaehle die Woerter nach,
  bevor du antwortest.
  Der erste Satz ist der Hook: hoechstens 8 Woerter, eine konkrete Zahl oder
  eine Behauptung, die der Erwartung widerspricht. Kein "In diesem Video",
  keine Begruessung, keine Ankuendigung des Themas.
  Danach hoechstens drei Aussagen, je ein Satz, jede mit etwas Konkretem:
  einer Zahl, einem Namen, einem Datum. Nenne die handelnden Personen und
  Unternehmen beim Namen, damit die Meldung ueberpruefbar bleibt.
  Keine Fuellwoerter ("eigentlich", "quasi", "im Grunde"), keine Einschuebe,
  keine Nebensaetze, wo ein Hauptsatz reicht. Aktive Verben.
  Der letzte Satz ist eine kurze Frage an die Zuschauer.
  Reiner Fliesstext ohne Ueberschriften, ohne Aufzaehlungszeichen, ohne
  Emojis, ohne Regieanweisungen.
- quellen: die URLs, auf die du dich stuetzt.
- datum: das Veroeffentlichungsdatum der Meldung als YYYY-MM-DD."""


def run_research(count: int, days: int, topic: str, model: str, timeout: int) -> list[dict]:
    cli = shutil.which("claude")
    if not cli:
        raise SystemExit(
            "claude CLI nicht gefunden. Installiere Claude Code und melde dich mit "
            "`claude` an, bevor du dieses Skript benutzt."
        )

    command = [
        cli,
        "-p",
        build_research_prompt(count, days, topic),
        "--allowedTools",
        "WebSearch,WebFetch",
        "--permission-mode",
        "auto",
        "--permission-prompts",
        "none",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(RESEARCH_SCHEMA),
    ]
    if model:
        command += ["--model", model]

    print(f"recherchiere {count} Meldungen zu '{topic}' ...", file=sys.stderr)
    completed = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", timeout=timeout
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"claude CLI beendet mit Code {completed.returncode}:\n"
            f"{(completed.stderr or completed.stdout)[:800]}"
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Antwort der CLI war kein JSON: {exc}") from exc

    if payload.get("is_error"):
        raise SystemExit(f"Recherche fehlgeschlagen: {str(payload.get('result'))[:500]}")

    structured = payload.get("structured_output") or {}
    videos = structured.get("videos") or []
    if not videos:
        raise SystemExit(
            "Die Recherche hat keine Meldungen geliefert. Versuch es mit einem "
            "groesseren --days-Fenster oder einem breiteren --topic."
        )
    return videos


def build_manifest(
    videos: list[dict], preset: dict | None = None, channel: str = ""
) -> tuple[list[dict], list[dict]]:
    """Trennt Render-Manifest und Quellenbeleg.

    `quellen` und `datum` sind keine VideoParams-Felder; das Batch-Manifest lehnt
    unbekannte Felder ab. Sie wandern deshalb in eine eigene Datei, damit die
    Behauptungen im Video vor dem Hochladen nachpruefbar bleiben.
    """
    preset = preset if preset is not None else SHORTS_PRESET
    manifest: list[dict] = []
    sources: list[dict] = []
    for item in videos:
        quellen = item.get("quellen", [])
        task = dict(preset)
        task["video_subject"] = item["video_subject"]
        task["video_script"] = item["video_script"]
        if channel:
            # Steht spaeter im fertigen Task und sagt der Oberflaeche, in
            # welchen Kanal dieses Video gehoert. Ohne das liegen die Videos
            # aller Kanaele ununterscheidbar nebeneinander.
            task["channel"] = channel
        if quellen:
            # Landet woertlich unter der Beschreibung des Uploads. Die erste
            # Quelle ist die, auf der die Meldung hauptsaechlich beruht.
            task["description_suffix"] = f"Quelle: {quellen[0]}"
        manifest.append(task)
        sources.append(
            {
                "video_subject": item["video_subject"],
                "datum": item.get("datum", ""),
                "quellen": item.get("quellen", []),
                "woerter": len(item["video_script"].split()),
            }
        )
    return manifest, sources


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recherchiert aktuelle News und schreibt ein MoneyPrinterTurbo-Batch."
    )
    parser.add_argument("--count", type=int, default=3, help="Anzahl Videos (Standard: 3)")
    parser.add_argument("--days", type=int, default=7, help="Wie weit zurueck gesucht wird")
    parser.add_argument(
        "--topic",
        default="Technologie und kuenstliche Intelligenz",
        help="Themenbereich der Recherche",
    )
    parser.add_argument(
        "--channel",
        default=None,
        metavar="NAME",
        help=(
            "Kanal, dessen channel.json Stimme und Schnitt vorgibt. Ohne "
            "Angabe gilt das eingebaute Kurzformat"
        ),
    )
    parser.add_argument("--out", default="shorts.json", help="Zieldatei des Batch-Manifests")
    parser.add_argument(
        "--sources-out",
        default="shorts.sources.json",
        help="Datei mit Quellen und Datum je Video",
    )
    parser.add_argument(
        "--split",
        action="store_true",
        help=(
            "zusaetzlich ein Manifest je Video schreiben (shorts.1.json, "
            "shorts.2.json, ...), damit die Uploads ueber den Tag verteilt "
            "in getrennten Laeufen erfolgen koennen"
        ),
    )
    parser.add_argument(
        "--model", default="", help="Modell fuer die Recherche, z. B. claude-sonnet-5"
    )
    parser.add_argument(
        "--timeout", type=int, default=900, help="Zeitlimit der Recherche in Sekunden"
    )
    args = parser.parse_args()

    if args.count < 1:
        raise SystemExit("--count muss mindestens 1 sein")

    preset = preset_for_channel(args.channel)
    videos = run_research(args.count, args.days, args.topic, args.model, args.timeout)
    manifest, sources = build_manifest(videos, preset, args.channel or "")

    Path(args.out).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(args.sources_out).write_text(
        json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    split_paths: list[Path] = []
    if args.split:
        # Ein Manifest je Video: cli.py rendert immer die ganze Datei, also
        # braucht jeder ueber den Tag verteilte Lauf seine eigene.
        out_path = Path(args.out)
        for index, task in enumerate(manifest, start=1):
            part = out_path.with_name(f"{out_path.stem}.{index}{out_path.suffix}")
            part.write_text(
                json.dumps([task], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            split_paths.append(part)

    print(f"\n{len(manifest)} Videos geschrieben nach {args.out}")
    for entry in sources:
        print(f"  - {entry['video_subject']}  ({entry['woerter']} Woerter, {entry['datum']})")
    if split_paths:
        print("\nEinzelne Manifeste:")
        for part in split_paths:
            print(f"  uv run python cli.py --batch-file .\\{part.name}")
    print(
        f"\nQuellen in {args.sources_out}. Pruefe sie, bevor du die Videos hochlaedst."
    )
    if not split_paths:
        print(f"Weiter mit: uv run python cli.py --batch-file {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
