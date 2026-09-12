"""Tests für die Kanalverwaltung der WebUI (webui/channels.py)."""

import json

import pytest

from webui import channels as ch


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Verlegt Kanal- und Statusverzeichnis in einen leeren Ordner."""
    monkeypatch.setattr(ch, "CHANNELS_DIR", tmp_path / "channels")
    monkeypatch.setattr(ch, "CHANNEL_STORAGE_DIR", tmp_path / "storage" / "channels")
    return tmp_path


QUEUE_ENTRY = {
    "video_subject": "Warum Kaffee müde macht",
    "video_aspect": "9:16",
    "voice_name": "de-DE-KatjaNeural-Female",
    "video_clip_duration": 2,
}


def test_listing_is_empty_without_any_channel(sandbox):
    assert ch.list_channel_names() == []


def test_create_and_load_roundtrip(sandbox):
    created = ch.create_channel("tech", {"source": "news", "topic": "KI"})
    assert created.name == "tech"
    assert created.is_news

    loaded = ch.load_channel("tech")
    assert loaded.config["topic"] == "KI"
    # Fehlende Felder kommen aus den Vorgaben, damit ein von Hand gekürztes
    # channel.json die Oberfläche nicht leer lässt.
    assert loaded.config["topics_per_run"] == ch.DEFAULT_CONFIG["topics_per_run"]
    assert ch.list_channel_names() == ["tech"]


def test_creating_the_same_channel_twice_is_refused(sandbox):
    ch.create_channel("tech", {"source": "queue", "topic": "x"})
    with pytest.raises(ch.ChannelError):
        ch.create_channel("tech", {"source": "queue", "topic": "x"})


@pytest.mark.parametrize(
    "name", ["../evil", "a/b", "", "..", "/absolut", "mit leerzeichen", "-start"]
)
def test_channel_name_cannot_escape_the_directory(sandbox, name):
    """Der Name wird zum Verzeichnisnamen — wie im Uploader abgesichert."""
    with pytest.raises(ch.ChannelError):
        ch.load_channel(name)


def test_validation_collects_every_problem_at_once(sandbox):
    problems = ch.validate_config(
        {
            "source": "unbekannt",
            "topics_per_run": 0,
            "category": "Bildung",
            "publish_at": "25:00",
        }
    )
    assert len(problems) == 4


def test_news_channel_without_topic_is_rejected(sandbox):
    problems = ch.validate_config(
        {**ch.DEFAULT_CONFIG, "source": "news", "topic": "   "}
    )
    assert any("Recherchekanal" in problem for problem in problems)


def test_privacy_only_matters_without_a_schedule(sandbox):
    scheduled = ch.validate_config(
        {**ch.DEFAULT_CONFIG, "topic": "x", "publish_at": "08:00", "privacy": "unsinn"}
    )
    assert scheduled == []

    unscheduled = ch.validate_config(
        {**ch.DEFAULT_CONFIG, "topic": "x", "publish_at": "", "privacy": "unsinn"}
    )
    assert any("privacy" in problem for problem in unscheduled)


def test_saving_an_invalid_config_writes_nothing(sandbox):
    ch.create_channel("tech", {"source": "queue", "topic": "x"})
    with pytest.raises(ch.ChannelError):
        ch.save_channel("tech", {**ch.DEFAULT_CONFIG, "category": "keine Zahl"})
    assert ch.load_channel("tech").config["category"] == ch.DEFAULT_CONFIG["category"]


def test_saved_config_is_valid_json_without_bom(sandbox):
    """Der Tageslauf liest dieselbe Datei mit Python; ein BOM bricht ihn."""
    ch.create_channel("tech", {"source": "news", "topic": "KI"})
    raw = (sandbox / "channels" / "tech" / "channel.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8"))["topic"] == "KI"


def test_queue_roundtrip_keeps_entries_usable(sandbox):
    ch.create_channel("wissen", {"source": "queue", "topic": "Alltag"})
    ch.save_queue("wissen", [QUEUE_ENTRY])
    assert ch.load_queue("wissen") == [QUEUE_ENTRY]


def test_queue_rejects_entries_the_pipeline_would_refuse(sandbox):
    """Besser hier scheitern als nachts im Lauf des Kanals."""
    ch.create_channel("wissen", {"source": "queue", "topic": "Alltag"})
    with pytest.raises(ch.ChannelError):
        ch.save_queue("wissen", [{"video_subject": "x", "video_aspect": "3:4"}])
    with pytest.raises(ch.ChannelError):
        ch.save_queue("wissen", [{"video_aspect": "9:16"}])


def test_editing_subjects_keeps_the_settings_of_existing_topics(sandbox):
    """Wer nur die Themenliste umsortiert, darf Stimme und Schnitt behalten."""
    second = {**QUEUE_ENTRY, "video_subject": "Zweites Thema", "voice_name": "de-DE-ConradNeural-Male"}
    entries = [QUEUE_ENTRY, second]

    result = ch.apply_subjects(entries, ["Zweites Thema", "Warum Kaffee müde macht"])

    assert [entry["video_subject"] for entry in result] == [
        "Zweites Thema",
        "Warum Kaffee müde macht",
    ]
    assert result[0]["voice_name"] == "de-DE-ConradNeural-Male"
    assert result[1]["voice_name"] == "de-DE-KatjaNeural-Female"


def test_a_new_subject_inherits_the_existing_settings(sandbox):
    result = ch.apply_subjects([QUEUE_ENTRY], ["Warum Kaffee müde macht", "Neues Thema"])
    assert result[1]["video_subject"] == "Neues Thema"
    assert result[1]["video_clip_duration"] == 2
    assert result[1]["voice_name"] == "de-DE-KatjaNeural-Female"


def test_blank_lines_do_not_become_topics(sandbox):
    assert ch.apply_subjects([QUEUE_ENTRY], ["  ", ""]) == []


def test_upload_count_reads_the_channel_state(sandbox):
    ch.create_channel("tech", {"source": "news", "topic": "KI"})
    assert ch.count_uploaded("tech") == 0

    state_file = sandbox / "storage" / "channels" / "tech" / "youtube-uploads.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"a.mp4": {}, "b.mp4": {}}), encoding="utf-8")
    assert ch.count_uploaded("tech") == 2


def test_unreadable_upload_state_counts_as_none(sandbox):
    ch.create_channel("tech", {"source": "news", "topic": "KI"})
    state_file = sandbox / "storage" / "channels" / "tech" / "youtube-uploads.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("kaputt", encoding="utf-8")
    assert ch.count_uploaded("tech") == 0


def test_a_broken_channel_does_not_hide_the_others(sandbox):
    ch.create_channel("gut", {"source": "news", "topic": "KI"})
    broken = sandbox / "channels" / "kaputt"
    broken.mkdir(parents=True)
    (broken / "channel.json").write_text("{kein json", encoding="utf-8")

    names = [channel.name for channel in ch.load_channels()]
    assert names == ["gut"]


def test_runner_command_names_the_platform_script(monkeypatch):
    monkeypatch.setattr(ch.platform, "system", lambda: "Windows")
    command = ch.runner_command("tech", dry_run=True)
    assert command[-3:] == ["-Channel", "tech", "-DryRun"]
    assert ch.supports_channel_runner() is True

    monkeypatch.setattr(ch.platform, "system", lambda: "Linux")
    assert ch.runner_command("tech", dry_run=True)[0] == "sh"
    assert ch.supports_channel_runner() is False


def test_every_translation_key_of_the_panel_exists():
    """Ein fehlender Schlüssel zeigt in der Oberfläche den rohen Key an."""
    import re

    panel_source = (ch.ROOT / "webui" / "channels_panel.py").read_text(encoding="utf-8")
    used = set(re.findall(r'tr\(\s*"([^"]+)"\s*\)', panel_source))
    assert used, "keine Übersetzungsaufrufe gefunden — Regex prüfen"

    for locale in ("en", "de"):
        translations = json.loads(
            (ch.ROOT / "webui" / "i18n" / f"{locale}.json").read_text(encoding="utf-8")
        )["Translation"]
        missing = sorted(key for key in used if key not in translations)
        assert not missing, f"{locale}.json fehlen: {missing}"


def test_translation_placeholders_match_between_locales():
    """{count} und {name} müssen in jeder Sprache vorkommen, sonst wirft format()."""
    import re

    locales = {}
    for locale in ("en", "de"):
        locales[locale] = json.loads(
            (ch.ROOT / "webui" / "i18n" / f"{locale}.json").read_text(encoding="utf-8")
        )["Translation"]

    for key, english in locales["en"].items():
        if not key.startswith("Channel"):
            continue
        german = locales["de"].get(key)
        if german is None:
            continue
        assert set(re.findall(r"\{(\w+)\}", english)) == set(
            re.findall(r"\{(\w+)\}", german)
        ), f"Platzhalter weichen ab bei {key!r}"
