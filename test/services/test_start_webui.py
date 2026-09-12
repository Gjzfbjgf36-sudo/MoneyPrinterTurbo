"""Prüft die Doppelklick-Startdatei Start-WebUI.bat."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
START = ROOT / "Start-WebUI.bat"


def test_start_file_exists():
    assert START.exists(), "Start-WebUI.bat fehlt"


def test_start_file_changes_into_its_own_directory():
    """Der ganze Zweck der Datei.

    webui.bat verlässt sich auf %CD%. Aus einer Desktop-Verknüpfung oder einem
    geplanten Task ist das oft C:\\Windows\\system32, und die Projektdateien
    werden nicht gefunden. %~dp0 ist immer der Ordner der Datei selbst.
    """
    content = START.read_text(encoding="utf-8", errors="replace")
    assert 'cd /d "%~dp0"' in content
    # Und webui.bat muss über denselben absoluten Pfad aufgerufen werden.
    assert '"%~dp0webui.bat"' in content


def test_start_file_keeps_the_window_open_on_failure():
    """Ohne pause verschwindet das Fenster samt Fehlermeldung sofort."""
    content = START.read_text(encoding="utf-8", errors="replace")
    assert "errorlevel 1" in content
    assert "pause" in content
