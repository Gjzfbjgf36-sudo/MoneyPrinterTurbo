"""Wann welches Video öffentlich wird.

Eigenes Modul, weil zwei Seiten dieselbe Antwort brauchen und sie sich nicht
widersprechen dürfen: ``scripts/youtube_upload.py`` setzt die Termine beim
Hochladen, und die Kanalseite der WebUI zeigt vorher an, welches Video wann
hochgeht. Zwei Implementierungen derselben Rechnung würden auseinanderlaufen,
und auffallen würde es erst, wenn ein Video zur falschen Zeit erscheint.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone


class SlotError(ValueError):
    """Unbrauchbare Zeitangabe — wird oben in eine Meldung übersetzt."""


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
            raise SlotError(f"Ungültige Uhrzeit: {part!r} (erwartet HH:MM)")
    if not slots:
        raise SlotError("Es braucht mindestens eine Uhrzeit, etwa 08:00,13:00")
    return sorted(set(slots))


def publish_slots(raw: str, count: int, now: datetime | None = None) -> list[datetime]:
    """Die nächsten count Veröffentlichungszeitpunkte ab jetzt.

    Bereits vergangene Uhrzeiten des heutigen Tages werden übersprungen; sind
    für heute keine mehr frei, geht es am Folgetag weiter. Damit verteilt ein
    nächtlicher Lauf seine Videos über den kommenden Tag — und ein Vorrat von
    sechs Videos reicht über zwei Tage, an denen niemand am Rechner sitzt.
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


def from_youtube_timestamp(raw: str) -> datetime | None:
    """Liest einen gespeicherten Termin zurück in die lokale Zeitzone.

    Gibt ``None`` statt zu werfen: der Eintrag stammt aus einer Datei, die
    auch von Hand bearbeitet worden sein kann, und ein unlesbarer Termin darf
    nicht die ganze Liste kosten.
    """
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None
