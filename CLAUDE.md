# MoneyPrinterTurbo — automatisierte deutsche Shorts

Fork von [harry0703/MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo).
Das Original erzeugt einzelne Videos auf Zuruf. Dieser Fork baut darum herum
eine Automatik: einmal täglich recherchieren, mehrere Shorts rendern und über
den Tag verteilt auf YouTube veröffentlichen — für mehrere Kanäle mit
verschiedenen Themen.

Arbeitsbranch: `claude/zen-einstein-bz1bxx`. Der Nutzer arbeitet auf Windows
(PowerShell 5.1, `C:\dev\MoneyPrinterTurbo`), spricht Deutsch, und hat keine
Grafikkarte.

## Was dieser Fork hinzufügt

| Datei | Rolle |
|---|---|
| `news_to_shorts.py` | Recherche über die Claude-CLI mit Websuche → Batch-Manifest für `cli.py`. Enthält `SHORTS_PRESET` (die Render-Einstellungen) und den Prompt, der die Skripte schreibt. |
| `publish_schedule.py` | Wann welches Video öffentlich wird. Gemeinsam genutzt von Uploader und WebUI — die beiden dürfen nicht auseinanderlaufen. |
| `scripts/daily_run.ps1` | Der Tageslauf auf Windows: recherchieren, rendern, hochladen, je Kanal. |
| `scripts/youtube_upload.py` | Upload über die YouTube Data API v3 mit OAuth, je Kanal ein eigener Token. |
| `webui/channels.py` | Kanalverwaltung, testbar ohne Streamlit. **Jede Regel gehört hierher.** |
| `webui/channels_panel.py` | Streamlit-Schicht darüber. Nur Darstellung und Formularabwicklung. |
| `channels/<name>/` | `channel.json` (Einstellungen) und optional `tasks.jsonl` (Themenliste). |
| `Start-WebUI.bat` | Doppelklick-Starter für die Oberfläche. |

Die Automatik liest **ausschließlich** `channels/<name>/channel.json`. Die
WebUI pflegt diese Dateien, führt die Automatik aber nicht aus.

## Ablauf

```
news_to_shorts.py --channel tech     Recherche → channels/tech/run.json
cli.py --batch-file run.json         Rendern   → storage/tasks/<id>/final-1.mp4
scripts/youtube_upload.py --channel  Upload    → storage/channels/tech/youtube-uploads.json
```

`daily_run.ps1` verkettet die drei Schritte. Die WebUI kann denselben Lauf als
Probelauf anstoßen (rendert, lädt nicht hoch) und zeigt seine Ausgabe live.

## Regeln

**Kommentare erklären das Warum.** Die eigenen Dateien dieses Forks sind auf
Deutsch kommentiert, die Dateien des Originals auf Chinesisch — in einer Datei
die vorhandene Sprache weiterführen. Kommentare, die nur wiederholen was der
Code tut, sind Ballast; erklärt wird, welche Alternative verworfen wurde und
warum.

**Jeder Übersetzungsschlüssel in allen 13 Sprachen.** `webui/i18n/*.json` —
en, de, zh, az, es, fr, id, it, ko, pt, ru, tr, vi. Ein fehlender Schlüssel
zeigt in der Oberfläche den rohen Key an; `test_webui_i18n.py` schlägt fehl.

**Logik in `webui/channels.py`, nicht im Panel.** Das Modul ist ohne laufendes
Streamlit testbar. Was im Panel steht, wird nicht getestet.

**Tests beschreiben den Fehler, den sie verhindern.** Der Docstring nennt den
Schaden, nicht die Mechanik.

```
uv run pytest test/ -q          # ~1330 Tests, ~4 min
uv run ruff check .
```

## Fallstricke, die schon zugeschlagen haben

**UTF-8 an beiden Enden.** Jeder Einstiegspunkt (`cli.py`, `news_to_shorts.py`,
`scripts/youtube_upload.py`) ruft `sys.stdout.reconfigure(encoding="utf-8")`,
und `daily_run.ps1` setzt zusätzlich `PYTHONIOENCODING` **und**
`[Console]::OutputEncoding`. Nur eine Seite umzustellen ist schlechter als
keine: dann wird aus „verschärft" zuverlässig „versch?rft".
Ebenso: jedes `subprocess.run(text=True)` braucht `encoding="utf-8"`.

**Keine BOM in JSON.** PowerShells `Set-Content -Encoding UTF8` schreibt eine
BOM, an der Pythons `json.load` scheitert. Immer
`[System.IO.File]::WriteAllText(..., New-Object System.Text.UTF8Encoding $false)`.

**`st.selectbox(format_func=...)` bricht Streamlits AppTest.** Der Rohwert wird
in der bereits formatierten Optionsliste gesucht. Stattdessen Anzeigetexte als
Optionen übergeben und danach zurück abbilden.

**Warteschlangen-Einträge sind `VideoParams`.** Ein unbekanntes Feld lässt
`cli.py` den nächtlichen Lauf abbrechen. Neue Felder gehören ins Schema.

**Videos brauchen `+faststart`.** Ohne das steht der Index am Dateiende und der
Browser muss die ganze Datei laden, bevor er abspielen kann.

**YouTube-Kontingent:** 10.000 Einheiten pro Tag, ein Upload kostet ~1.600 —
also etwa **6 Uploads täglich**. Geplante Videos müssen bis zum Termin privat
sein, sonst lehnt YouTube den Termin ab.

**Kanaltrennung.** `--scan` kennt die Kanalzuordnung nicht und würde fremde
Videos mitnehmen; deshalb werden Pfade immer einzeln übergeben. Jeder Task
notiert seinen Kanal im Feld `channel`.

## Stand

Läuft: Recherche, Rendern, Upload mit Terminplanung, Kanaltrennung, die
Kanalseite in der WebUI (Schritt 1–4 mit Fortschritt, Vorlagen, Löschen,
Veröffentlichungsplan, Live-Ausgabe).

Offen:
- Der Knopf „Einstellungen von oben übernehmen" kopiert die Vorgaben des
  großen Formulars ungefiltert in den Kanal. Er hat damit schon einen Kanal
  unbrauchbar gemacht (Schrift 30, schwarz, ohne Kontur, österreichische
  Stimme) und 20 Videos gekostet. Eine Plausibilitätsprüfung fehlt.
- Die Windows-Aufgabenplanung für den täglichen Lauf ist noch nicht
  eingerichtet.
- Renderzeit: rund 13 Minuten je 60-Sekunden-Video auf dem Rechner des
  Nutzers. Die Vorlage „sparsam" spart etwa ein Drittel.
