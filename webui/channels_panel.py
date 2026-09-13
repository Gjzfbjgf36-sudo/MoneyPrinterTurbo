"""Streamlit-Oberfläche für die Kanalverwaltung.

Dünne Schicht über :mod:`webui.channels`: hier steht nur Darstellung und
Formularabwicklung, jede Regel liegt im getesteten Kernmodul.

Die Automatik selbst bleibt beim Skript. Diese Seite pflegt die Dateien, die
``scripts/daily_run.ps1`` und ``scripts/youtube_upload.py --channel`` lesen,
und kann einen Probelauf anstoßen.
"""

from __future__ import annotations

import subprocess

import streamlit as st

from webui import channels as ch


def _category_label(category_id: str) -> str:
    name = ch.CATEGORIES.get(str(category_id))
    return f"{category_id} – {name}" if name else str(category_id)


def _source_labels(tr) -> dict[str, str]:
    return {
        "news": tr("Channel Source News"),
        "queue": tr("Channel Source Queue"),
    }


def _select_source(tr, current: str, key: str) -> str:
    """Auswahl der Themenquelle über Anzeigetexte statt über format_func.

    st.selectbox(format_func=...) laesst Streamlits AppTest den Rohwert in der
    bereits formatierten Optionsliste suchen; das laesst jeden Test scheitern,
    der die Oberflaeche laedt. Deshalb sind die Optionen hier direkt die
    Anzeigetexte, und die Zuordnung passiert danach.
    """
    labels = _source_labels(tr)
    options = [labels[source] for source in ch.SOURCES]
    current_label = labels.get(current, options[0])
    chosen = st.selectbox(
        tr("Channel Source"),
        options=options,
        index=options.index(current_label),
        help=tr("Channel Source Help"),
        key=key,
    )
    for source, label in labels.items():
        if label == chosen:
            return source
    return ch.SOURCES[0]


def _render_settings_form(channel: ch.Channel, tr) -> None:
    st.subheader(tr("Channel Settings"))
    with st.form(key=f"channel_form_{channel.name}"):
        config = dict(channel.config)

        source = _select_source(
            tr, config.get("source", "queue"), f"channel_source_{channel.name}"
        )

        topic = st.text_input(
            tr("Channel Topic"),
            value=str(config.get("topic", "")),
            help=tr("Channel Topic Help"),
        )

        # Ein von Hand eingetragener Wert ausserhalb der Spanne laesst
        # st.number_input werfen. Die Seite wird inline gerendert, ein Fehler
        # hier nimmt also die ganze Oberflaeche mit — deshalb begrenzen statt
        # durchreichen.
        try:
            current_count = int(config.get("topics_per_run", 3))
        except (TypeError, ValueError):
            current_count = 3
        topics_per_run = st.number_input(
            tr("Channel Videos Per Run"),
            min_value=1,
            max_value=20,
            value=max(1, min(current_count, 20)),
            key=f"channel_count_{channel.name}",
        )

        category_ids = list(ch.CATEGORIES)
        current_category = str(config.get("category", "27"))
        if current_category not in category_ids:
            category_ids.insert(0, current_category)
        category_labels = [_category_label(value) for value in category_ids]
        chosen_category = st.selectbox(
            tr("Channel Category"),
            options=category_labels,
            index=category_ids.index(current_category),
            key=f"channel_category_{channel.name}",
        )
        category = category_ids[category_labels.index(chosen_category)]

        publish_at = st.text_input(
            tr("Channel Publish Times"),
            value=str(config.get("publish_at", "")),
            help=tr("Channel Publish Times Help"),
        )

        privacy_options = list(ch.PRIVACY_LEVELS)
        current_privacy = config.get("privacy", "private")
        if current_privacy not in privacy_options:
            current_privacy = "private"
        privacy = st.selectbox(
            tr("Channel Privacy"),
            options=privacy_options,
            index=privacy_options.index(current_privacy),
            help=tr("Channel Privacy Help"),
            disabled=bool(publish_at.strip()),
            key=f"channel_privacy_{channel.name}",
        )

        research_model = st.text_input(
            tr("Channel Research Model"),
            value=str(config.get("research_model", "")),
            disabled=source != "news",
            key=f"channel_model_{channel.name}",
        )

        st.divider()
        st.subheader(tr("Channel Look"))
        st.caption(tr("Channel Look Help"))

        voices = list(ch.GERMAN_VOICES)
        current_voice = str(config.get("voice_name", voices[0]))
        if current_voice not in voices:
            voices.insert(0, current_voice)
        voice_name = st.selectbox(
            tr("Channel Voice"),
            options=voices,
            index=voices.index(current_voice),
            help=tr("Channel Voice Help"),
            key=f"channel_voice_{channel.name}",
        )

        voice_rate = st.slider(
            tr("Channel Voice Rate"),
            min_value=0.8,
            max_value=1.5,
            value=float(config.get("voice_rate", 1.2)),
            step=0.05,
            key=f"channel_rate_{channel.name}",
        )

        clip_duration = st.slider(
            tr("Channel Clip Duration"),
            min_value=1,
            max_value=6,
            value=int(config.get("video_clip_duration", 2)),
            help=tr("Channel Clip Duration Help"),
            key=f"channel_clip_{channel.name}",
        )

        # None ist ein gueltiger Wert (keine Bewegung), darf also nicht durch
        # den leeren String ersetzt werden.
        transition_labels = [
            tr("Channel Transition None") if value is None else value
            for value in ch.TRANSITIONS
        ]
        current_transition = config.get("video_transition_mode")
        current_label = (
            tr("Channel Transition None")
            if current_transition is None
            else str(current_transition)
        )
        if current_label not in transition_labels:
            current_label = transition_labels[0]
        chosen_transition = st.selectbox(
            tr("Channel Transition"),
            options=transition_labels,
            index=transition_labels.index(current_label),
            help=tr("Channel Transition Help"),
            key=f"channel_transition_{channel.name}",
        )
        transition = ch.TRANSITIONS[transition_labels.index(chosen_transition)]

        if st.form_submit_button(tr("Channel Save"), type="primary"):
            updated = {
                **config,
                "source": source,
                "topic": topic,
                "topics_per_run": int(topics_per_run),
                "category": category,
                "publish_at": publish_at.strip(),
                "privacy": privacy,
                "research_model": research_model.strip(),
                "voice_name": voice_name,
                "voice_rate": round(float(voice_rate), 2),
                "video_clip_duration": int(clip_duration),
                "video_transition_mode": transition,
            }
            try:
                ch.save_channel(channel.name, updated)
            except ch.ChannelError as exc:
                st.error(str(exc))
            else:
                st.success(tr("Channel Saved"))
                st.rerun()


def _render_queue_editor(channel: ch.Channel, tr) -> None:
    if channel.is_news:
        st.info(tr("Channel Queue Not Needed"))
        return

    subjects = ch.queue_subjects(channel.queue)
    with st.form(key=f"channel_queue_{channel.name}"):
        text = st.text_area(
            tr("Channel Queue"),
            value="\n".join(subjects),
            height=200,
            help=tr("Channel Queue Help"),
        )
        if st.form_submit_button(tr("Channel Queue Save")):
            entries = ch.apply_subjects(channel.queue, text.splitlines())
            try:
                ch.save_queue(channel.name, entries)
            except ch.ChannelError as exc:
                st.error(str(exc))
            else:
                st.success(tr("Channel Queue Saved").format(count=len(entries)))
                st.rerun()


def _render_dry_run(channel: ch.Channel, tr) -> None:
    command = ch.runner_command(channel.name, dry_run=True)
    # Ohne Ueberschrift findet niemand den Knopf, auf den der Schritt zeigt.
    st.subheader(tr("Channel Dry Run Section"))

    if not ch.supports_channel_runner():
        # daily_run.sh kennt weder einzelne Kanäle noch einen Probelauf.
        st.info(tr("Channel Dry Run Windows Only"))
        st.code(" ".join(command))
        return

    st.caption(tr("Channel Dry Run Help"))
    if not st.button(tr("Channel Dry Run"), key=f"channel_dry_{channel.name}"):
        return

    with st.spinner(tr("Channel Dry Run Running")):
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(ch.ROOT),
                timeout=3600,
            )
        except subprocess.TimeoutExpired:
            st.error(tr("Channel Dry Run Timeout"))
            return
        except OSError as exc:
            st.error(str(exc))
            return

    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        st.success(tr("Channel Dry Run Done"))
    else:
        st.error(tr("Channel Dry Run Failed").format(code=completed.returncode))
    st.code(output[-8000:] or tr("Channel Dry Run No Output"))


def _run_script(command: list[str], spinner: str, tr) -> tuple[int, str]:
    """Führt ein Skript aus und gibt Rückgabewert und Ausgabe zurück."""
    with st.spinner(spinner):
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(ch.ROOT),
                timeout=3600,
            )
        except subprocess.TimeoutExpired:
            return 1, tr("Channel Dry Run Timeout")
        except OSError as exc:
            return 1, str(exc)
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _render_next_step(channel: ch.Channel, tr) -> None:
    """Ein klarer naechster Schritt statt einer Wand aus Einstellungen."""
    step = ch.next_step(channel)
    # „Schritt 4 von 4“ stand sonst sowohl über dem Hochladen als auch über
    # dem fertig eingerichteten Kanal — zwei Zustände, eine Beschriftung.
    if step.key == "ready":
        label = tr("Channel Step Done")
    else:
        label = tr("Channel Step Progress").format(done=step.number, total=step.total)
    st.progress(step.progress, text=label)
    # Der Kanalname steht im Befehl, den "Step render" zum Abtippen anbietet.
    # Die übrigen Schritte kennen keinen Platzhalter; format() stört das nicht.
    text = tr(f"Step {step.key}").format(name=channel.name)
    if step.key == "ready":
        st.success(text)
    else:
        st.info(text)


def _render_login(channel: ch.Channel, tr) -> None:
    # Jeder angesagte Schritt braucht eine sichtbare Überschrift, sonst
    # zeigt der Text auf einen Abschnitt, den es optisch nicht gibt.
    st.subheader(tr("Channel Login Section"))
    if ch.is_logged_in(channel.name):
        st.caption(tr("Channel Logged In"))
        return

    st.warning(tr("Channel Not Logged In"))
    if not st.button(tr("Channel Login"), key=f"channel_login_{channel.name}"):
        return

    code, output = _run_script(
        ch.login_command(channel.name), tr("Channel Login Running"), tr
    )
    if code == 0:
        st.success(tr("Channel Login Done"))
        st.rerun()
    else:
        st.error(tr("Channel Login Failed"))
        st.code(output[-4000:])


def _render_pending_videos(channel: ch.Channel, tr) -> None:
    """Fertige Videos mit Quellenangabe prüfen und auswählen."""
    videos = ch.pending_videos(channel.name)
    st.subheader(tr("Channel Pending"))

    # Die Meldung des letzten Löschens. Sie muss den Neuaufbau überleben:
    # auf das Löschen folgt st.rerun(), das den Bildschirm neu zeichnet,
    # bevor irgendjemand einen Text lesen konnte. Und sie steht vor dem
    # Abbruch weiter unten: nach dem letzten Video ist die Liste leer, und
    # gerade dann will man wissen, dass das Löschen geklappt hat.
    deleted = st.session_state.pop(f"channel_deleted_{channel.name}", "")
    if deleted:
        st.success(tr("Channel Deleted").format(name=deleted))

    if not videos:
        st.info(tr("Channel Pending Empty"))
        return

    st.caption(tr("Channel Pending Help"))
    selected: list = []
    for video in videos:
        key = f"{channel.name}_{video.task_id}"
        # Die beiden Warnungen gehören in die Zeile, nicht nur in den
        # Aufklappbereich: ausgewählt wird hier, und hochgeladen wird, was
        # ausgewählt ist — ohne dass jemand aufklappen muss.
        marker = ""
        if not video.source:
            marker += f"  ·  ⚠️ {tr('Channel No Source Short')}"
        if video.is_foreign:
            marker += f"  ·  ❓ {tr('Channel Unknown Owner Short')}"
        checked = st.checkbox(
            f"{video.subject}  ·  {video.words} "
            f"{tr('Channel Words')}  ·  {video.size_mb} MB{marker}",
            key=f"channel_pick_{key}",
        )
        with st.expander(tr("Channel Pending Details"), expanded=False):
            if video.source:
                # Die Quelle ist der Grund, warum diese Liste existiert: hier
                # wird geprüft, bevor eine Behauptung öffentlich wird.
                st.markdown(f"**{tr('Channel Source Link')}:** {video.source}")
            else:
                st.warning(tr("Channel No Source"))
            if video.is_foreign:
                st.warning(tr("Channel Unknown Owner"))
            st.write(video.script or tr("Channel No Script"))
            if video.path.exists():
                st.video(str(video.path))

            # Löschen gehört hierher und nicht neben das Auswahlkästchen:
            # erst ansehen, dann verwerfen.
            confirm_key = f"channel_delconfirm_{key}"
            if st.session_state.get(confirm_key):
                st.warning(tr("Channel Delete Confirm").format(subject=video.subject))
                yes, no = st.columns(2)
                if yes.button(tr("Channel Delete Yes"), key=f"channel_delyes_{key}"):
                    try:
                        removed = ch.delete_video(video.path)
                    except ch.ChannelError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state.pop(confirm_key, None)
                        st.session_state[f"channel_deleted_{channel.name}"] = removed
                        st.rerun()
                if no.button(tr("Channel Delete No"), key=f"channel_delno_{key}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            elif st.button(tr("Channel Delete"), key=f"channel_del_{key}"):
                st.session_state[confirm_key] = True
                st.rerun()
        if checked:
            selected.append(video)

    st.divider()
    schedule = st.checkbox(
        tr("Channel Upload Scheduled"),
        value=bool(str(channel.config.get("publish_at", "")).strip()),
        key=f"channel_sched_{channel.name}",
        help=tr("Channel Upload Scheduled Help"),
    )
    privacy_options = list(ch.PRIVACY_LEVELS)
    privacy = st.selectbox(
        tr("Channel Privacy"),
        options=privacy_options,
        index=0,
        disabled=schedule,
        key=f"channel_uploadvis_{channel.name}",
    )

    if not st.button(
        tr("Channel Upload"),
        type="primary",
        disabled=not selected or not ch.is_logged_in(channel.name),
        key=f"channel_upload_{channel.name}",
    ):
        return

    command = ch.upload_command(
        channel.name,
        [video.path for video in selected],
        publish_at=str(channel.config.get("publish_at", "")) if schedule else "",
        privacy=privacy,
    )
    code, output = _run_script(command, tr("Channel Upload Running"), tr)
    if code == 0:
        st.success(tr("Channel Upload Done").format(count=len(selected)))
    else:
        st.error(tr("Channel Upload Failed").format(code=code))
    st.code(output[-8000:] or tr("Channel Dry Run No Output"))


def _render_style_picker(channel: ch.Channel, tr) -> None:
    """Fertige Look-Kombinationen. Einzelwerte sind schwer einzuschätzen."""
    # Ohne Ueberschrift geht der Abschnitt zwischen den Formularfeldern unter.
    st.subheader(tr("Channel Styles"))
    current = ch.detect_style(channel.config)
    names = list(ch.STYLES)
    labels = [tr(f"Style {name}") for name in names]

    cols = st.columns([3, 1], vertical_alignment="bottom")
    chosen = cols[0].selectbox(
        tr("Channel Style"),
        options=labels,
        index=names.index(current) if current in names else 0,
        help=tr("Channel Style Help"),
        key=f"channel_style_{channel.name}",
    )
    if current is None:
        st.caption(tr("Channel Style Custom"))

    if cols[1].button(tr("Channel Style Apply"), key=f"channel_styleapply_{channel.name}"):
        try:
            updated = ch.apply_style(channel.config, names[labels.index(chosen)])
            ch.save_channel(channel.name, updated)
        except ch.ChannelError as exc:
            st.error(str(exc))
        else:
            st.success(tr("Channel Style Applied"))
            st.rerun()


def _render_run_log(channel: ch.Channel, tr) -> None:
    """Wo der Tageslauf dieses Kanals gerade steht."""
    events = ch.read_run_log(limit=40, channel=channel.name)
    with st.expander(tr("Channel Run Log"), expanded=False):
        st.caption(tr("Channel Run Log Help"))
        if not events:
            st.info(tr("Channel Run Log Empty"))
            return

        if st.button(tr("Channel Run Log Refresh"), key=f"channel_logrefresh_{channel.name}"):
            st.rerun()

        # Neueste zuerst: beim Nachsehen interessiert der letzte Stand.
        for event in reversed(events):
            line = f"`{event.time}` · **{event.step}** · {event.message}"
            if event.is_error:
                st.error(line)
            else:
                st.markdown(line)


def _render_new_channel(tr) -> None:
    with st.form(key="channel_create"):
        name = st.text_input(
            tr("Channel New Name"),
            help=tr("Channel New Name Help"),
            key="channel_new_name",
        )
        source = _select_source(tr, "queue", "channel_new_source")
        topic = st.text_input(tr("Channel Topic"), key="channel_new_topic")
        if st.form_submit_button(tr("Channel Create"), type="primary"):
            try:
                ch.create_channel(name.strip(), {"source": source, "topic": topic})
            except ch.ChannelError as exc:
                st.error(str(exc))
            else:
                st.success(tr("Channel Created").format(name=name.strip()))
                st.rerun()


def render_channels_panel(tr) -> None:
    """Zeichnet die Kanalverwaltung. ``tr`` ist die Übersetzungsfunktion."""
    with st.expander(tr("Channels"), expanded=False):
        st.caption(tr("Channels Help"))

        channels = ch.load_channels()
        if not channels:
            st.info(tr("Channels Empty"))
        else:
            tabs = st.tabs([channel.name for channel in channels])
            for channel, tab in zip(channels, tabs):
                with tab:
                    queue_size = len(channel.queue)
                    stats = st.columns(3)
                    stats[0].metric(
                        tr("Channel Mode"),
                        tr("Channel Source News") if channel.is_news
                        else tr("Channel Source Queue"),
                    )
                    stats[1].metric(
                        tr("Channel Queue Size"), "—" if channel.is_news else queue_size
                    )
                    stats[2].metric(tr("Channel Uploaded"), channel.uploaded)

                    # Die Abschnitte stehen in der Reihenfolge der Schritte,
                    # die oben angesagt werden: anmelden, Vorlage, erzeugen,
                    # hochladen. Sonst zeigt der angesagte Schritt an eine
                    # Stelle, die der Nutzer erst suchen muss.
                    _render_next_step(channel, tr)
                    _render_login(channel, tr)
                    _render_style_picker(channel, tr)
                    _render_dry_run(channel, tr)
                    _render_pending_videos(channel, tr)
                    _render_run_log(channel, tr)

                    # Ab hier nur noch Feinheiten, die kein Schritt verlangt.
                    st.divider()
                    _render_settings_form(channel, tr)
                    _render_queue_editor(channel, tr)

        st.divider()
        st.caption(tr("Channel New"))
        _render_new_channel(tr)
