"""Idempotent synthetic data for the dedicated public-screenshot fixture only."""

from pathlib import Path

from hub.db import Conversation, Message, Project
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
database = ROOT / ".local" / "website-fixture" / "fixture.sqlite"
if not database.is_file():
    raise SystemExit("Start the dedicated website fixture first")
engine = create_engine("sqlite:///" + str(database))
with Session(engine) as db:
    project = db.scalar(select(Project).where(Project.name == "Projekt Aurora"))
    if not project:
        project = Project(
            name="Projekt Aurora",
            description="Synthetisches Beispiel: Wissen sammeln, Ideen entwickeln und Ergebnisse "
            "als Dateien festhalten.",
        )
        db.add(project)
        db.flush()
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.project_id == project.id,
            Conversation.title == "Ideen werden Ergebnisse",
        )
    )
    if not conversation:
        conversation = Conversation(
            project_id=project.id, title="Ideen werden Ergebnisse", manual_title=True
        )
        db.add(conversation)
        db.flush()
        db.add_all(
            [
                Message(
                    conversation_id=conversation.id,
                    role="user",
                    content="Wie können wir aus unseren Projektunterlagen einen klaren "
                    "nächsten Schritt ableiten?",
                ),
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content="## Ein klarer Plan für Projekt Aurora\n\n"
                    "Wir bündeln die Unterlagen in einem Projektraum und arbeiten mit einem "
                    "gemeinsamen Überblick.\n\n"
                    "1. **Wissen sammeln:** Dokumente hochladen und öffentliche Webseiten "
                    "als Quellen hinzufügen.\n"
                    "2. **Zusammenhänge verstehen:** Im Projektchat Fragen stellen und "
                    "Fundstellen nachvollziehen.\n"
                    "3. **Ergebnisse festhalten:** Eine Word-Datei oder Präsentation "
                    "entwerfen und die Vorschau prüfen.\n\n"
                    "### Der nächste Schritt\nErstelle eine kurze Projektübersicht mit Ziel, "
                    "offenen Fragen und den nächsten drei Aufgaben. Alle Inhalte bleiben "
                    "zunächst lokal.\n\n"
                    "*Diese Unterhaltung enthält ausschließlich synthetische Beispieldaten.*",
                ),
            ]
        )
        db.commit()
print("Dedicated synthetic showcase conversation ready")
