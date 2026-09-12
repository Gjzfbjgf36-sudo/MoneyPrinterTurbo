"""Prüft die mitgelieferten Kanal-Vorlagen unter channels/.

Die Vorlagen sind die Vorlage für jeden neuen Kanal des Nutzers. Wenn sich
VideoParams oder die erlaubten Werte ändern, sollen sie hier auffallen und
nicht erst beim nächtlichen Lauf.
"""

import json
from pathlib import Path

import pytest

from app.models.schema import VideoParams

ROOT = Path(__file__).resolve().parent.parent.parent
CHANNELS_DIR = ROOT / "channels"
# Nur diese Quellen kennt scripts/daily_run.ps1.
KNOWN_SOURCES = {"news", "queue"}


def channel_dirs() -> list[Path]:
    if not CHANNELS_DIR.exists():
        return []
    return sorted(
        path
        for path in CHANNELS_DIR.iterdir()
        if path.is_dir() and (path / "channel.json").exists()
    )


def test_repository_ships_at_least_one_channel_template():
    """Ohne Vorlage weiß niemand, wie ein Kanal aussehen muss."""
    assert channel_dirs(), "channels/ enthält keine Vorlage mit channel.json"


@pytest.mark.parametrize("channel", channel_dirs(), ids=lambda path: path.name)
def test_channel_config_is_usable(channel: Path):
    config = json.loads((channel / "channel.json").read_text(encoding="utf-8"))

    assert config.get("source") in KNOWN_SOURCES, (
        f"{channel.name}: source muss eine von {sorted(KNOWN_SOURCES)} sein"
    )
    assert str(config.get("topic", "")).strip(), f"{channel.name}: topic fehlt"
    assert int(config.get("topics_per_run", 0)) >= 1

    # Die Kategorie geht als --category an youtube_upload.py und muss dort
    # die Ziffernprüfung bestehen.
    category = str(config.get("category", "")).strip()
    assert category.isdigit(), f"{channel.name}: category muss eine Zahl sein"

    for slot in str(config.get("publish_at", "")).split(","):
        slot = slot.strip()
        if not slot:
            continue
        hour, minute = (int(value) for value in slot.split(":", 1))
        assert 0 <= hour < 24 and 0 <= minute < 60, (
            f"{channel.name}: ungültige Uhrzeit {slot!r} in publish_at"
        )


@pytest.mark.parametrize("channel", channel_dirs(), ids=lambda path: path.name)
def test_queue_entries_are_valid_video_params(channel: Path):
    """Ein Warteschlangenkanal braucht ein Manifest, das cli.py auch annimmt."""
    config = json.loads((channel / "channel.json").read_text(encoding="utf-8"))
    queue = channel / "tasks.jsonl"

    if config.get("source") != "queue":
        return

    assert queue.exists(), f"{channel.name}: source=queue, aber tasks.jsonl fehlt"
    entries = [
        line for line in queue.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert entries, f"{channel.name}: tasks.jsonl ist leer"

    for index, line in enumerate(entries, start=1):
        params = VideoParams(**json.loads(line))
        assert params.video_subject or params.video_script, (
            f"{channel.name}, Zeile {index}: braucht video_subject oder video_script"
        )
