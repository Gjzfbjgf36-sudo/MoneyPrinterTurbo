#!/usr/bin/env python3
"""Prüft Skripte durch spezialisierte Durchgänge, bevor ein Video entsteht.

Für jedes Thema wird zuerst ein Skript erzeugt und danach von mehreren
Fachprüfungen begutachtet: Faktenlage, Kurzformat-Tauglichkeit und
Auffindbarkeit. Aus den Befunden entsteht eine überarbeitete Fassung, die als
``video_script`` in die Ausgabedatei geschrieben wird — die Renderphase
übernimmt sie unverändert und erzeugt kein neues Skript mehr.

Themen mit ungelösten schweren Befunden landen in einer zweiten Datei und
werden nicht gerendert.

Aufruf:
  python scripts/review_topics.py tasks.jsonl
  python scripts/review_topics.py tasks.jsonl --out geprueft.jsonl --language de-DE

Grenzen: Die Prüfungen laufen über dasselbe Sprachmodell wie die Erzeugung und
haben keinen Zugriff auf Quellen. Sie erkennen Rechenfehler, unbelegte
Superlative und unrealistische Annahmen — sie ersetzen keine Recherche.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services import llm  # noqa: E402

MAX_ROUNDS = 3
# Nur Sachfehler halten ein Thema auf. Stil- und Auffindbarkeitsbefunde gehen in
# die Überarbeitung ein, blockieren aber nicht: Die Prüfungen finden dort immer
# etwas, und ein perfekt optimierter Text ist kein Freigabekriterium.
BLOCKING_REVIEWER = "fakten"

REVIEWERS = {
    "fakten": """Du prüfst den folgenden Sprechtext eines Kurzvideos auf sachliche Richtigkeit.

Achte besonders auf: falsch gerechnete Beispiele, unrealistische Annahmen,
verwechselte Größenordnungen, fehlende Angabe der Annahme bei jeder Prozent-
oder Renditezahl, absolute Aussagen ohne Einschränkung, und Behauptungen, die
als Beratung gelesen werden könnten.

Rechne jedes Zahlenbeispiel nach und melde Abweichungen über zehn Prozent.

Antworte ausschließlich mit JSON:
{"befunde": [{"stelle": "zitierter Ausschnitt", "problem": "...", "schwere": "hoch|mittel|niedrig", "korrektur": "..."}]}
Keine Befunde bedeutet: {"befunde": []}""",
    "kurzformat": """Du bewertest den folgenden Sprechtext als Kurzvideo-Redakteur.

Achte auf: trägt der erste Satz allein (überraschend, konkret, ohne Anlauf),
Wortzahl über 95, Sätze über 20 Wörter, Füllwörter, abstrakte Passagen ohne
Bild im Kopf, ein Schluss ohne konkrete Handlung.

Antworte ausschließlich mit JSON:
{"befunde": [{"stelle": "zitierter Ausschnitt", "problem": "...", "schwere": "hoch|mittel|niedrig", "korrektur": "..."}]}""",
    "auffindbarkeit": """Du bewertest den folgenden Sprechtext für die Auffindbarkeit auf YouTube.

Prüfe, ob der Text den Suchbegriff enthält, nach dem jemand tatsächlich sucht,
ob der erste Satz auch als Titel funktioniert, und ob konkrete Zahlen enthalten
sind, die sich in einen Titel übernehmen lassen.

Antworte ausschließlich mit JSON:
{"befunde": [{"stelle": "...", "problem": "...", "schwere": "hoch|mittel|niedrig", "korrektur": "..."}], "titel": "Titelvorschlag unter 80 Zeichen", "suchbegriffe": ["...", "..."]}""",
}

EDITOR_PROMPT = """Überarbeite den folgenden Sprechtext anhand der Prüfbefunde.

Übernimm jede Korrektur, ohne den Text zu verlängern: Er muss unter 95 Wörtern
bleiben, im selben Ton, in derselben Sprache, mit demselben Aufbau aus
Aufhänger, drei Punkten und einer Handlung am Ende.

Gib ausschließlich den überarbeiteten Sprechtext aus, ohne Vorrede, ohne
Anführungszeichen, ohne Erklärung, was du geändert hast.

SPRECHTEXT:
{script}

BEFUNDE:
{findings}"""


def ask(prompt: str) -> str:
    """Eine Anfrage an den konfigurierten Anbieter.

    Nutzt bewusst denselben internen Einstiegspunkt wie die Skript- und
    Keyword-Erzeugung, damit Provider-Auswahl, Zeitüberschreitungen und
    Fehlerbehandlung identisch bleiben.
    """
    return llm._generate_response(prompt)


def parse_json_response(raw: str) -> dict:
    """Liest JSON auch dann, wenn das Modell es in Fließtext einbettet."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def run_reviews(script: str) -> tuple[list[dict], dict]:
    """Alle Prüfungen über denselben Text; liefert Befunde und Zusatzangaben."""
    findings: list[dict] = []
    extras: dict = {}
    for name, instruction in REVIEWERS.items():
        answer = parse_json_response(ask(f"{instruction}\n\nSPRECHTEXT:\n{script}"))
        for finding in answer.get("befunde") or []:
            if isinstance(finding, dict):
                findings.append({**finding, "pruefung": name})
        for key in ("titel", "suchbegriffe"):
            if answer.get(key):
                extras[key] = answer[key]
    return findings, extras


def severity_of(findings: list[dict], level: str) -> list[dict]:
    return [f for f in findings if str(f.get("schwere", "")).lower() == level]


def format_findings(findings: list[dict]) -> str:
    return "\n".join(
        f"- [{f.get('pruefung')}/{f.get('schwere')}] {f.get('problem')} "
        f"→ {f.get('korrektur')}"
        for f in findings
    )


def review_topic(subject: str, language: str, script_prompt: str) -> dict:
    """Erzeugt, prüft und überarbeitet ein Skript bis es sauber ist."""
    print(f"\n=== {subject} ===")
    script = llm.generate_script(
        video_subject=subject,
        language=language,
        paragraph_number=1,
        video_script_prompt=script_prompt,
    )
    if not script or "Error: " in script:
        return {"subject": subject, "ok": False, "grund": "Skripterzeugung fehlgeschlagen"}

    extras: dict = {}
    findings: list[dict] = []
    approved_script: str | None = None
    for round_number in range(1, MAX_ROUNDS + 1):
        findings, extras = run_reviews(script)
        severe = severity_of(findings, "hoch")
        medium = severity_of(findings, "mittel")
        blocking = [f for f in severe if f.get("pruefung") == BLOCKING_REVIEWER]
        print(
            f"  Runde {round_number}: {len(findings)} Befund(e) "
            f"({len(severe)} schwer, davon {len(blocking)} sachlich, "
            f"{len(medium)} mittel)"
        )
        for finding in findings:
            print(f"    [{finding.get('pruefung')}] {finding.get('problem')}")

        if not blocking:
            # Sachlich sauber. Weitere Stilrunden lohnen nicht: Jede
            # Überarbeitung kann neue Fehler einbauen, und genau das ist in
            # Tests passiert. Diese Fassung wird verwendet.
            approved_script = script
            break
        if round_number == MAX_ROUNDS:
            break
        script = ask(
            EDITOR_PROMPT.format(script=script, findings=format_findings(findings))
        ).strip()
        print(f"  überarbeitet: {len(script.split())} Wörter")

    remaining = [
        finding
        for finding in severity_of(findings, "hoch")
        if finding.get("pruefung") == BLOCKING_REVIEWER
    ]
    script = approved_script or script
    return {
        "subject": subject,
        "ok": not remaining,
        "script": script,
        "befunde": findings,
        "offen": remaining,
        "titel": extras.get("titel"),
        "suchbegriffe": extras.get("suchbegriffe"),
    }


def read_topics(path: Path) -> list[dict]:
    topics = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            sys.exit(f"Zeile ist kein gültiges JSON: {line[:80]}")
        if not entry.get("video_subject"):
            sys.exit(f"Zeile ohne video_subject: {line[:80]}")
        topics.append(entry)
    return topics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prüft Skripte vor der Videoproduktion."
    )
    parser.add_argument("tasks", help="Themenliste im JSONL-Format")
    parser.add_argument(
        "--out", default="tasks-approved.jsonl",
        help="Zieldatei für freigegebene Themen (Standard: tasks-approved.jsonl)",
    )
    parser.add_argument(
        "--rejected", default="tasks-review.jsonl",
        help="Zieldatei für Themen mit offenen Befunden",
    )
    parser.add_argument(
        "--report", default="tasks-report.json",
        help="Zieldatei für Befunde, Titelvorschläge und Suchbegriffe",
    )
    parser.add_argument("--language", default="de-DE")
    parser.add_argument(
        "--script-prompt-file", default=None,
        help="Datei mit dem Skript-Prompt; ohne Angabe gilt der Standard",
    )
    args = parser.parse_args()

    script_prompt = ""
    if args.script_prompt_file:
        script_prompt = Path(args.script_prompt_file).read_text(encoding="utf-8")

    topics = read_topics(Path(args.tasks))
    approved, rejected, report = [], [], []
    for entry in topics:
        result = review_topic(entry["video_subject"], args.language, script_prompt)
        # Titelvorschlag und Suchbegriffe gehören nicht in die Themenliste:
        # Der Batch-Modus lehnt unbekannte Felder ab. Sie landen im Bericht.
        report.append(
            {
                "thema": result["subject"],
                "freigegeben": bool(result.get("ok")),
                "titelvorschlag": result.get("titel"),
                "suchbegriffe": result.get("suchbegriffe"),
                "befunde": result.get("befunde"),
            }
        )
        if result.get("ok") and result.get("script"):
            approved.append(
                {
                    **entry,
                    # Ein gesetztes video_script überspringt die Skripterzeugung
                    # beim Rendern; geprüft wird also genau das, was gesendet wird.
                    "video_script": result["script"],
                }
            )
        else:
            rejected.append({**entry, "_befunde": result.get("offen") or result})

    Path(args.out).write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in approved),
        encoding="utf-8",
    )
    Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if rejected:
        # Anhängen, nicht überschreiben: daily_run nimmt zurückgestellte Themen
        # endgültig aus tasks.jsonl heraus, sie stehen danach nur noch hier.
        # Ein Überschreiben hätte die Befunde des Vortags gelöscht, und damit
        # die einzige Spur der aussortierten Themen.
        with Path(args.rejected).open("a", encoding="utf-8") as handle:
            for item in rejected:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(
        f"\nFreigegeben: {len(approved)} → {args.out}"
        + (f"\nZurückgestellt: {len(rejected)} → {args.rejected}" if rejected else "")
        + f"\nBericht: {args.report}"
    )


if __name__ == "__main__":
    main()
