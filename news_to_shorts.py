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

# Die Render-Einstellungen sind fuer 9:16-Shorts (YouTube Shorts / TikTok)
# abgestimmt und gelten fuer jeden Task gleich. Der Recherche-Schritt liefert
# nur video_subject und video_script dazu.
SHORTS_PRESET: dict = {
    "video_aspect": "9:16",
    "video_fit_mode": "cover",
    "video_language": "de-DE",
    "video_source": "pexels",
    "video_concat_mode": "random",
    # Harte Schnitte statt Blenden: auf Shorts haelt schneller Bildwechsel
    # laenger fest als eine weiche Ueberblendung.
    "video_transition_mode": None,
    "video_clip_duration": 2,
    "video_clip_speed": 1.0,
    "match_materials_to_script": True,
    "video_count": 1,
    "voice_name": "de-DE-KatjaNeural-Female",
    "voice_rate": 1.15,
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
- video_script: der gesprochene Text, hoechstens 95 Woerter. Diese Grenze ist
  hart: laengere Skripte ergeben Videos ueber 45 Sekunden, und die laufen auf
  Shorts schlechter. Der erste Satz ist ein Hook von maximal 12 Woertern, der
  eine Frage aufwirft oder etwas Ueberraschendes behauptet. Danach kurze
  gesprochene Saetze, direkte Ansprache mit "du", kein Fachjargon, keine
  Begruessung, kein Intro. Nenne die handelnden Personen und Unternehmen beim
  Namen, damit die Meldung ueberpruefbar bleibt. Reiner Fliesstext ohne
  Ueberschriften, ohne Aufzaehlungszeichen, ohne Emojis, ohne Regieanweisungen.
  Schliesse mit einer Frage an die Zuschauer.
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


def build_manifest(videos: list[dict]) -> tuple[list[dict], list[dict]]:
    """Trennt Render-Manifest und Quellenbeleg.

    `quellen` und `datum` sind keine VideoParams-Felder; das Batch-Manifest lehnt
    unbekannte Felder ab. Sie wandern deshalb in eine eigene Datei, damit die
    Behauptungen im Video vor dem Hochladen nachpruefbar bleiben.
    """
    manifest: list[dict] = []
    sources: list[dict] = []
    for item in videos:
        quellen = item.get("quellen", [])
        task = dict(SHORTS_PRESET)
        task["video_subject"] = item["video_subject"]
        task["video_script"] = item["video_script"]
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
    parser.add_argument("--out", default="shorts.json", help="Zieldatei des Batch-Manifests")
    parser.add_argument(
        "--sources-out",
        default="shorts.sources.json",
        help="Datei mit Quellen und Datum je Video",
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

    videos = run_research(args.count, args.days, args.topic, args.model, args.timeout)
    manifest, sources = build_manifest(videos)

    Path(args.out).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(args.sources_out).write_text(
        json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n{len(manifest)} Videos geschrieben nach {args.out}")
    for entry in sources:
        print(f"  - {entry['video_subject']}  ({entry['woerter']} Woerter, {entry['datum']})")
    print(
        f"\nQuellen in {args.sources_out}. Pruefe sie, bevor du die Videos hochlaedst.\n"
        f"Weiter mit: uv run python cli.py --batch-file {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
