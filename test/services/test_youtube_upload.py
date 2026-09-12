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
