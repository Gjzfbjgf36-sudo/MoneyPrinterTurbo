#!/usr/bin/env python3
"""Lädt fertige MoneyPrinterTurbo-Videos direkt zu YouTube hoch.

Nutzt die YouTube Data API v3 mit OAuth (kostenlos, kein Drittanbieter).
Titel, Beschreibung und Tags entstehen aus der script.json des Tasks.

Einrichtung einmalig:
  1. Google-Cloud-Projekt anlegen, "YouTube Data API v3" aktivieren
  2. OAuth-Client vom Typ "Desktopanwendung" erstellen
  3. Die JSON-Datei als client_secret.json ins Projektverzeichnis legen
  4. uv pip install google-api-python-client google-auth-oauthlib

Aufrufe:
  python scripts/youtube_upload.py --scan --dry-run     # nur anzeigen
  python scripts/youtube_upload.py --scan               # alle neuen hochladen
  python scripts/youtube_upload.py pfad/zu/final-1.mp4  # einzelne Datei
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "storage" / "tasks"
STATE_FILE = ROOT / "storage" / "youtube-uploads.json"
TOKEN_FILE = ROOT / "storage" / "youtube-token.json"
CLIENT_SECRET_FILE = ROOT / "client_secret.json"
# Je Kanal ein eigener OAuth-Token, ein eigener Upload-Verlauf und ein eigener
# Kanaltext. Der OAuth-Client (client_secret.json) bleibt gemeinsam: er gehört
# zum Google-Cloud-Projekt, nicht zum YouTube-Konto, und beim Anmelden wählt
# man den jeweiligen Kanal aus.
CHANNEL_STORAGE_DIR = ROOT / "storage" / "channels"
CHANNELS_DIR = ROOT / "channels"
# Der Kanalname wird zu einem Verzeichnisnamen. Ohne Prüfung könnte "../.."
# den Token außerhalb des Projekts ablegen oder eine fremde Datei überschreiben.
CHANNEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
# 27 = Education. Andere gängige Werte: 22 Menschen & Blogs, 24 Unterhaltung.
CATEGORY_ID = "27"
TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 4900
# Die Pexels-API-Bedingungen verlangen eine sichtbare Namensnennung, sobald
# damit erzeugte Inhalte veröffentlicht werden.
PEXELS_CREDIT = "Videomaterial: Pexels (https://www.pexels.com)"
# Optionaler Kanaltext, der an jede Beschreibung angehängt wird: Haftungs-
# ausschluss, Impressumshinweis, Kanalregeln. Fehlt die Datei, bleibt die
# Beschreibung unverändert.
FOOTER_FILE = ROOT / "youtube-footer.txt"


def channel_paths(channel: str | None) -> dict[str, Path]:
    """Token, Upload-Verlauf und Kanaltext für einen Kanal.

    Ohne Kanalnamen bleiben es die bisherigen Pfade im Projektstamm, damit ein
    bestehender Einzelkanal nach dem Update weiterläuft und sich nicht neu
    anmelden muss.
    """
    if channel is None:
        # Nur das fehlende Argument heißt "kein Kanal". Ein ausdrücklich
        # übergebenes --channel "" ist ein Tippfehler und darf nicht
        # stillschweigend im Standardkanal landen.
        return {
            "state": ROOT / "storage" / "youtube-uploads.json",
            "token": ROOT / "storage" / "youtube-token.json",
            "footer": ROOT / "youtube-footer.txt",
        }
    if not CHANNEL_NAME_PATTERN.match(channel):
        sys.exit(
            f"Ungültiger Kanalname {channel!r}. Erlaubt sind Buchstaben, "
            "Ziffern, Bindestrich und Unterstrich, beginnend mit "
            "Buchstabe oder Ziffer."
        )
    return {
        "state": CHANNEL_STORAGE_DIR / channel / "youtube-uploads.json",
        "token": CHANNEL_STORAGE_DIR / channel / "youtube-token.json",
        "footer": CHANNELS_DIR / channel / "footer.txt",
    }


def apply_channel(channel: str | None) -> None:
    """Schaltet die Modulpfade auf den gewählten Kanal um."""
    global STATE_FILE, TOKEN_FILE, FOOTER_FILE
    paths = channel_paths(channel)
    STATE_FILE = paths["state"]
    TOKEN_FILE = paths["token"]
    FOOTER_FILE = paths["footer"]


def apply_category(category: str | None) -> None:
    """Setzt die YouTube-Kategorie, wenn der Kanal eine eigene braucht."""
    global CATEGORY_ID
    category = (category or "").strip()
    if not category:
        return
    if not category.isdigit():
        sys.exit(f"Ungültige Kategorie-ID {category!r}; erwartet wird eine Zahl.")
    CATEGORY_ID = category


def load_state() -> dict:
    """Bereits hochgeladene Dateien, damit --scan nichts doppelt hochlädt."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Warnung: Upload-Verlauf nicht lesbar, starte leer ({exc})")
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_task_metadata(video_path: Path) -> dict:
    """Liest script.json aus dem Task-Ordner des Videos."""
    script_file = video_path.parent / "script.json"
    if not script_file.exists():
        return {}
    try:
        return json.loads(script_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Warnung: {script_file} nicht lesbar ({exc})")
        return {}


def build_title(metadata: dict, fallback: str) -> str:
    """Titel aus dem Videothema, gekürzt auf das YouTube-Limit inkl. #Shorts."""
    params = metadata.get("params") or {}
    subject = str(params.get("video_subject") or "").strip() or fallback
    suffix = " #Shorts"
    if len(subject) + len(suffix) > TITLE_LIMIT:
        subject = subject[: TITLE_LIMIT - len(suffix) - 1].rstrip() + "…"
    return subject + suffix


def read_footer() -> str:
    """Kanaltext aus youtube-footer.txt, falls vorhanden."""
    if not FOOTER_FILE.exists():
        return ""
    try:
        return FOOTER_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        print(f"Warnung: {FOOTER_FILE.name} nicht lesbar ({exc})")
        return ""


def build_description(metadata: dict) -> str:
    """Beschreibung aus Skript, Hashtags und der Pexels-Namensnennung."""
    blocks = []
    script = str(metadata.get("script") or "").strip()
    if script:
        blocks.append(script)

    terms = metadata.get("search_terms") or []
    if isinstance(terms, str):
        terms = [term.strip() for term in terms.split(",") if term.strip()]
    hashtags = [
        "#" + "".join(word.capitalize() for word in str(term).split())
        for term in terms
        if str(term).strip()
    ]
    if hashtags:
        blocks.append(" ".join(["#shorts"] + hashtags[:5]))

    # description_suffix trägt bei Recherchevideos die Quelle der Behauptungen.
    # Es steht vor dem Pexels-Hinweis, weil es zum Inhalt gehört und nicht zur
    # Lizenz des Bildmaterials.
    params = metadata.get("params") or {}
    suffix = str(params.get("description_suffix") or "").strip()
    if suffix:
        blocks.append(suffix)

    blocks.append(PEXELS_CREDIT)

    footer = read_footer()
    if footer:
        blocks.append(footer)

    description = "\n\n".join(blocks)
    return description[:DESCRIPTION_LIMIT]


def build_tags(metadata: dict) -> list[str]:
    terms = metadata.get("search_terms") or []
    if isinstance(terms, str):
        terms = [term.strip() for term in terms.split(",") if term.strip()]
    return [str(term)[:30] for term in terms][:10]


def state_key(video_path: Path) -> str:
    """Schlüssel im Upload-Verlauf: relativ zum Projekt, sonst absolut."""
    try:
        return str(video_path.relative_to(ROOT))
    except ValueError:
        return str(video_path)


def find_new_videos(state: dict) -> list[Path]:
    """Alle final-*.mp4 unter storage/tasks, die noch nicht hochgeladen sind."""
    if not TASKS_DIR.exists():
        return []
    videos = sorted(
        TASKS_DIR.glob("*/final-*.mp4"), key=lambda path: path.stat().st_mtime
    )
    return [video for video in videos if state_key(video) not in state]


def parse_slot_times(raw: str) -> list[time]:
    """Wandelt "08:00,13:00,18:00" in sortierte Uhrzeiten der lokalen Zeitzone."""
    slots = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            hour, minute = (int(value) for value in part.split(":", 1))
            slots.append(time(hour=hour, minute=minute))
        except ValueError:
            sys.exit(f"Ungültige Uhrzeit in --publish-at: {part!r} (erwartet HH:MM)")
    if not slots:
        sys.exit("--publish-at braucht mindestens eine Uhrzeit, etwa 08:00,13:00")
    return sorted(set(slots))


def publish_slots(raw: str, count: int, now: datetime | None = None) -> list[datetime]:
    """Die nächsten count Veröffentlichungszeitpunkte ab jetzt.

    Bereits vergangene Uhrzeiten des heutigen Tages werden übersprungen; sind
    für heute keine mehr frei, geht es am Folgetag weiter. Damit verteilt ein
    nächtlicher Lauf seine Videos über den kommenden Tag.
    """
    if count <= 0:
        return []
    now = now or datetime.now().astimezone()
    times = parse_slot_times(raw)
    result: list[datetime] = []
    day = now.date()
    while len(result) < count:
        for slot_time in times:
            # Den Zeitzonen-Versatz je Tag neu bestimmen statt den von heute
            # weiterzureichen: ueber eine Zeitumstellung hinweg laegen die
            # Termine der Folgetage sonst eine Stunde daneben.
            candidate = datetime.combine(day, slot_time).astimezone()
            if candidate > now:
                result.append(candidate)
                if len(result) == count:
                    break
        day += timedelta(days=1)
    return result


def to_youtube_timestamp(moment: datetime) -> str:
    """RFC-3339 in UTC, wie es die YouTube-API für publishAt erwartet."""
    return (
        moment.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def get_youtube_client():
    """OAuth-Flow; der Token wird gespeichert, der Browser öffnet sich nur einmal."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit(
            "Fehlende Pakete. Bitte ausführen:\n"
            "  uv pip install google-api-python-client google-auth-oauthlib"
        )

    credentials = None
    if TOKEN_FILE.exists():
        try:
            credentials = Credentials.from_authorized_user_file(
                str(TOKEN_FILE), SCOPES
            )
        except (OSError, ValueError) as exc:
            print(f"Warnung: {TOKEN_FILE.name} unbrauchbar ({exc}), melde neu an.")
            credentials = None

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception as exc:
            # Google widerruft das Refresh-Token eines OAuth-Clients im Status
            # "Testing" nach sieben Tagen. Ohne diesen Zweig endet der
            # naechtliche Lauf dann mit einem Traceback statt mit einer neuen
            # Anmeldung — und bei einem geplanten Lauf sieht das niemand.
            print(f"Anmeldung abgelaufen ({exc}), starte die Anmeldung neu.")
            credentials = None

    if not credentials or not credentials.valid:
        if not CLIENT_SECRET_FILE.exists():
            sys.exit(
                f"{CLIENT_SECRET_FILE.name} fehlt. OAuth-Client vom Typ "
                "'Desktopanwendung' in der Google Cloud Console erstellen und "
                f"die JSON-Datei nach {CLIENT_SECRET_FILE} legen."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRET_FILE), SCOPES
        )
        credentials = flow.run_local_server(port=0)

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)
    return build("youtube", "v3", credentials=credentials)


def upload(youtube, video_path: Path, title: str, description: str,
           tags: list[str], privacy: str, publish_at: datetime | None = None) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": CATEGORY_ID,
        },
        "status": {
            # Ein geplantes Video muss bis zum Termin privat bleiben; YouTube
            # schaltet es dann selbst öffentlich.
            "privacyStatus": "private" if publish_at else privacy,
            # YouTube verlangt eine Angabe zur Zielgruppe.
            "selfDeclaredMadeForKids": False,
        },
    }
    if publish_at:
        body["status"]["publishAt"] = to_youtube_timestamp(publish_at)
    media = MediaFileUpload(str(video_path), chunksize=4 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )

    response = None
    try:
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"  {int(status.progress() * 100)} % übertragen")
    except HttpError as exc:
        if exc.resp.status == 403 and "quota" in str(exc).lower():
            sys.exit(
                "YouTube-Tageskontingent erschöpft (ein Upload kostet ~1.600 von "
                "10.000 Einheiten, also etwa 6 Uploads pro Tag). Morgen erneut "
                "versuchen — bereits hochgeladene Videos werden übersprungen."
            )
        raise
    return response["id"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lädt fertige MoneyPrinterTurbo-Videos zu YouTube hoch."
    )
    parser.add_argument("videos", nargs="*", help="Pfade zu final-*.mp4")
    parser.add_argument(
        "--channel", default=None, metavar="NAME",
        help=(
            "Kanal, in den hochgeladen wird. Token, Upload-Verlauf und "
            "Kanaltext liegen dann unter storage/channels/NAME/ bzw. "
            "channels/NAME/. Ohne Angabe gelten die Pfade im Projektstamm."
        ),
    )
    parser.add_argument(
        "--category", default=None, metavar="ID",
        help=(
            "YouTube-Kategorie-ID, etwa 27 Bildung, 28 Wissenschaft und "
            f"Technik, 24 Unterhaltung (Standard: {CATEGORY_ID})"
        ),
    )
    parser.add_argument(
        "--scan", action="store_true",
        help=(
            "alle noch nicht hochgeladenen Videos unter storage/tasks "
            "verwenden. Bei mehreren Kanälen nicht benutzen: der Scan sieht "
            "auch die Videos der anderen Kanäle und würde sie hier "
            "veröffentlichen. Dann die Pfade ausdrücklich übergeben."
        ),
    )
    parser.add_argument(
        "--privacy", choices=["private", "unlisted", "public"], default="private",
        help="Sichtbarkeit auf YouTube (Standard: private)",
    )
    parser.add_argument(
        "--limit", type=int, default=5,
        help=(
            "maximale Uploads pro --scan; schützt vor dem Tageskontingent. "
            "Ausdrücklich genannte Pfade werden immer alle hochgeladen, sonst "
            "fielen genau die Videos still unter den Tisch, die der Aufrufer "
            "gerade erzeugt hat"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="nur Titel und Beschreibung anzeigen, nichts hochladen",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="auch Videos hochladen, die laut Verlauf schon auf YouTube sind",
    )
    parser.add_argument(
        "--publish-at", default=None, metavar="HH:MM[,HH:MM...]",
        help=(
            "Veröffentlichung planen statt sofort freizugeben; die Videos "
            "belegen der Reihe nach die nächsten freien Uhrzeiten "
            "(Beispiel: 08:00,13:00,18:00)"
        ),
    )
    args = parser.parse_args()

    apply_channel(args.channel)
    apply_category(args.category)
    if args.channel:
        print(f"Kanal: {args.channel}")

    state = load_state()
    if args.scan:
        targets = find_new_videos(state)
    else:
        # Auch bei ausdrücklich genannten Pfaden gegen den Verlauf prüfen. Ein
        # versehentlich wiederholter Aufruf darf kein zweites Video im Kanal
        # anlegen; --force bleibt der bewusste Weg für eine Neuveröffentlichung.
        targets = []
        for video in args.videos:
            path = Path(video).resolve()
            known = state.get(state_key(path))
            if known and not args.force:
                print(
                    f"übersprungen, bereits hochgeladen: {path}\n"
                    f"  {known.get('url', known.get('video_id', ''))}\n"
                    f"  erneut hochladen mit --force"
                )
                continue
            targets.append(path)

    if not targets:
        print("Keine neuen Videos gefunden.")
        return

    if args.scan and len(targets) > args.limit:
        # Nur beim Scan ist die Menge unbekannt gross. Genannte Pfade sind die
        # bewusste Auswahl des Aufrufers und werden nicht beschnitten: der
        # Tageslauf uebergibt genau die Videos, die er gerade gerendert hat,
        # und weil er ohne --scan arbeitet, wuerde sie niemand nachholen.
        print(
            f"{len(targets)} neue Videos gefunden, lade die ersten "
            f"{args.limit} hoch (--limit)."
        )
        targets = targets[: args.limit]

    schedule = (
        publish_slots(args.publish_at, len(targets)) if args.publish_at else []
    )
    if schedule and args.privacy != "private":
        # publishAt und ein oeffentliches Video schliessen sich aus: YouTube
        # lehnt die Kombination ab. Der Termin gewinnt, der Hinweis bleibt.
        print(
            f"Hinweis: --privacy {args.privacy} wird ignoriert; geplante Videos "
            "bleiben bis zum Termin privat."
        )
    youtube = None if args.dry_run else get_youtube_client()

    for index, video_path in enumerate(targets):
        if not video_path.exists():
            print(f"übersprungen, Datei fehlt: {video_path}")
            continue

        metadata = read_task_metadata(video_path)
        title = build_title(metadata, fallback=video_path.parent.name)
        description = build_description(metadata)
        tags = build_tags(metadata)
        size_mb = video_path.stat().st_size / 1024 / 1024

        print(f"\n{video_path}  ({size_mb:.1f} MB)")
        print(f"  Titel:       {title}")
        print(f"  Tags:        {', '.join(tags) or '—'}")
        publish_at = schedule[index] if schedule else None
        if publish_at:
            print(f"  Sichtbarkeit: geplant für {publish_at:%d.%m.%Y %H:%M}")
        else:
            print(f"  Sichtbarkeit: {args.privacy}")
        print("  Beschreibung:")
        for line in description.splitlines():
            print(f"    {line}")

        if args.dry_run:
            continue

        video_id = upload(
            youtube, video_path, title, description, tags, args.privacy, publish_at
        )
        url = f"https://youtu.be/{video_id}"
        print(f"  hochgeladen: {url}")
        state[state_key(video_path)] = {
            "video_id": video_id,
            "url": url,
            "privacy": "private" if publish_at else args.privacy,
            "publish_at": to_youtube_timestamp(publish_at) if publish_at else None,
        }
        save_state(state)


if __name__ == "__main__":
    main()
