"""Optionally project-scoped declarative forms and immutable local results; no model execution."""

import csv
import hashlib
import io
import json
import math
import re
import time
from datetime import date
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import (
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    func,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from hub.db import Base, Project, new_id
from hub.db_locks import ownership_lock
from hub.knowledge_api import Auth


class UseCase(Base):
    __tablename__ = "use_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class UseCaseRevision(Base):
    __tablename__ = "use_case_revisions"
    use_case_id: Mapped[str] = mapped_column(ForeignKey("use_cases.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    spec: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))


class UseCaseRun(Base):
    __tablename__ = "use_case_runs"
    __table_args__ = (UniqueConstraint("use_case_id", "request_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    use_case_id: Mapped[str] = mapped_column(ForeignKey("use_cases.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputField(Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=100)
    type: Literal["text", "long_text", "number", "date", "choice"] = "text"
    required: bool = True
    choices: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def options(self) -> "InputField":
        if any(
            not x.strip()
            or len(x) > 100
            or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]", x)
            for x in self.choices
        ):
            raise ValueError("Auswahloptionen benötigen 1 bis 100 Zeichen")
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("Auswahloptionen müssen eindeutig sein")
        if (self.type == "choice") != bool(self.choices):
            raise ValueError("Nur Auswahlfelder benötigen Auswahloptionen")
        return self


class OutputColumn(Strict):
    label: str = Field(min_length=1, max_length=100)
    source: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")


class Definition(Strict):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    presentation: Literal["form", "dialogue"] = "form"
    fields: list[InputField] = Field(min_length=1, max_length=20)
    output_kind: Literal["table", "csv", "xlsx", "bi", "chat"] = "table"
    output_columns: list[OutputColumn] = Field(min_length=1, max_length=20)
    text_template: str = Field(default="", max_length=8000)

    @model_validator(mode="after")
    def references(self) -> "Definition":
        texts = [
            self.name,
            self.description,
            self.text_template,
            *[f.label for f in self.fields],
            *[c.label for c in self.output_columns],
        ]
        if (
            not self.name.strip()
            or any(not f.label.strip() for f in self.fields)
            or any(not c.label.strip() for c in self.output_columns)
        ):
            raise ValueError("Name und Beschriftungen dürfen nicht leer sein")
        if any(re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]", v) for v in texts):
            raise ValueError("Ungültige Steuerzeichen")
        keys = {f.key for f in self.fields}
        if len(keys) != len(self.fields):
            raise ValueError("Feldschlüssel müssen eindeutig sein")
        if any(c.source not in keys for c in self.output_columns):
            raise ValueError("Ausgabespalte verweist auf unbekanntes Feld")
        if len({c.source for c in self.output_columns}) != len(self.output_columns):
            raise ValueError("Ein Feld darf nur einmal ausgegeben werden")
        if self.output_kind == "bi" and not any(f.type == "number" for f in self.fields):
            raise ValueError("Diagramme benötigen ein Zahlenfeld")
        tokens = re.findall(r"\{([^{}]*)\}", self.text_template)
        if any(token not in keys for token in tokens):
            raise ValueError("Textvorlage verweist auf unbekanntes Feld")
        if self.output_kind == "chat" and not self.text_template.strip():
            raise ValueError("Textausgabe benötigt eine Textvorlage")
        return self


class SaveInput(Strict):
    project_id: UUID | None = None
    spec: Definition
    expected_revision: int | None = Field(default=None, ge=1)


class DeleteInput(Strict):
    expected_revision: int = Field(ge=1)


class RunInput(Strict):
    request_id: UUID
    expected_revision: int = Field(ge=1)
    values: dict[str, Any]


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def validated_values(spec: Definition, values: dict[str, Any]) -> dict[str, Any]:
    if set(values) - {f.key for f in spec.fields}:
        raise HTTPException(422, "Unbekanntes Eingabefeld")
    result: dict[str, Any] = {}
    for field in spec.fields:
        value = values.get(field.key)
        if value is None or value == "" or (isinstance(value, str) and not value.strip()):
            if field.required:
                raise HTTPException(422, field.label + " fehlt")
            result[field.key] = None
            continue
        valid = False
        if field.type == "number":
            valid = type(value) in (int, float) and abs(value) <= 1e15 and math.isfinite(value)
        elif isinstance(value, str):
            valid = len(value) <= (8000 if field.type == "long_text" else 1000) and not re.search(
                r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]", value
            )
            if field.type == "choice":
                valid = value in field.choices
            elif field.type == "date":
                try:
                    valid = date.fromisoformat(value).isoformat() == value
                except ValueError:
                    valid = False
        if not valid:
            raise HTTPException(422, "Ungültiger Wert: " + field.label)
        result[field.key] = value
    return result


def result_for(spec: Definition, values: dict[str, Any]) -> dict[str, Any]:
    text = re.sub(
        r"\{([^{}]*)\}",
        lambda m: str(values[m[1]]) if values.get(m[1]) is not None else "",
        spec.text_template,
    )
    return {
        "columns": [c.label for c in spec.output_columns],
        "row": [values.get(c.source) for c in spec.output_columns],
        "text": text,
        "chart": [
            {"label": f.label, "value": values[f.key]}
            for f in spec.fields
            if f.type == "number" and values[f.key] is not None
        ],
    }


def project_case_witness(db: Any, project_id: str) -> dict[str, Any]:
    cases = list(db.scalars(select(UseCase).where(UseCase.project_id == project_id)))
    ids = [c.id for c in cases]
    runs = list(db.scalars(select(UseCaseRun).where(UseCaseRun.use_case_id.in_(ids))))
    return {
        "use_cases": len(cases),
        "use_case_runs": len(runs),
        "state": sorted([(c.id, c.revision) for c in cases])
        + sorted([(r.id, r.request_digest) for r in runs]),
    }


def delete_project_cases(db: Any, project_id: str) -> None:
    ids = select(UseCase.id).where(UseCase.project_id == project_id)
    db.execute(delete(UseCaseRun).where(UseCaseRun.use_case_id.in_(ids)))
    db.execute(delete(UseCaseRevision).where(UseCaseRevision.use_case_id.in_(ids)))
    db.execute(delete(UseCase).where(UseCase.project_id == project_id))


def install_use_case_api(app: FastAPI, cfg: Any, factory: Any) -> None:
    prefix = "/api/projects/{project_id}/use-cases"

    def project(db: Any, project_id: str, write: bool = False) -> None:
        row = db.get(Project, project_id)
        if not row or row.kind != "project":
            raise HTTPException(404, "Projekt nicht gefunden")
        if write and row.archived:
            raise HTTPException(409, "Archiviertes Projekt ist schreibgeschützt")

    def case(db: Any, project_id: str | None, identifier: str) -> UseCase:
        if project_id is not None:
            project(db, project_id)
        row = db.get(UseCase, identifier)
        if not row or (project_id is not None and row.project_id != project_id):
            raise HTTPException(404, "Use Case nicht gefunden")
        return cast(UseCase, row)

    def current_query(project_id: str | None = None) -> Any:
        query = select(UseCase, UseCaseRevision).outerjoin(
            UseCaseRevision,
            (UseCaseRevision.use_case_id == UseCase.id)
            & (UseCaseRevision.revision == UseCase.revision),
        )
        if project_id is not None:
            query = query.where(UseCase.project_id == project_id)
        return query

    def info(db: Any, row: UseCase, revision: UseCaseRevision | None = None) -> dict[str, Any]:
        if revision is None:
            revision = db.get(UseCaseRevision, (row.id, row.revision))
        if revision is None:
            raise HTTPException(409, "Use-Case-Definition fehlt; gespeicherten Stand prüfen")
        return {
            "id": row.id,
            "revision": row.revision,
            "project_id": row.project_id,
            "spec": json.loads(revision.spec),
            "label": "LOCAL_ONLY",
        }

    def loaded_info(db: Any, row: UseCase, revision: UseCaseRevision | None) -> dict[str, Any]:
        if revision is None:
            raise HTTPException(409, "Use-Case-Definition fehlt; gespeicherten Stand prüfen")
        return info(db, row, revision)

    @app.get("/api/use-cases")
    @app.get(prefix)
    def listing(auth: Auth, project_id: str | None = None) -> list[dict[str, Any]]:
        with factory() as db:
            if project_id is not None:
                project(db, project_id)
            # Fetch ownership, current revision and definition in one SQL snapshot.
            # A concurrent delete cannot remove the definition between separate reads.
            query = current_query(project_id).order_by(UseCase.id)
            return [loaded_info(db, row, revision) for row, revision in db.execute(query)]

    @app.post("/api/use-cases")
    @app.post(prefix)
    def create(body: SaveInput, auth: Auth, project_id: str | None = None) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            target = str(body.project_id) if body.project_id is not None else None
            if project_id is not None:
                if "project_id" in body.model_fields_set and target != project_id:
                    raise HTTPException(
                        422, "Projektbezug stimmt nicht mit dem Projektpfad überein"
                    )
                target = project_id
            if target is not None:
                project(db, target, True)
            row = UseCase(project_id=target)
            db.add(row)
            db.flush()
            spec = encode(body.spec.model_dump())
            db.add(UseCaseRevision(use_case_id=row.id, revision=1, spec=spec, sha256=digest(spec)))
            db.flush()
            answer = info(db, row)
            db.commit()
            return answer

    @app.put("/api/use-cases/{identifier}")
    @app.put(prefix + "/{identifier}")
    def edit(
        identifier: str, body: SaveInput, auth: Auth, project_id: str | None = None
    ) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            row = case(db, project_id, identifier)
            if row.project_id is not None:
                project(db, row.project_id, True)
            if body.expected_revision != row.revision:
                raise HTTPException(409, "Use Case inzwischen geändert")
            if "project_id" in body.model_fields_set:
                target = str(body.project_id) if body.project_id is not None else None
                if project_id is not None and target != project_id:
                    raise HTTPException(
                        422, "Projektbezug über die globale Use-Case-Ansicht ändern"
                    )
                if target is not None:
                    project(db, target, True)
                row.project_id = target
            row.revision += 1
            spec = encode(body.spec.model_dump())
            db.add(
                UseCaseRevision(
                    use_case_id=row.id, revision=row.revision, spec=spec, sha256=digest(spec)
                )
            )
            db.flush()
            answer = info(db, row)
            db.commit()
            return answer

    @app.delete("/api/use-cases/{identifier}")
    @app.delete(prefix + "/{identifier}")
    def remove(
        identifier: str, body: DeleteInput, auth: Auth, project_id: str | None = None
    ) -> dict[str, bool]:
        with factory() as db:
            ownership_lock(db)
            row = case(db, project_id, identifier)
            if row.project_id is not None:
                project(db, row.project_id, True)
            if body.expected_revision != row.revision:
                raise HTTPException(409, "Use Case inzwischen geändert")
            db.execute(delete(UseCaseRun).where(UseCaseRun.use_case_id == identifier))
            db.execute(delete(UseCaseRevision).where(UseCaseRevision.use_case_id == identifier))
            db.delete(row)
            db.commit()
            return {"deleted": True}

    @app.post("/api/use-cases/{identifier}/runs")
    @app.post(prefix + "/{identifier}/runs")
    def run(
        identifier: str, body: RunInput, auth: Auth, project_id: str | None = None
    ) -> dict[str, Any]:
        with factory() as db:
            ownership_lock(db)
            row = case(db, project_id, identifier)
            if row.project_id is not None:
                project(db, row.project_id, True)
            try:
                request_digest = digest(
                    encode({"revision": body.expected_revision, "values": body.values})
                )
            except (ValueError, UnicodeEncodeError):
                raise HTTPException(422, "Eingaben enthalten ungültige Werte") from None
            replay = db.scalar(
                select(UseCaseRun).where(
                    UseCaseRun.use_case_id == identifier,
                    UseCaseRun.request_id == str(body.request_id),
                )
            )
            if replay:
                if replay.request_digest != request_digest:
                    raise HTTPException(409, "Anfragekennung gehört zu anderen Eingaben")
                return run_info(replay)
            if body.expected_revision != row.revision:
                raise HTTPException(409, "Use Case inzwischen geändert")
            if (
                db.scalar(
                    select(func.count())
                    .select_from(UseCaseRun)
                    .where(UseCaseRun.use_case_id == row.id)
                )
                >= 1000
            ):
                raise HTTPException(413, "Maximal 1000 Eingaben pro Use Case")
            spec = Definition.model_validate_json(
                db.get(UseCaseRevision, (row.id, row.revision)).spec
            )
            values = validated_values(spec, body.values)
            snapshot = {
                "spec": spec.model_dump(),
                "values": values,
                "output": result_for(spec, values),
            }
            item = UseCaseRun(
                use_case_id=row.id,
                revision=row.revision,
                request_id=str(body.request_id),
                request_digest=request_digest,
                snapshot=encode(snapshot),
                created=time.time(),
            )
            db.add(item)
            db.flush()
            answer = run_info(item)
            db.commit()
            return answer

    def run_info(row: UseCaseRun) -> dict[str, Any]:
        return {
            "id": row.id,
            "revision": row.revision,
            "created": float(row.created),
            "status": "succeeded",
            "processing": "local_form",
            **json.loads(row.snapshot),
        }

    @app.get("/api/use-cases/{identifier}/runs")
    @app.get(prefix + "/{identifier}/runs")
    def runs(identifier: str, auth: Auth, project_id: str | None = None) -> list[dict[str, Any]]:
        with factory() as db:
            if project_id is not None:
                project(db, project_id)
            query = (
                select(UseCase, UseCaseRun)
                .outerjoin(UseCaseRun, UseCaseRun.use_case_id == UseCase.id)
                .where(UseCase.id == identifier)
            )
            if project_id is not None:
                query = query.where(UseCase.project_id == project_id)
            rows = list(db.execute(query.order_by(UseCaseRun.created.desc()).limit(200)))
            if not rows:
                raise HTTPException(404, "Use Case nicht gefunden")
            return [run_info(item) for _, item in rows if item is not None]

    @app.get("/api/use-cases/{identifier}/runs/{run_id}")
    @app.get(prefix + "/{identifier}/runs/{run_id}")
    def run_detail(
        identifier: str, run_id: str, auth: Auth, project_id: str | None = None
    ) -> dict[str, Any]:
        with factory() as db:
            if project_id is not None:
                project(db, project_id)
            query = (
                select(UseCaseRun)
                .join(UseCase, UseCase.id == UseCaseRun.use_case_id)
                .where(UseCase.id == identifier, UseCaseRun.id == run_id)
            )
            if project_id is not None:
                query = query.where(UseCase.project_id == project_id)
            row = db.scalar(query)
            if row is None:
                raise HTTPException(404, "Eingabe nicht gefunden")
            return run_info(row)

    def export_data(
        db: Any, project_id: str | None, identifier: str
    ) -> tuple[list[str], list[list[Any]]]:
        if project_id is not None:
            project(db, project_id)
        query = (
            current_query(project_id)
            .add_columns(UseCaseRun)
            .outerjoin(
                UseCaseRun,
                (UseCaseRun.use_case_id == UseCase.id) & (UseCaseRun.revision == UseCase.revision),
            )
            .where(UseCase.id == identifier)
            .order_by(UseCaseRun.created)
            .limit(1001)
        )
        records = list(db.execute(query))
        if not records:
            raise HTTPException(404, "Use Case nicht gefunden")
        row, revision, _ = records[0]
        definition = loaded_info(db, row, revision)
        spec = Definition.model_validate(definition["spec"])
        rows = [item for _, _, item in records if item is not None]
        if len(rows) > 1000:
            raise HTTPException(413, "Exportlimit von 1000 Eingaben erreicht")
        if sum(len(r.snapshot.encode()) for r in rows) > 8_000_000:
            raise HTTPException(413, "Export überschreitet das Größenlimit von 8 MB")
        return [c.label for c in spec.output_columns], [
            json.loads(r.snapshot)["output"]["row"] for r in rows
        ]

    @app.get("/api/use-cases/{identifier}/output.csv")
    @app.get(prefix + "/{identifier}/output.csv")
    def export_csv(identifier: str, auth: Auth, project_id: str | None = None) -> Response:
        with factory() as db:
            columns, rows = export_data(db, project_id, identifier)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter=";")

        def safe(v: Any) -> Any:
            return (
                "'" + v
                if isinstance(v, str)
                and (
                    v.startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
                    or v.lstrip().startswith(("=", "+", "-", "@"))
                )
                else v
            )

        writer.writerows([[safe(v) for v in row] for row in [columns, *rows]])
        return Response(
            "\ufeff" + stream.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="use-case.csv"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/use-cases/{identifier}/output.xlsx")
    @app.get(prefix + "/{identifier}/output.xlsx")
    def export_xlsx(identifier: str, auth: Auth, project_id: str | None = None) -> Response:
        from openpyxl import Workbook  # type: ignore[import-untyped]

        with factory() as db:
            columns, rows = export_data(db, project_id, identifier)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Ergebnisse"
        for row in [columns, *rows]:
            sheet.append(row)
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        output = io.BytesIO()
        workbook.save(output)
        return Response(
            output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": 'attachment; filename="use-case.xlsx"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/use-cases/{identifier}")
    def detail(identifier: str, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            record = db.execute(current_query().where(UseCase.id == identifier)).first()
            if record is None:
                raise HTTPException(404, "Use Case nicht gefunden")
            row, revision = record
            return loaded_info(db, row, revision)
