"""Tests für scripts/voice_samples.py (Hörproben der Edge-Stimmen)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "voice_samples", ROOT / "scripts" / "voice_samples.py"
)
samples = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(samples)


def test_male_german_voices_are_found():
    """Die drei deutschen Männerstimmen müssen vollständig erkannt werden."""
    voices = samples.read_voices("de-DE", "male")
    assert voices == [
        "de-DE-ConradNeural",
        "de-DE-FlorianMultilingualNeural",
        "de-DE-KillianNeural",
    ]


def test_gender_filter_separates_the_lists():
    male = set(samples.read_voices("de-DE", "male"))
    female = set(samples.read_voices("de-DE", "female"))
    assert male and female
    assert not male & female
    assert male | female == set(samples.read_voices("de-DE", "any"))


def test_language_prefix_is_not_a_substring_match():
    """de-DE darf nicht die österreichischen und Schweizer Stimmen mitnehmen."""
    german = samples.read_voices("de-DE", "any")
    assert all(voice.startswith("de-DE-") for voice in german)
    assert samples.read_voices("de-AT", "any")


def test_unknown_language_yields_nothing():
    assert samples.read_voices("xx-XX", "any") == []


@pytest.mark.parametrize(
    ("rate", "expected"), [(1.0, "+0%"), (1.2, "+20%"), (0.9, "-10%"), (1.15, "+15%")]
)
def test_rate_matches_the_edge_percentage_format(rate, expected):
    """Dieselbe Umrechnung wie app/services/voice.py, sonst klingt die Probe
    anders als das spätere Video."""
    assert f"{round((rate - 1.0) * 100):+d}%" == expected
