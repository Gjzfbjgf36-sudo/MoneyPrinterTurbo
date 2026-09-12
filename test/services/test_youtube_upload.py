"""Prüft Metadaten, Duplikatschutz und Veröffentlichungstermine des Uploaders.

Der Uploader liegt außerhalb des app-Pakets und wird deshalb über seinen Pfad
geladen. Getestet wird nur, was ohne Google-Zugang entscheidbar ist; der
eigentliche Upload gehört nicht in die Testsuite.
"""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).parent.parent.parent / "scripts" / "youtube_upload.py"
)
_spec = importlib.util.spec_from_file_location("youtube_upload", MODULE_PATH)
uploader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uploader)


def _local(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute).astimezone()


def test_publish_slots_skips_times_that_already_passed_today():
    """Ein nächtlicher Lauf darf keinen Termin in der Vergangenheit setzen."""
    now = _local(2026, 5, 4, 14, 30)
    slots = uploader.publish_slots("08:00,13:00,18:00", 2, now=now)
    assert [slot.strftime("%d.%m %H:%M") for slot in slots] == [
        "04.05 18:00",
        "05.05 08:00",
    ]


def test_publish_slots_spread_across_following_days():
    """Mehr Videos als Uhrzeiten füllen die Folgetage der Reihe nach."""
    now = _local(2026, 5, 4, 6, 0)
    slots = uploader.publish_slots("08:00,18:00", 5, now=now)
    assert [slot.strftime("%d.%m %H:%M") for slot in slots] == [
        "04.05 08:00",
        "04.05 18:00",
        "05.05 08:00",
        "05.05 18:00",
        "06.05 08:00",
    ]


def test_publish_slots_sorts_and_deduplicates_times():
    now = _local(2026, 5, 4, 0, 0)
    slots = uploader.publish_slots("18:00,08:00,08:00", 2, now=now)
    assert [slot.strftime("%H:%M") for slot in slots] == ["08:00", "18:00"]


def test_publish_slots_without_videos_returns_nothing():
    assert uploader.publish_slots("08:00", 0, now=_local(2026, 5, 4, 1)) == []


@pytest.mark.parametrize("invalid", ["", "acht Uhr", "25:00:00", "08.00", ","])
def test_invalid_slot_times_abort_instead_of_guessing(invalid):
    """Eine unverständliche Uhrzeit darf nicht stillschweigend entfallen."""
    with pytest.raises(SystemExit):
        uploader.parse_slot_times(invalid)


def test_youtube_timestamp_is_utc_with_z_suffix():
    moment = datetime(2026, 5, 4, 18, 0, tzinfo=timezone(timedelta(hours=2)))
    assert uploader.to_youtube_timestamp(moment) == "2026-05-04T16:00:00Z"


def test_title_keeps_the_shorts_tag_within_the_youtube_limit():
    metadata = {"params": {"video_subject": "A" * 200}}
    title = uploader.build_title(metadata, fallback="egal")
    assert len(title) <= uploader.TITLE_LIMIT
    assert title.endswith(" #Shorts")


def test_title_falls_back_to_the_task_folder():
    assert uploader.build_title({}, fallback="task-42") == "task-42 #Shorts"


def test_description_carries_script_hashtags_and_the_pexels_credit():
    metadata = {
        "script": "Kurzer Text.",
        "search_terms": ["saving money", "index funds"],
    }
    description = uploader.build_description(metadata)
    assert "Kurzer Text." in description
    assert "#shorts #SavingMoney #IndexFunds" in description
    assert uploader.PEXELS_CREDIT in description


def test_description_appends_the_channel_footer_when_present(tmp_path, monkeypatch):
    """Der Haftungsausschluss eines Kanals muss unter jedem Video stehen."""
    footer = tmp_path / "youtube-footer.txt"
    footer.write_text("Keine Anlageberatung.\n", encoding="utf-8")
    monkeypatch.setattr(uploader, "FOOTER_FILE", footer)
    description = uploader.build_description({"script": "Text."})
    assert description.endswith("Keine Anlageberatung.")


def test_description_without_footer_file_stays_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(uploader, "FOOTER_FILE", tmp_path / "fehlt.txt")
    description = uploader.build_description({"script": "Text."})
    assert description.endswith(uploader.PEXELS_CREDIT)


def test_state_key_is_relative_inside_the_project():
    inside = uploader.ROOT / "storage" / "tasks" / "abc" / "final-1.mp4"
    assert uploader.state_key(inside) == "storage/tasks/abc/final-1.mp4"


def test_state_key_keeps_absolute_paths_from_outside():
    outside = Path("/tmp/woanders/final-1.mp4")
    assert uploader.state_key(outside) == "/tmp/woanders/final-1.mp4"


def test_channel_paths_default_to_the_project_root():
    """Ohne --channel bleiben die alten Pfade, damit ein bestehender
    Einzelkanal nach dem Update nicht neu angemeldet werden muss."""
    paths = uploader.channel_paths(None)
    assert paths["token"] == uploader.ROOT / "storage" / "youtube-token.json"
    assert paths["state"] == uploader.ROOT / "storage" / "youtube-uploads.json"
    assert paths["footer"] == uploader.ROOT / "youtube-footer.txt"


def test_channel_paths_are_separate_per_channel():
    """Zwei Kanäle duerfen sich weder Token noch Upload-Verlauf teilen:
    ein gemeinsamer Token wuerde in den falschen Kanal hochladen."""
    tech = uploader.channel_paths("tech")
    geld = uploader.channel_paths("geld")
    assert tech["token"] != geld["token"]
    assert tech["state"] != geld["state"]
    assert tech["footer"] != geld["footer"]
    assert tech["token"].parent == uploader.CHANNEL_STORAGE_DIR / "tech"


@pytest.mark.parametrize(
    "name",
    ["../evil", "a/b", "..", "", "/absolut", "mit leerzeichen", "-start", "x" * 65],
)
def test_channel_name_cannot_escape_the_project(name):
    """Der Kanalname wird zum Verzeichnisnamen; ein Pfadwechsel darf daraus
    nicht entstehen."""
    with pytest.raises(SystemExit):
        uploader.channel_paths(name)


def test_apply_channel_switches_the_module_paths(monkeypatch):
    monkeypatch.setattr(uploader, "STATE_FILE", Path("unset"))
    monkeypatch.setattr(uploader, "TOKEN_FILE", Path("unset"))
    monkeypatch.setattr(uploader, "FOOTER_FILE", Path("unset"))
    uploader.apply_channel("tech")
    assert uploader.TOKEN_FILE == uploader.CHANNEL_STORAGE_DIR / "tech" / "youtube-token.json"
    assert uploader.FOOTER_FILE == uploader.CHANNELS_DIR / "tech" / "footer.txt"


def test_apply_category_accepts_digits_and_rejects_anything_else(monkeypatch):
    monkeypatch.setattr(uploader, "CATEGORY_ID", "27")
    uploader.apply_category("")
    assert uploader.CATEGORY_ID == "27"
    uploader.apply_category("28")
    assert uploader.CATEGORY_ID == "28"
    with pytest.raises(SystemExit):
        uploader.apply_category("Bildung")


def test_description_carries_the_source_link_from_the_task(tmp_path, monkeypatch):
    """news_to_shorts schreibt die Quelle je Video; sie muss im Upload landen.

    Ohne diesen Weg erreicht der Link nur den Upload-Post-Pfad, nicht aber den
    direkten YouTube-Upload, den der Tageslauf benutzt.
    """
    monkeypatch.setattr(uploader, "FOOTER_FILE", tmp_path / "fehlt.txt")
    metadata = {
        "script": "Text.",
        "params": {"description_suffix": "Quelle: https://example.com/artikel"},
    }
    description = uploader.build_description(metadata)
    assert "Quelle: https://example.com/artikel" in description
    # Die Pexels-Namensnennung bleibt am Ende, sie betrifft die Lizenz.
    assert description.endswith(uploader.PEXELS_CREDIT)


def test_description_without_a_source_link_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(uploader, "FOOTER_FILE", tmp_path / "fehlt.txt")
    description = uploader.build_description({"script": "Text.", "params": {}})
    assert description.endswith(uploader.PEXELS_CREDIT)


def test_publish_slots_keep_the_wall_clock_across_a_dst_change(monkeypatch):
    """Über die Zeitumstellung hinweg muss 08:00 auch am Folgetag 08:00 sein."""
    import os
    import time as time_module

    if not hasattr(time_module, "tzset"):
        pytest.skip("tzset gibt es nur auf POSIX")

    monkeypatch.setitem(os.environ, "TZ", "Europe/Berlin")
    time_module.tzset()
    try:
        # In der Nacht zum 29.03.2026 wird in Europa auf Sommerzeit gestellt.
        now = datetime(2026, 3, 28, 9, 0).astimezone()
        slots = uploader.publish_slots("08:00,18:00", 4, now=now)
        assert [slot.strftime("%d.%m %H:%M") for slot in slots] == [
            "28.03 18:00",
            "29.03 08:00",
            "29.03 18:00",
            "30.03 08:00",
        ]
        # Der Versatz muss sich über die Umstellung tatsächlich ändern.
        assert slots[0].utcoffset() != slots[-1].utcoffset()
    finally:
        os.environ.pop("TZ", None)
        time_module.tzset()
