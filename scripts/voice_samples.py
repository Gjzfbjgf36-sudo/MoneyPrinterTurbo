#!/usr/bin/env python3
"""Erzeugt Hoerproben aller Edge-Stimmen einer Sprache zum Vergleichen.

Welche Stimme am besten traegt, laesst sich nicht aus einer Liste ablesen. Das
Skript spricht denselben Text mit jeder in Frage kommenden Stimme, mit dem
Tempo, das die Videos spaeter verwenden, und legt die Dateien nebeneinander ab.

Beispiele:
    uv run python scripts/voice_samples.py
    uv run python scripts/voice_samples.py --gender male --rate 1.2
    uv run python scripts/voice_samples.py --language en-US --text "Your text"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOICE_LIST = ROOT / "docs" / "voice-list.txt"

# Der Text enthaelt bewusst Umlaute, Zahlen und eine Frage: daran hoert man
# Aussprache, Betonung am Satzende und den Umgang mit Ziffern.
DEFAULT_TEXT = (
    "Apple zeigte Siri Recap beim Event am neunten September. "
    "Die Uhr fasst Gespräche automatisch zusammen, ganz ohne Audioaufnahme. "
    "Würdest du eine Uhr tragen, die mithört?"
)


def read_voices(language: str, gender: str) -> list[str]:
    """Stimmen aus docs/voice-list.txt, gefiltert nach Sprache und Geschlecht."""
    if not VOICE_LIST.exists():
        sys.exit(f"{VOICE_LIST} fehlt.")

    voices: list[str] = []
    current: str | None = None
    for line in VOICE_LIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            current = line.split(":", 1)[1].strip()
        elif line.startswith("Gender:") and current:
            voice_gender = line.split(":", 1)[1].strip().lower()
            if current.startswith(language) and gender in ("any", voice_gender):
                voices.append(current)
            current = None
    return voices


async def synthesize(voices: list[str], text: str, rate: float, out_dir: Path) -> None:
    try:
        import edge_tts
    except ImportError:
        sys.exit("edge-tts fehlt. Bitte 'uv sync --frozen' ausfuehren.")

    out_dir.mkdir(parents=True, exist_ok=True)
    # edge-tts erwartet das Tempo als Prozentangabe mit Vorzeichen, genau wie
    # app/services/voice.py es aus voice_rate berechnet.
    rate_str = f"{round((rate - 1.0) * 100):+d}%"

    for voice in voices:
        target = out_dir / f"{voice}.mp3"
        try:
            await edge_tts.Communicate(text, voice, rate=rate_str).save(str(target))
        except Exception as exc:
            print(f"  {voice}: fehlgeschlagen ({exc})")
            continue
        size = target.stat().st_size
        if size == 0:
            print(f"  {voice}: leere Datei, uebersprungen")
            target.unlink(missing_ok=True)
            continue
        print(f"  {voice}  ({size // 1024} KB)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Erzeugt Hoerproben der Edge-Stimmen zum Vergleichen."
    )
    parser.add_argument(
        "--language", default="de-DE", help="Sprachpraefix, etwa de-DE oder en-US"
    )
    parser.add_argument(
        "--gender",
        default="male",
        choices=["male", "female", "any"],
        help="nur maennliche, nur weibliche oder alle Stimmen",
    )
    parser.add_argument("--text", default=DEFAULT_TEXT, help="gesprochener Text")
    parser.add_argument(
        "--rate",
        type=float,
        default=1.2,
        help="Sprechtempo wie voice_rate im Preset (Standard: 1.2)",
    )
    parser.add_argument(
        "--out", default="storage/voice-samples", help="Zielverzeichnis"
    )
    args = parser.parse_args()

    voices = read_voices(args.language, args.gender)
    if not voices:
        sys.exit(
            f"Keine Stimmen fuer {args.language} ({args.gender}) gefunden. "
            "Sprachpraefix pruefen, etwa de-DE statt de."
        )

    out_dir = Path(args.out)
    print(f"{len(voices)} Stimme(n), Tempo {args.rate}x, Ziel {out_dir}:")
    asyncio.run(synthesize(voices, args.text, args.rate, out_dir))
    print(
        f"\nFertig. Dateien in {out_dir.resolve()} anhoeren und die beste "
        "als voice_name eintragen."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
