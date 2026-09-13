"""Kanalverwaltung für die WebUI.

Ein Kanal ist ein Verzeichnis unter ``channels/`` mit einer ``channel.json``
und, bei Warteschlangenkanälen, einer ``tasks.jsonl``. ``scripts/daily_run.ps1``
und ``scripts/youtube_upload.py --channel`` arbeiten mit denselben Dateien.

Die Logik liegt bewusst hier statt in ``webui/Main.py``: das Modul ist damit
ohne laufendes Streamlit testbar, und Main.py wächst nicht weiter.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app.models.schema import VideoParams

ROOT = Path(__file__).resolve().parent.parent
CHANNELS_DIR = ROOT / "channels"
CHANNEL_STORAGE_DIR = ROOT / "storage" / "channels"

# Muss mit scripts/youtube_upload.py übereinstimmen: der Name wird dort zu
# einem Verzeichnisnamen, ein Pfadwechsel darf daraus nicht entstehen.
CHANNEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

SOURCES = ("news", "queue")
PRIVACY_LEVELS = ("private", "unlisted", "public")
# Stimme und Schnitt sind Geschmack, kein Programmablauf. Sie stehen deshalb
# in der channel.json und nicht im Code: wer sie in news_to_shorts.py aendert,
# faengt sich beim naechsten Update einen Merge-Konflikt ein.
GERMAN_VOICES = (
    "de-DE-FlorianMultilingualNeural-Male",
    "de-DE-ConradNeural-Male",
    "de-DE-KillianNeural-Male",
    "de-DE-SeraphinaMultilingualNeural-Female",
    "de-DE-KatjaNeural-Female",
    "de-DE-AmalaNeural-Female",
)
TRANSITIONS = (None, "ZoomIn", "ZoomOut", "FadeIn", "FadeOut", "Shuffle")

# Fertige Kombinationen aus Untertitel, Schnitt und Tempo. Einzeln sind die
# Werte schwer einzuschätzen — erst zusammen ergeben sie einen Look. Die
# Schlüssel sind genau die Felder aus CHANNEL_OVERRIDES in news_to_shorts.py,
# ein Stil schreibt also nichts, was der Tageslauf nicht ohnehin liest.
STYLES: dict[str, dict] = {
    "karaoke": {
        # Wort für Wort mit Sprung-Animation, groß und mittig: der Look, den
        # die meisten erfolgreichen Shorts benutzen.
        "subtitle_display_mode": "word_by_word",
        "subtitle_animation": "pop_spring",
        "subtitle_position": "two_thirds_bottom",
        "font_name": "BeVietnamPro-Bold.ttf",
        "font_size": 84,
        "stroke_width": 3.0,
        "text_fore_color": "#FFFFFF",
        "text_background_color": False,
        "video_clip_duration": 2,
        "video_clip_speed": 1.08,
        "video_transition_mode": "ZoomIn",
        "voice_rate": 1.2,
        "bgm_volume": 0.12,
    },
    "signal": {
        # Gelb auf schwarzem Rand liest sich auf jedem Untergrund, auch auf
        # hellem Stockmaterial, wo Weiß verschwindet.
        "subtitle_display_mode": "word_by_word",
        "subtitle_animation": "pop_spring",
        "subtitle_position": "center",
        "font_name": "BeVietnamPro-Bold.ttf",
        "font_size": 96,
        "stroke_width": 4.0,
        "text_fore_color": "#FFE000",
        "text_background_color": False,
        "video_clip_duration": 2,
        "video_clip_speed": 1.1,
        "video_transition_mode": "ZoomIn",
        "voice_rate": 1.25,
        "bgm_volume": 0.1,
    },
    "ruhig": {
        # Ganze Sätze, keine Animation, kleinere Schrift: für Themen, bei denen
        # Hektik dem Inhalt widerspricht.
        "subtitle_display_mode": "sentence",
        "subtitle_animation": "none",
        "subtitle_position": "bottom",
        "font_name": "BeVietnamPro-Medium.ttf",
        "font_size": 64,
        "stroke_width": 2.0,
        "text_fore_color": "#FFFFFF",
        "text_background_color": False,
        "video_clip_duration": 4,
        "video_clip_speed": 1.0,
        "video_transition_mode": "FadeIn",
        "voice_rate": 1.05,
        "bgm_volume": 0.18,
    },
    "kontrast": {
        # Balken hinter der Schrift statt Kontur. Auf unruhigem Material die
        # einzige Variante, die durchgehend lesbar bleibt.
        "subtitle_display_mode": "word_by_word",
        "subtitle_animation": "pop_spring",
        "subtitle_position": "two_thirds_bottom",
        "font_name": "BeVietnamPro-Bold.ttf",
        "font_size": 78,
        "stroke_width": 1.0,
        "text_fore_color": "#FFFFFF",
        "text_background_color": "#000000",
        "video_clip_duration": 2,
        "video_clip_speed": 1.08,
        "video_transition_mode": "ZoomIn",
        "voice_rate": 1.2,
        "bgm_volume": 0.12,
    },
    "sparsam": {
        # Ohne Zoom und mit längeren Clips: rund ein Drittel weniger
        # Renderzeit, spürbar auf Rechnern ohne Grafikkarte.
        "subtitle_display_mode": "word_by_word",
        "subtitle_animation": "pop_spring",
        "subtitle_position": "two_thirds_bottom",
        "font_name": "BeVietnamPro-Bold.ttf",
        "font_size": 84,
        "stroke_width": 3.0,
        "text_fore_color": "#FFFFFF",
        "text_background_color": False,
        "video_clip_duration": 3,
        "video_clip_speed": 1.0,
        "video_transition_mode": None,
        "voice_rate": 1.2,
        "bgm_volume": 0.12,
    },
}


def apply_style(config: dict, style: str) -> dict:
    """Legt einen Stil über eine Kanalkonfiguration.

    Die Stimme bleibt unangetastet: sie gehört zur Kanalidentität, nicht zum
    Look, und wer den Stil wechselt will nicht plötzlich anders klingen.
    """
    if style not in STYLES:
        raise ChannelError(f"Unbekannter Stil {style!r}")
    updated = dict(config)
    updated.update(STYLES[style])
    updated["style"] = style
    return updated


def detect_style(config: dict) -> str | None:
    """Der Stil, dessen Werte alle in der Konfiguration stehen.

    Der gespeicherte Name allein würde lügen, sobald jemand danach einen
    einzelnen Regler verstellt — deshalb wird verglichen statt geglaubt.
    """
    for name, style in STYLES.items():
        if all(config.get(key) == value for key, value in style.items()):
            return name
    return None
# Die gängigen YouTube-Kategorien für diese Art Kanal. Andere IDs bleiben
# erlaubt, die Liste ist nur die Auswahlhilfe in der Oberfläche.
CATEGORIES = {
    "27": "Bildung",
    "28": "Wissenschaft und Technik",
    "24": "Unterhaltung",
    "22": "Menschen und Blogs",
    "25": "Nachrichten und Politik",
}

DEFAULT_CONFIG: dict = {
    "source": "queue",
    "topic": "",
    "topics_per_run": 3,
    "category": "27",
    "publish_at": "08:00,13:00,18:00",
    "privacy": "private",
    "research_model": "claude-sonnet-5",
    # Diese vier überschreiben das Kurzformat aus news_to_shorts.py.
    "voice_name": "de-DE-FlorianMultilingualNeural-Male",
    "voice_rate": 1.2,
    "video_clip_duration": 2,
    "video_transition_mode": "ZoomIn",
}


class ChannelError(ValueError):
    """Eingabefehler, der dem Nutzer angezeigt werden soll."""


@dataclass
class Channel:
    name: str
    config: dict
    queue: list[dict] = field(default_factory=list)
    uploaded: int = 0

    @property
    def is_news(self) -> bool:
        return self.config.get("source") == "news"


def _channel_dir(name: str) -> Path:
    if not CHANNEL_NAME_PATTERN.match(name or ""):
        raise ChannelError(
            f"Ungültiger Kanalname {name!r}. Erlaubt sind Buchstaben, Ziffern, "
            "Bindestrich und Unterstrich, beginnend mit Buchstabe oder Ziffer."
        )
    return CHANNELS_DIR / name


def list_channel_names() -> list[str]:
    """Alle Kanäle mit einer channel.json, alphabetisch."""
    if not CHANNELS_DIR.exists():
        return []
    return sorted(
        path.name
        for path in CHANNELS_DIR.iterdir()
        if path.is_dir() and (path / "channel.json").exists()
    )


def validate_config(config: dict) -> list[str]:
    """Sammelt alle Probleme auf einmal, statt beim ersten abzubrechen.

    Die Oberfläche zeigt sie zusammen an; ein Formular, das jeden Fehler
    einzeln meldet, kostet den Nutzer unnötige Durchläufe.
    """
    problems: list[str] = []

    if config.get("source") not in SOURCES:
        problems.append(f"source muss {' oder '.join(SOURCES)} sein")

    if config.get("source") == "news" and not str(config.get("topic", "")).strip():
        problems.append("Ein Recherchekanal braucht ein Thema als Suchvorgabe")

    try:
        count = int(config.get("topics_per_run", 0))
        if count < 1:
            problems.append("topics_per_run muss mindestens 1 sein")
    except (TypeError, ValueError):
        problems.append("topics_per_run muss eine Zahl sein")

    category = str(config.get("category", "")).strip()
    if not category.isdigit():
        problems.append("category muss eine Zahl sein, etwa 27 für Bildung")

    publish_at = str(config.get("publish_at", "")).strip()
    if publish_at:
        for slot in publish_at.split(","):
            slot = slot.strip()
            if not slot:
                continue
            try:
                hour, minute = (int(value) for value in slot.split(":", 1))
            except ValueError:
                problems.append(f"Ungültige Uhrzeit {slot!r}, erwartet wird HH:MM")
                continue
            if not (0 <= hour < 24 and 0 <= minute < 60):
                problems.append(f"Uhrzeit {slot!r} liegt außerhalb von 00:00–23:59")
    elif config.get("privacy") not in PRIVACY_LEVELS:
        # Ohne Termin entscheidet privacy über die Sichtbarkeit; mit Termin
        # lädt der Uploader immer privat hoch und YouTube schaltet selbst frei.
        problems.append(f"privacy muss {', '.join(PRIVACY_LEVELS)} sein")

    return problems


def load_queue(name: str) -> list[dict]:
    """Themen aus tasks.jsonl; unlesbare Zeilen werden übersprungen."""
    queue_file = _channel_dir(name) / "tasks.jsonl"
    if not queue_file.exists():
        return []
    entries: list[dict] = []
    for line in queue_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def count_uploaded(name: str) -> int:
    """Anzahl der laut Verlauf bereits veröffentlichten Videos."""
    state_file = CHANNEL_STORAGE_DIR / name / "youtube-uploads.json"
    if not state_file.exists():
        return 0
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return len(state) if isinstance(state, dict) else 0


def load_channel(name: str) -> Channel:
    config_file = _channel_dir(name) / "channel.json"
    if not config_file.exists():
        raise ChannelError(f"Kanal {name!r} hat keine channel.json")
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ChannelError(f"channel.json von {name!r} ist kein gültiges JSON: {exc}")

    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    return Channel(
        name=name,
        config=merged,
        queue=load_queue(name),
        uploaded=count_uploaded(name),
    )


def load_channels() -> list[Channel]:
    channels = []
    for name in list_channel_names():
        try:
            channels.append(load_channel(name))
        except ChannelError:
            # Ein kaputter Kanal darf die Liste der anderen nicht verhindern.
            continue
    return channels


def _write_json(path: Path, payload) -> None:
    """Immer UTF-8 ohne BOM: dieselben Dateien liest Python im Tageslauf."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def save_channel(name: str, config: dict) -> None:
    problems = validate_config(config)
    if problems:
        raise ChannelError("; ".join(problems))
    stored = dict(config)
    stored["topics_per_run"] = int(stored["topics_per_run"])
    stored["category"] = str(stored["category"]).strip()
    _write_json(_channel_dir(name) / "channel.json", stored)


def create_channel(name: str, config: dict | None = None) -> Channel:
    directory = _channel_dir(name)
    if (directory / "channel.json").exists():
        raise ChannelError(f"Kanal {name!r} gibt es schon")
    merged = dict(DEFAULT_CONFIG)
    merged.update(config or {})
    save_channel(name, merged)
    return load_channel(name)


def save_queue(name: str, entries: list[dict]) -> None:
    """Schreibt die Warteschlange und prüft jeden Eintrag vorher.

    Ein Eintrag, den cli.py später ablehnt, würde den nächtlichen Lauf des
    Kanals scheitern lassen — also hier abfangen, wo jemand zusieht.
    """
    for index, entry in enumerate(entries, start=1):
        try:
            params = VideoParams(**entry)
        except Exception as exc:
            raise ChannelError(f"Thema {index} ist unbrauchbar: {exc}")
        if not (params.video_subject or params.video_script):
            raise ChannelError(f"Thema {index} braucht ein Thema oder ein Skript")

    queue_file = _channel_dir(name) / "tasks.jsonl"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(entry, ensure_ascii=False) for entry in entries]
    queue_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def queue_subjects(entries: list[dict]) -> list[str]:
    """Nur die Themen, für die Textfläche in der Oberfläche."""
    return [str(entry.get("video_subject", "")).strip() for entry in entries]


def apply_subjects(entries: list[dict], subjects: list[str]) -> list[dict]:
    """Setzt eine bearbeitete Themenliste um und behält bestehende Einstellungen.

    Wer in der Oberfläche nur Zeilen umsortiert oder ergänzt, soll nicht die
    Stimme und den Schnitt der übrigen Themen verlieren. Ein neues Thema erbt
    deshalb die Einstellungen des ersten vorhandenen Eintrags.

    Jeder vorhandene Eintrag wird höchstens einmal wiederverwendet. Nach dem
    Thema zu gruppieren wäre verlockend, würde aber bei zwei gleich benannten
    Zeilen beide auf denselben Eintrag abbilden und den anderen samt seinem
    fertigen Skript verwerfen.
    """
    template = dict(entries[0]) if entries else {}
    template.pop("video_subject", None)
    template.pop("video_script", None)

    unused = list(entries)
    result = []
    for subject in subjects:
        subject = subject.strip()
        if not subject:
            continue
        match = next(
            (
                entry
                for entry in unused
                if str(entry.get("video_subject", "")).strip() == subject
            ),
            None,
        )
        if match is not None:
            unused.remove(match)
            result.append(dict(match))
        else:
            result.append({**template, "video_subject": subject})

    # Einträge ohne Thema lassen sich über die Themenliste nicht darstellen.
    # Wer ein fertiges Skript mitgebracht hat, darf es aber nicht dadurch
    # verlieren, dass jemand die Liste bearbeitet — sie bleiben erhalten.
    result.extend(
        dict(entry)
        for entry in unused
        if not str(entry.get("video_subject", "")).strip()
        and str(entry.get("video_script", "")).strip()
    )
    return result


RUN_LOG = ROOT / "storage" / "logs" / "daily-run.jsonl"
# Die Schritte des Tageslaufs in ihrer Reihenfolge, fuer die Anzeige.
RUN_STEPS = ("research", "render", "upload", "done", "error")


@dataclass
class RunEvent:
    """Ein Schritt des Tageslaufs, so wie ihn daily_run.ps1 protokolliert."""

    time: str
    channel: str
    step: str
    message: str
    ok: bool

    @property
    def is_error(self) -> bool:
        return not self.ok or self.step == "error"


def read_run_log(limit: int = 60, channel: str | None = None) -> list[RunEvent]:
    """Die letzten Ereignisse des Tageslaufs, neueste zuletzt.

    Der geplante Lauf laeuft in einem eigenen Prozess; die Aufgabenliste der
    WebUI sieht ihn nicht. Das Protokoll ist deshalb die einzige Stelle, an
    der sich nachvollziehen laesst, wo die Erzeugung gerade steht.
    """
    if not RUN_LOG.exists():
        return []

    events: list[RunEvent] = []
    try:
        lines = RUN_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            # Eine abgeschnittene Zeile entsteht, wenn der Lauf mitten im
            # Schreiben abgebrochen wird. Sie darf den Rest nicht verdecken.
            continue
        if channel and entry.get("channel") != channel:
            continue
        events.append(
            RunEvent(
                time=str(entry.get("time", "")),
                channel=str(entry.get("channel", "")),
                step=str(entry.get("step", "")),
                message=str(entry.get("message", "")),
                ok=bool(entry.get("ok", True)),
            )
        )
    return events[-limit:]


def last_run_summary(channel: str) -> dict:
    """Stand des letzten Laufs dieses Kanals fuer die Kennzahlen-Zeile."""
    events = read_run_log(limit=10_000, channel=channel)
    if not events:
        return {"time": "", "step": "", "ok": True, "message": ""}
    last = events[-1]
    return {
        "time": last.time,
        "step": last.step,
        "ok": not any(event.is_error for event in events if event.time == last.time),
        "message": last.message,
    }


@dataclass
class PendingVideo:
    """Ein fertiges Video, das in diesem Kanal noch nicht veröffentlicht ist."""

    path: Path
    task_id: str
    subject: str
    script: str
    source: str
    size_mb: float

    @property
    def words(self) -> int:
        return len(self.script.split())


def _read_task_metadata(task_dir: Path) -> dict:
    script_file = task_dir / "script.json"
    if not script_file.exists():
        return {}
    try:
        return json.loads(script_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _uploaded_keys(name: str) -> set[str]:
    state_file = CHANNEL_STORAGE_DIR / name / "youtube-uploads.json"
    if not state_file.exists():
        return set()
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return set(state) if isinstance(state, dict) else set()


def pending_videos(name: str) -> list[PendingVideo]:
    """Fertige Videos, die dieser Kanal noch nicht veröffentlicht hat.

    Bewusst alle Videos unter ``storage/tasks``, nicht nur die dieses Kanals:
    welcher Kanal ein Video gerendert hat, steht nirgends. Statt zu raten
    zeigt die Oberfläche alles an und lässt den Nutzer auswählen — damit kann
    kein Video versehentlich im falschen Kanal landen.
    """
    tasks_dir = ROOT / "storage" / "tasks"
    if not tasks_dir.exists():
        return []

    uploaded = _uploaded_keys(name)
    videos: list[PendingVideo] = []
    for video in sorted(
        tasks_dir.glob("*/final-*.mp4"), key=lambda path: path.stat().st_mtime
    ):
        try:
            key = str(video.relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            key = str(video)
        if key in uploaded or str(video.relative_to(ROOT)) in uploaded:
            continue

        metadata = _read_task_metadata(video.parent)
        params = metadata.get("params") or {}
        videos.append(
            PendingVideo(
                path=video,
                task_id=video.parent.name,
                subject=str(params.get("video_subject") or video.parent.name),
                script=str(metadata.get("script") or ""),
                source=str(params.get("description_suffix") or "").strip(),
                size_mb=round(video.stat().st_size / 1_048_576, 1),
            )
        )
    return videos


def delete_video(path: Path) -> str:
    """Löscht den Task-Ordner eines Videos und meldet, was entfernt wurde.

    Es wird immer der ganze Ordner gelöscht, nicht nur die MP4: daneben liegen
    Skript, Untertitel und Tonspur, die ohne das Video nichts mehr nützen.

    Der Pfad wird gegen ``storage/tasks`` geprüft, bevor irgendetwas passiert.
    Ein Pfad aus einer Oberfläche darf nie ungeprüft in ein rekursives Löschen
    laufen — hier hinge ein Tippfehler oder ein manipulierter Zustand direkt an
    ``rmtree``.
    """
    tasks_dir = (ROOT / "storage" / "tasks").resolve()
    target = Path(path).resolve()

    try:
        relative = target.relative_to(tasks_dir)
    except ValueError:
        raise ChannelError(
            f"{target} liegt nicht unter storage/tasks und wird nicht gelöscht."
        )
    if not relative.parts:
        raise ChannelError("Es wird nur ein einzelner Task gelöscht, nicht alles.")

    task_dir = tasks_dir / relative.parts[0]
    if not task_dir.is_dir():
        raise ChannelError(f"{task_dir.name} gibt es nicht mehr.")

    shutil.rmtree(task_dir)
    return task_dir.name


def upload_command(
    name: str, videos: list[Path], publish_at: str = "", privacy: str = "private"
) -> list[str]:
    """Lädt genau die genannten Videos in diesen Kanal.

    Ohne ``--scan``: der Scan kennt die Kanalzuordnung nicht und würde die
    Videos der anderen Kanäle mitnehmen.
    """
    command = [
        "uv",
        "run",
        "python",
        str(ROOT / "scripts" / "youtube_upload.py"),
        *[str(video) for video in videos],
        "--channel",
        name,
    ]
    if publish_at.strip():
        command += ["--publish-at", publish_at.strip()]
    else:
        command += ["--privacy", privacy]
    return command


def login_command(name: str) -> list[str]:
    """Einmalige Anmeldung eines Kanals; öffnet den Browser, lädt nichts hoch."""
    return [
        "uv",
        "run",
        "python",
        str(ROOT / "scripts" / "youtube_upload.py"),
        "--channel",
        name,
        "--login",
    ]


def is_logged_in(name: str) -> bool:
    return (CHANNEL_STORAGE_DIR / name / "youtube-token.json").exists()


@dataclass
class NextStep:
    """Was dieser Kanal als Naechstes braucht.

    Die Oberflaeche zeigt sonst alles gleichzeitig und ueberlaesst es dem
    Nutzer, die Reihenfolge zu erraten. Der Zustand steht in den Dateien —
    also kann er auch ausgerechnet werden.
    """

    key: str
    done: int
    total: int

    @property
    def progress(self) -> float:
        return self.done / self.total if self.total else 0.0

    @property
    def number(self) -> int:
        """Die Nummer, unter der dieser Schritt in der Oberflaeche steht.

        ``done`` zaehlt die erledigten Schritte und ist beim ersten noch 0 —
        als Anzeige waere das eine „0 von 4“ ueber einem Abschnitt, der
        „Schritt 1“ heisst. Gezaehlt wird deshalb der laufende Schritt.
        """
        return min(self.done + 1, self.total) if self.total else 0


# Die Schritte in der Reihenfolge, in der sie erledigt werden muessen. Der
# erste unerfuellte ist der naechste.
SETUP_STEPS = ("login", "style", "render", "upload", "ready")


def next_step(channel: Channel) -> NextStep:
    """Der erste Schritt, der bei diesem Kanal noch offen ist."""
    total = len(SETUP_STEPS) - 1

    if not is_logged_in(channel.name):
        return NextStep("login", 0, total)
    if detect_style(channel.config) is None:
        # Kein Fehler, nur ungewiss: eine Vorlage nimmt dem Nutzer die
        # Entscheidung ueber zehn Einzelwerte ab.
        return NextStep("style", 1, total)
    if not pending_videos(channel.name) and channel.uploaded == 0:
        return NextStep("render", 2, total)
    if pending_videos(channel.name):
        return NextStep("upload", 3, total)
    return NextStep("ready", total, total)


def runner_command(channel: str | None = None, dry_run: bool = False) -> list[str]:
    """Der Befehl für den Tageslauf auf diesem Betriebssystem.

    Nur ``daily_run.ps1`` kennt einzelne Kanäle und einen Probelauf. Auf
    anderen Systemen wird für einen angefragten Probelauf deshalb ``cli.py``
    direkt aufgerufen: ``daily_run.sh`` würde rendern **und** über ``--scan``
    aus der gemeinsamen Warteschlange hochladen — als „Probelauf“ angeboten
    wäre das genau die kanalübergreifende Veröffentlichung, die diese
    Kanaltrennung verhindern soll.
    """
    if platform.system() == "Windows":
        command = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "daily_run.ps1"),
        ]
        if channel:
            command += ["-Channel", channel]
        if dry_run:
            command.append("-DryRun")
        return command

    if dry_run:
        manifest = CHANNELS_DIR / (channel or "") / "tasks.jsonl"
        return [
            "uv",
            "run",
            "python",
            str(ROOT / "cli.py"),
            "--batch-file",
            str(manifest),
            "--stop-at",
            "script",
        ]

    return ["sh", str(ROOT / "scripts" / "daily_run.sh")]


def supports_channel_runner() -> bool:
    """Nur der PowerShell-Runner kennt einzelne Kanäle und den Probelauf."""
    return platform.system() == "Windows"
