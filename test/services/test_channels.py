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


# Die Tempo-Einstellungen entscheiden ueber den Eindruck der Shorts. Weichen
# Warteschlangen-Vorlage und Recherche-Preset voneinander ab, sehen die Videos
# eines Kanals anders aus als die des anderen, ohne dass es jemand merkt.
PACING_FIELDS = (
    "video_aspect",
    "video_clip_duration",
    "video_clip_speed",
    "video_transition_mode",
    "voice_rate",
    "subtitle_position",
    "subtitle_display_mode",
    "subtitle_animation",
    "font_size",
    "stroke_width",
)


@pytest.mark.parametrize("channel", channel_dirs(), ids=lambda path: path.name)
def test_queue_template_matches_the_shorts_preset(channel: Path):
    """Beide Themenquellen muessen dasselbe Kurzformat erzeugen."""
    import sys

    sys.path.insert(0, str(ROOT))
    from news_to_shorts import SHORTS_PRESET

    config = json.loads((channel / "channel.json").read_text(encoding="utf-8"))
    if config.get("source") != "queue":
        return

    queue = channel / "tasks.jsonl"
    for index, line in enumerate(queue.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        entry = json.loads(line)
        for field in PACING_FIELDS:
            assert entry.get(field) == SHORTS_PRESET.get(field), (
                f"{channel.name}, Zeile {index}: {field} weicht vom Preset ab "
                f"({entry.get(field)!r} statt {SHORTS_PRESET.get(field)!r})"
            )


def test_channel_overrides_replace_the_preset(tmp_path, monkeypatch):
    """Stimme und Schnitt kommen aus der channel.json, nicht aus dem Code.

    Wer sie in news_to_shorts.py aendert, faengt sich beim naechsten Update
    einen Merge-Konflikt ein — deshalb muss der Umweg ueber den Kanal gehen.
    """
    import sys

    sys.path.insert(0, str(ROOT))
    import news_to_shorts as nts

    monkeypatch.setattr(nts, "ROOT", tmp_path)
    channel = tmp_path / "channels" / "meiner"
    channel.mkdir(parents=True)
    (channel / "channel.json").write_text(
        json.dumps(
            {
                "source": "news",
                "topic": "KI",
                "voice_name": "de-DE-ConradNeural-Male",
                "video_transition_mode": None,
                "video_clip_duration": 4,
            }
        ),
        encoding="utf-8",
    )

    preset = nts.preset_for_channel("meiner")
    assert preset["voice_name"] == "de-DE-ConradNeural-Male"
    assert preset["video_transition_mode"] is None
    assert preset["video_clip_duration"] == 4
    # Nicht ueberschriebene Felder bleiben beim eingebauten Kurzformat.
    assert preset["video_aspect"] == nts.SHORTS_PRESET["video_aspect"]
    # Und der Kanal darf keine beliebigen Felder unterschieben.
    assert "topic" not in preset


def test_preset_without_a_channel_is_the_builtin_one():
    import sys

    sys.path.insert(0, str(ROOT))
    import news_to_shorts as nts

    assert nts.preset_for_channel(None) == nts.SHORTS_PRESET


def test_unknown_channel_fails_loudly(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(ROOT))
    import news_to_shorts as nts

    monkeypatch.setattr(nts, "ROOT", tmp_path)
    with pytest.raises(SystemExit):
        nts.preset_for_channel("gibtsnicht")


def test_the_manifest_records_the_channel():
    """Der Kanal muss im fertigen Task stehen, sonst mischt die Oberflaeche
    die Videos aller Kanaele."""
    import news_to_shorts as nts

    videos = [{"video_subject": "Thema", "video_script": "Ein Satz.", "quellen": ["https://example.com"]}]
    manifest, _ = nts.build_manifest(videos, channel="tech")
    assert manifest[0]["channel"] == "tech"
    # Der Eintrag muss weiterhin durch die Pruefung von cli.py kommen.
    assert VideoParams(**manifest[0]).channel == "tech"


def test_without_a_channel_the_manifest_stays_unstamped():
    """Ein Lauf ohne --channel soll kein leeres Feld erfinden."""
    import news_to_shorts as nts

    videos = [{"video_subject": "Thema", "video_script": "Ein Satz."}]
    manifest, _ = nts.build_manifest(videos)
    assert "channel" not in manifest[0]


def test_the_prompt_states_both_bounds_and_the_seconds():
    """Ohne beide Grenzen liefert das Modell zuverlaessig zu kurze Skripte."""
    import news_to_shorts as nts

    # Der Prompt ist umbrochen; gelesen wird er als Fliesstext.
    prompt = " ".join(nts.build_research_prompt(3, 7, "Tech", words=145).split())
    assert "137 bis 153 Woerter" in prompt
    # 145 Woerter sind rund eine Minute — die Sekunden stehen im Prompt, damit
    # das Modell die Groessenordnung kennt und nicht nur eine nackte Zahl.
    assert "57 bis 64 Sekunden" in prompt


def test_a_longer_script_gets_more_beats_and_a_rehook():
    """Ein 60-Sekunden-Skript mit drei Aussagen besteht aus Leerlauf."""
    import news_to_shorts as nts

    kurz = nts.build_research_prompt(1, 7, "Tech", words=60)
    lang = nts.build_research_prompt(1, 7, "Tech", words=145)

    assert "Danach 3 Aussagen" in kurz
    assert "Danach 5 Aussagen" in lang
    # Der Bruch in der Mitte lohnt sich erst, wenn es eine Mitte gibt.
    assert "Haltequote" in lang and "Haelfte" in lang
    assert "Haelfte" not in kurz


def test_script_length_never_falls_below_the_minimum():
    """Die Toleranz darf die Untergrenze nicht unterlaufen."""
    import news_to_shorts as nts

    prompt = nts.build_research_prompt(1, 7, "Tech", words=nts.SCRIPT_WORDS_MIN)
    assert f"{nts.SCRIPT_WORDS_MIN} bis" in prompt


def test_the_channel_sets_the_script_length(tmp_path, monkeypatch):
    import news_to_shorts as nts

    monkeypatch.setattr(nts, "ROOT", tmp_path)
    kanal = tmp_path / "channels" / "tech"
    kanal.mkdir(parents=True)
    (kanal / "channel.json").write_text(
        json.dumps({"script_words": 90}), encoding="utf-8"
    )
    assert nts.words_for_channel("tech") == 90


def test_a_channel_without_the_field_gets_the_default(tmp_path, monkeypatch):
    import news_to_shorts as nts

    monkeypatch.setattr(nts, "ROOT", tmp_path)
    kanal = tmp_path / "channels" / "tech"
    kanal.mkdir(parents=True)
    (kanal / "channel.json").write_text(json.dumps({"topic": "KI"}), encoding="utf-8")
    assert nts.words_for_channel("tech") == nts.SCRIPT_WORDS
    assert nts.words_for_channel(None) == nts.SCRIPT_WORDS


@pytest.mark.parametrize("wert", [10, 500, "viel", None])
def test_an_impossible_length_fails_loudly(tmp_path, monkeypatch, wert):
    """Lieber hier scheitern als ein Skript, das niemand zu Ende sieht."""
    import news_to_shorts as nts

    monkeypatch.setattr(nts, "ROOT", tmp_path)
    kanal = tmp_path / "channels" / "tech"
    kanal.mkdir(parents=True)
    (kanal / "channel.json").write_text(
        json.dumps({"script_words": wert}), encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        nts.words_for_channel("tech")


def test_the_default_length_is_about_a_minute():
    """Die Vorgabe soll das treffen, was als „etwa eine Minute“ gemeint ist."""
    import news_to_shorts as nts

    assert 55 <= nts.script_seconds(nts.SCRIPT_WORDS) <= 65
