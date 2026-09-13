"""Tests für die Kanalverwaltung der WebUI (webui/channels.py)."""

from pathlib import Path
import json

import pytest

from app.models.schema import VideoParams
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
    # Beim Speichern kommt der Kanalname dazu; sonst bleibt der Eintrag gleich.
    assert ch.load_queue("wissen") == [{**QUEUE_ENTRY, "channel": "wissen"}]


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
    # Ohne Probelauf bleibt es das Tagesskript; der Probelauf selbst geht
    # einen anderen Weg, siehe test_dry_run_on_other_systems_never_uploads.
    assert ch.runner_command(None, dry_run=False)[0] == "sh"
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


def test_duplicate_subjects_keep_their_own_entries(sandbox):
    """Zwei gleich benannte Zeilen duerfen nicht auf denselben Eintrag fallen.

    Nach dem Thema zu gruppieren haette den einen samt fertigem Skript
    verworfen und beide auf den letzten Eintrag abgebildet.
    """
    erste = {**QUEUE_ENTRY, "video_script": "Erstes Skript."}
    zweite = {**QUEUE_ENTRY, "video_script": "Zweites Skript."}

    result = ch.apply_subjects([erste, zweite], [QUEUE_ENTRY["video_subject"]] * 2)

    assert len(result) == 2
    assert [entry["video_script"] for entry in result] == [
        "Erstes Skript.",
        "Zweites Skript.",
    ]


def test_an_entry_without_a_subject_is_not_lost(sandbox):
    """Ein mitgebrachtes Skript ohne Thema laesst sich in der Liste nicht
    darstellen, darf aber beim Bearbeiten nicht verschwinden."""
    nur_skript = {"video_script": "Fertiger Text.", "video_aspect": "9:16"}

    result = ch.apply_subjects([QUEUE_ENTRY, nur_skript], [QUEUE_ENTRY["video_subject"]])

    assert len(result) == 2
    assert result[1]["video_script"] == "Fertiger Text."


def test_dry_run_on_other_systems_never_uploads(monkeypatch):
    """Der Probelauf darf auf keinem System einen Upload ausloesen.

    daily_run.sh rendert und laedt per --scan aus der gemeinsamen
    Warteschlange hoch — als Probelauf angeboten waere das genau die
    kanaluebergreifende Veroeffentlichung, die die Kanaltrennung verhindert.
    """
    monkeypatch.setattr(ch.platform, "system", lambda: "Linux")
    command = ch.runner_command("tech", dry_run=True)
    assert "daily_run.sh" not in " ".join(command)
    assert "--stop-at" in command and "script" in command


def test_pending_videos_exclude_what_this_channel_uploaded(sandbox, monkeypatch):
    """Ein bereits veroeffentlichtes Video darf nicht erneut angeboten werden."""
    monkeypatch.setattr(ch, "ROOT", sandbox)
    task = sandbox / "storage" / "tasks" / "abc"
    task.mkdir(parents=True)
    video = task / "final-1.mp4"
    video.write_bytes(b"x" * 2048)
    (task / "script.json").write_text(
        json.dumps(
            {
                "script": "Ein kurzer Text.",
                "params": {
                    "video_subject": "Testthema",
                    "description_suffix": "Quelle: https://example.com",
                },
            }
        ),
        encoding="utf-8",
    )
    ch.create_channel("tech", {"source": "news", "topic": "KI"})

    offen = ch.pending_videos("tech")
    assert len(offen) == 1
    assert offen[0].subject == "Testthema"
    assert offen[0].source == "Quelle: https://example.com"
    assert offen[0].words == 3

    state = sandbox / "storage" / "channels" / "tech" / "youtube-uploads.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"storage/tasks/abc/final-1.mp4": {}}), encoding="utf-8")
    assert ch.pending_videos("tech") == []


def test_upload_command_names_the_files_and_never_scans(sandbox):
    """--scan kennt die Kanalzuordnung nicht und wuerde fremde Videos mitnehmen."""
    command = ch.upload_command("tech", [Path("a.mp4"), Path("b.mp4")], publish_at="08:00")
    assert "--scan" not in command
    assert "a.mp4" in command and "b.mp4" in command
    assert command[command.index("--channel") + 1] == "tech"
    assert "--publish-at" in command

    ohne_termin = ch.upload_command("tech", [Path("a.mp4")], privacy="unlisted")
    assert "--publish-at" not in ohne_termin
    assert ohne_termin[ohne_termin.index("--privacy") + 1] == "unlisted"


def test_login_command_only_signs_in(sandbox):
    command = ch.login_command("tech")
    assert "--login" in command
    assert "--scan" not in command


def test_is_logged_in_follows_the_channel_token(sandbox):
    ch.create_channel("tech", {"source": "news", "topic": "KI"})
    assert ch.is_logged_in("tech") is False
    token = sandbox / "storage" / "channels" / "tech" / "youtube-token.json"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("{}", encoding="utf-8")
    assert ch.is_logged_in("tech") is True


def test_every_style_only_sets_fields_the_daily_run_reads(sandbox):
    """Ein Stil, der Felder setzt, die niemand liest, waere wirkungslos."""
    import sys

    sys.path.insert(0, str(ch.ROOT))
    from news_to_shorts import CHANNEL_OVERRIDES

    for name, style in ch.STYLES.items():
        unbekannt = sorted(set(style) - set(CHANNEL_OVERRIDES))
        assert not unbekannt, f"Stil {name!r} setzt ungelesene Felder: {unbekannt}"


def test_every_style_produces_valid_video_params(sandbox):
    """Ein Stil muss die Pipeline auch tatsaechlich durchlaufen koennen."""
    from app.models.schema import VideoParams

    for name, style in ch.STYLES.items():
        params = VideoParams(video_subject="Test", **style)
        assert params.video_subject == "Test", name


def test_applying_a_style_keeps_the_channel_identity(sandbox):
    """Stimme und Thema gehoeren zum Kanal, nicht zum Look."""
    config = {
        **ch.DEFAULT_CONFIG,
        "topic": "KI",
        "voice_name": "de-DE-ConradNeural-Male",
    }
    updated = ch.apply_style(config, "signal")

    assert updated["voice_name"] == "de-DE-ConradNeural-Male"
    assert updated["topic"] == "KI"
    assert updated["text_fore_color"] == "#FFE000"
    assert updated["style"] == "signal"


def test_unknown_style_is_refused(sandbox):
    with pytest.raises(ch.ChannelError):
        ch.apply_style(dict(ch.DEFAULT_CONFIG), "gibtsnicht")


def test_style_detection_compares_instead_of_trusting_the_name(sandbox):
    """Der gespeicherte Name luegt, sobald jemand einen Regler verstellt."""
    config = ch.apply_style(dict(ch.DEFAULT_CONFIG), "karaoke")
    assert ch.detect_style(config) == "karaoke"

    config["font_size"] = 40
    assert ch.detect_style(config) is None
    # Der Name steht noch drin, die Erkennung faellt trotzdem nicht darauf herein.
    assert config["style"] == "karaoke"


def test_run_log_is_empty_without_a_run(sandbox, monkeypatch):
    monkeypatch.setattr(ch, "RUN_LOG", sandbox / "storage" / "logs" / "daily-run.jsonl")
    assert ch.read_run_log() == []


def test_run_log_reads_events_and_filters_by_channel(sandbox, monkeypatch):
    log = sandbox / "storage" / "logs" / "daily-run.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ch, "RUN_LOG", log)

    log.write_text(
        "\n".join(
            json.dumps(entry, ensure_ascii=False)
            for entry in [
                {"time": "2026-09-12 06:00:00", "channel": "tech", "step": "research",
                 "message": "3 Meldungen", "ok": True},
                {"time": "2026-09-12 06:01:00", "channel": "geld", "step": "render",
                 "message": "1 Video", "ok": True},
                {"time": "2026-09-12 06:20:00", "channel": "tech", "step": "upload",
                 "message": "fehlgeschlagen", "ok": False},
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    alle = ch.read_run_log()
    assert len(alle) == 3

    nur_tech = ch.read_run_log(channel="tech")
    assert [event.step for event in nur_tech] == ["research", "upload"]
    assert nur_tech[-1].is_error is True


def test_a_truncated_line_does_not_hide_the_rest(sandbox, monkeypatch):
    """Ein Abbruch mitten im Schreiben beschaedigt hoechstens die letzte Zeile."""
    log = sandbox / "storage" / "logs" / "daily-run.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ch, "RUN_LOG", log)
    log.write_text(
        json.dumps({"time": "t", "channel": "tech", "step": "render",
                    "message": "ok", "ok": True})
        + '\n{"time": "t2", "channel": "te\n',
        encoding="utf-8",
    )
    events = ch.read_run_log()
    assert len(events) == 1
    assert events[0].message == "ok"


def _task_with_video(root: Path, task_id: str) -> Path:
    """Legt einen fertigen Task an, wie ihn der Renderer hinterlaesst."""
    task = root / "storage" / "tasks" / task_id
    task.mkdir(parents=True)
    video = task / "final-1.mp4"
    video.write_bytes(b"x" * 2048)
    (task / "script.json").write_text(
        json.dumps({"script": "Ein Text.", "params": {"video_subject": task_id}}),
        encoding="utf-8",
    )
    return video


def test_deleting_a_video_removes_the_whole_task(sandbox, monkeypatch):
    """Skript, Untertitel und Ton nuetzen ohne das Video nichts mehr."""
    monkeypatch.setattr(ch, "ROOT", sandbox)
    video = _task_with_video(sandbox, "abc")
    other = _task_with_video(sandbox, "xyz")

    assert ch.delete_video(video) == "abc"
    assert not video.parent.exists()
    # Der Nachbartask bleibt stehen: geloescht wird genau einer.
    assert other.parent.is_dir()


@pytest.mark.parametrize(
    "relativ",
    ["", "..", "../channels", "../../etc"],
)
def test_deleting_outside_the_task_folder_is_refused(sandbox, monkeypatch, relativ):
    """Ein Pfad aus der Oberflaeche darf nie ungeprueft in rmtree laufen."""
    monkeypatch.setattr(ch, "ROOT", sandbox)
    tasks = sandbox / "storage" / "tasks"
    tasks.mkdir(parents=True)
    aussen = sandbox / "channels"
    aussen.mkdir(exist_ok=True)

    ziel = tasks / relativ if relativ else tasks
    with pytest.raises(ch.ChannelError):
        ch.delete_video(ziel)
    assert tasks.is_dir()
    assert aussen.is_dir()


def test_deleting_an_already_gone_task_says_so(sandbox, monkeypatch):
    monkeypatch.setattr(ch, "ROOT", sandbox)
    (sandbox / "storage" / "tasks").mkdir(parents=True)
    with pytest.raises(ch.ChannelError):
        ch.delete_video(sandbox / "storage" / "tasks" / "weg" / "final-1.mp4")


def test_next_step_walks_the_setup_in_order(sandbox, monkeypatch):
    """Jeder Schritt wird erst freigegeben, wenn der vorige wirklich erledigt ist."""
    monkeypatch.setattr(ch, "ROOT", sandbox)
    ch.create_channel("tech", {"source": "news", "topic": "KI"})

    def aktuell() -> ch.NextStep:
        return ch.next_step(ch.load_channel("tech"))

    # 1. Ohne Anmeldung laesst sich nichts hochladen.
    assert aktuell().key == "login"

    token = sandbox / "storage" / "channels" / "tech" / "youtube-token.json"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("{}", encoding="utf-8")

    # 2. Angemeldet, aber das Aussehen ist noch keine der Vorlagen.
    assert aktuell().key == "style"

    kanal = ch.load_channel("tech")
    ch.save_channel("tech", ch.apply_style(kanal.config, "karaoke"))
    assert ch.detect_style(ch.load_channel("tech").config) == "karaoke"

    # 3. Vorlage gewaehlt, aber noch nichts gerendert.
    assert aktuell().key == "render"

    _task_with_video(sandbox, "abc")

    # 4. Ein fertiges Video wartet auf den Upload.
    assert aktuell().key == "upload"

    state = sandbox / "storage" / "channels" / "tech" / "youtube-uploads.json"
    state.write_text(
        json.dumps({"storage/tasks/abc/final-1.mp4": {}}), encoding="utf-8"
    )

    # 5. Alles erledigt — ab hier laeuft der Kanal von allein.
    fertig = aktuell()
    assert fertig.key == "ready"
    assert fertig.progress == 1.0


def test_next_step_progress_grows_with_every_step():
    """Der Balken darf nie zurueckspringen und nie ueber voll hinauslaufen."""
    werte = [
        ch.NextStep(key, index, len(ch.SETUP_STEPS) - 1).progress
        for index, key in enumerate(ch.SETUP_STEPS)
    ]
    assert werte == sorted(werte)
    assert werte[0] == 0.0
    assert werte[-1] == 1.0


def test_every_setup_step_has_a_translation():
    """Ein fehlender Schluessel wuerde als roher Text in der Oberflaeche stehen."""
    english = json.loads(
        (Path(ch.ROOT) / "webui" / "i18n" / "en.json").read_text(encoding="utf-8")
    )["Translation"]
    for step in ch.SETUP_STEPS:
        assert f"Step {step}" in english


def test_the_delete_message_is_shown_before_the_empty_list_aborts():
    """Nach dem letzten Video ist die Liste leer — gerade dann muss die
    Erfolgsmeldung noch kommen.

    Sie wird ueber ``session_state`` durch den ``st.rerun()`` getragen; steht
    ihre Ausgabe hinter dem ``return`` fuer die leere Liste, sieht der Nutzer
    nie eine Bestaetigung, obwohl geloescht wurde.
    """
    import ast

    source = (ch.ROOT / "webui" / "channels_panel.py").read_text(encoding="utf-8")
    funktion = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_render_pending_videos"
    )

    meldung = abbruch = None
    for index, statement in enumerate(funktion.body):
        text = ast.dump(statement)
        if meldung is None and "channel_deleted_" in text:
            meldung = index
        if abbruch is None and isinstance(statement, ast.If):
            if any(isinstance(inner, ast.Return) for inner in statement.body):
                abbruch = index

    assert meldung is not None, "Die Meldung wird gar nicht mehr ausgegeben."
    assert abbruch is not None, "Der Abbruch bei leerer Liste fehlt."
    assert meldung < abbruch


def test_step_texts_only_use_placeholders_the_panel_fills():
    """``{name}`` steht im Befehl, den der Render-Schritt zum Abtippen zeigt.

    Der Text wird ueber einen f-String geholt, den die Schluesselpruefung oben
    nicht sieht. Ein zusaetzlicher Platzhalter in irgendeiner Sprache wuerde
    hier zur Laufzeit ein ``KeyError`` aus ``format()`` werfen.
    """
    import re

    for locale_file in sorted((ch.ROOT / "webui" / "i18n").glob("*.json")):
        translations = json.loads(locale_file.read_text(encoding="utf-8"))[
            "Translation"
        ]
        for step in ch.SETUP_STEPS:
            text = translations.get(f"Step {step}")
            assert text, f"{locale_file.name} fehlt 'Step {step}'"
            unbekannt = set(re.findall(r"\{(\w+)\}", text)) - {"name"}
            assert not unbekannt, f"{locale_file.name}/{step}: {unbekannt}"
            text.format(name="tech")

        fortschritt = translations.get("Channel Step Progress", "")
        assert set(re.findall(r"\{(\w+)\}", fortschritt)) == {"done", "total"}


def test_the_shown_step_number_matches_the_section_headings():
    """Der Balken nennt den laufenden Schritt, nicht die erledigten.

    Die Abschnitte heissen „Schritt 1“ bis „Schritt 4“. Eine „0 von 4“
    darueber wuerde auf einen Abschnitt zeigen, den es nicht gibt.
    """
    total = len(ch.SETUP_STEPS) - 1
    nummern = [ch.NextStep(key, i, total).number for i, key in enumerate(ch.SETUP_STEPS)]
    assert nummern == [1, 2, 3, 4, 4]
    assert ch.NextStep("login", 0, 0).number == 0


def test_a_video_of_another_channel_is_not_offered(sandbox, monkeypatch):
    """Bei zwei Kanaelen lagen sonst beide Listen identisch nebeneinander —
    ein Tech-Video war einen Klick vom falschen Kanal entfernt."""
    monkeypatch.setattr(ch, "ROOT", sandbox)
    ch.create_channel("tech", {"source": "news", "topic": "KI"})
    ch.create_channel("wissen", {"source": "news", "topic": "Alltag"})

    for task_id, owner in [("t1", "tech"), ("t2", "wissen"), ("alt", "")]:
        task = sandbox / "storage" / "tasks" / task_id
        task.mkdir(parents=True)
        (task / "final-1.mp4").write_bytes(b"x" * 2048)
        params = {"video_subject": task_id}
        if owner:
            params["channel"] = owner
        (task / "script.json").write_text(
            json.dumps({"script": "Text.", "params": params}), encoding="utf-8"
        )

    assert [v.task_id for v in ch.pending_videos("tech")] == ["t1", "alt"]
    assert [v.task_id for v in ch.pending_videos("wissen")] == ["t2", "alt"]

    # Das alte Video verschweigt seine Herkunft; still verschwinden waere
    # schlimmer als die Nachfrage beim Nutzer.
    alt = [v for v in ch.pending_videos("tech") if v.task_id == "alt"][0]
    assert alt.is_foreign is True
    eigen = [v for v in ch.pending_videos("tech") if v.task_id == "t1"][0]
    assert eigen.is_foreign is False


def test_saving_the_queue_stamps_the_channel(sandbox):
    """Ohne den Stempel steht dem fertigen Video nicht an, wohin es gehoert."""
    ch.create_channel("tech", {"source": "queue", "topic": "KI"})
    ch.save_queue("tech", [dict(QUEUE_ENTRY)])

    gespeichert = ch.load_queue("tech")
    assert gespeichert[0]["channel"] == "tech"
    # Die uebergebene Liste des Aufrufers bleibt unveraendert.
    assert "channel" not in QUEUE_ENTRY


def test_the_stamped_queue_stays_valid_for_the_pipeline(sandbox):
    """Ein Feld, das cli.py spaeter ablehnt, liesse den Nachtlauf scheitern."""
    ch.create_channel("tech", {"source": "queue", "topic": "KI"})
    ch.save_queue("tech", [dict(QUEUE_ENTRY)])
    params = VideoParams(**ch.load_queue("tech")[0])
    assert params.channel == "tech"


def test_the_script_length_is_part_of_the_channel(sandbox):
    """Die Laenge gehoert zum Kanal, nicht ins Skript — jeder Kanal anders."""
    ch.create_channel("tech", {"source": "news", "topic": "KI"})
    geladen = ch.load_channel("tech")
    assert geladen.config["script_words"] == ch.SCRIPT_WORDS

    ch.save_channel("tech", {**geladen.config, "script_words": 90})
    assert ch.load_channel("tech").config["script_words"] == 90


@pytest.mark.parametrize("wert", [10, 500, "lang"])
def test_an_impossible_script_length_is_refused(sandbox, wert):
    problems = ch.validate_config(
        {**ch.DEFAULT_CONFIG, "topic": "x", "script_words": wert}
    )
    assert any("script_words" in problem for problem in problems)


def test_the_channel_length_reaches_the_research(sandbox, monkeypatch):
    """Was in der Oberflaeche steht, muss beim Schreiben des Skripts ankommen."""
    import news_to_shorts as nts

    monkeypatch.setattr(nts, "ROOT", sandbox)
    monkeypatch.setattr(ch, "CHANNELS_DIR", sandbox / "channels")
    ch.create_channel("tech", {"source": "news", "topic": "KI"})
    ch.save_channel("tech", {**ch.load_channel("tech").config, "script_words": 200})

    assert nts.words_for_channel("tech") == 200


def test_the_delete_button_is_reachable_without_expanding():
    """Ein Knopf, den niemand findet, gibt es nicht.

    Er lag im zugeklappten Bereich „Skript, Quelle und Vorschau“ — wer ein
    Video wegwerfen will, sucht dort nicht.
    """
    source = (ch.ROOT / "webui" / "channels_panel.py").read_text(encoding="utf-8")
    loeschen = source.index('key=f"channel_del_{key}"')
    aufklappbereich = source.index('st.expander(tr("Channel Pending Details")')
    assert loeschen < aufklappbereich

    # Und die Rueckfrage bleibt: einmal danebengeklickt darf nichts kosten.
    bestaetigung = source.index('key=f"channel_delyes_{key}"')
    assert loeschen < bestaetigung < aufklappbereich
