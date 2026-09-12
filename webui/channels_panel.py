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

        topics_per_run = st.number_input(
            tr("Channel Videos Per Run"),
            min_value=1,
            max_value=20,
            value=int(config.get("topics_per_run", 3)),
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
        )

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

                    _render_settings_form(channel, tr)
                    _render_queue_editor(channel, tr)
                    _render_dry_run(channel, tr)

        st.divider()
        st.caption(tr("Channel New"))
        _render_new_channel(tr)
