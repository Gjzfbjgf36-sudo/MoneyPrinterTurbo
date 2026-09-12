"""Prüft scripts/daily_run.ps1 statisch.

Das Skript läuft nur unter Windows PowerShell 5.1 im Echtbetrieb; die
Testumgebung kann es nicht ausführen. Diese Prüfungen halten deshalb die
Fehler fest, die dort schon aufgetreten sind.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "daily_run.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8", errors="replace")


def test_script_exists():
    assert SCRIPT.exists()


def test_every_external_call_goes_through_the_helper():
    """Ein roher Aufruf bricht den Lauf ab, sobald das Programm nach stderr
    schreibt.

    Mit $ErrorActionPreference = 'Stop' macht Windows PowerShell 5.1 aus
    stderr-Zeilen ErrorRecord-Objekte und wertet sie als Fehler. cli.py und
    news_to_shorts.py loggen ihren normalen Fortschritt dorthin, der Lauf
    starb also an einer harmlosen Statusmeldung.
    """
    lines = source().splitlines()
    offenders = [
        (number, line.strip())
        for number, line in enumerate(lines, start=1)
        # Ein Aufruf von $uv ausserhalb des Helfers und ausserhalb von Kommentaren.
        if re.search(r"(?<!Invoke-Native )&\s*\$uv\b", line)
        and not line.strip().startswith("#")
    ]
    assert not offenders, f"Direkter Aufruf ohne Invoke-Native: {offenders}"


def test_helper_restores_the_error_preference():
    """Sonst gilt 'Continue' für den Rest des Laufs und echte Fehler fallen
    stillschweigend durch."""
    text = source()
    assert "$ErrorActionPreference = 'Continue'" in text
    assert "finally" in text
    assert "$ErrorActionPreference = $previous" in text


def test_success_is_measured_by_the_exit_code():
    text = source()
    assert "$LASTEXITCODE" in text
    assert ".ExitCode -ne 0" in text


def code_without_comments() -> str:
    """Der Quelltext ohne Blockkommentar und ohne Zeilenkommentare.

    Die Kommentare erklären unter anderem, warum --scan vermieden wird; eine
    reine Textsuche würde genau diese Erklärung als Verstoß melden.
    """
    text = re.sub(r"<#.*?#>", "", source(), flags=re.DOTALL)
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


def test_script_never_scans_for_videos():
    """--scan kennt die Kanalzuordnung nicht; der Runner benennt die Dateien.

    Mit zwei Kanälen würde ein Scan die Videos des einen im anderen
    veröffentlichen.
    """
    assert "--scan" not in code_without_comments()
