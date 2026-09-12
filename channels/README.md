# Kanäle

Ein Verzeichnis je YouTube-Kanal. `scripts/daily_run.ps1` (Windows) arbeitet
alle Kanäle nacheinander ab, `scripts/youtube_upload.py --channel <name>`
lädt in genau einen hoch.

```
channels/<name>/
  channel.json      Einstellungen (siehe unten)
  tasks.jsonl       Themen-Warteschlange, nur bei "source": "queue"
  footer.txt        optionaler Kanaltext unter jeder Beschreibung
  tasks-done.jsonl  abgearbeitete Themen, wird selbst geschrieben
  run.json          Manifest des letzten Laufs, wird selbst geschrieben

storage/channels/<name>/
  youtube-token.json    OAuth-Token dieses Kanals
  youtube-uploads.json  Upload-Verlauf dieses Kanals
```

`client_secret.json` bleibt gemeinsam im Projektstamm: Der OAuth-Client gehört
zum Google-Cloud-Projekt, nicht zum YouTube-Konto. Beim ersten Upload je Kanal
öffnet sich der Browser, und dort wählst du den jeweiligen Kanal aus.

## channel.json

| Feld | Bedeutung |
|---|---|
| `source` | `news` recherchiert aktuelle Meldungen, `queue` nimmt Themen aus `tasks.jsonl` |
| `topic` | Themenbereich, bei `news` die Suchvorgabe |
| `topics_per_run` | Videos pro Lauf |
| `category` | YouTube-Kategorie: 27 Bildung, 28 Wissenschaft und Technik, 24 Unterhaltung |
| `publish_at` | Uhrzeiten für die geplante Veröffentlichung, etwa `08:00,13:00,18:00` |
| `privacy` | nur ohne `publish_at`: `private`, `unlisted` oder `public` |
| `research_model` | nur bei `news`: Modell für die Recherche |

Ist `publish_at` gesetzt, lädt das Skript die Videos privat hoch und YouTube
schaltet sie selbst zum Termin frei. Der Rechner muss danach nicht laufen.
