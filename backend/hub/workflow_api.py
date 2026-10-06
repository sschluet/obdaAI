"""Bound n8n invocation and durable callback receipts; no task content in n8n."""

import asyncio
import hmac
import ipaddress
import json
import secrets
import time
from typing import Any
from uuid import UUID

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hub.action_api import StrictInput, digest, encode
from hub.config import Settings, read_secret
from hub.db import TaskRun, WorkflowBinding, WorkflowDispatch, new_id
from hub.knowledge_api import Auth
from hub.n8n_check import CheckError
from hub.n8n_workflows import task_workflow, verify_workflow
from hub.provider_settings import decrypt, encrypt
from hub.task_api import RunInput, check_bindings, current, lock


class Review(StrictInput):
    expected_revision: int = Field(ge=1)
    expected_control_revision: int = Field(ge=1)
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Register(Review):
    workflow_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    workflow_version: UUID
    header_credential_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    ca_credential_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


class Callback(StrictInput):
    dispatch_id: UUID
    execution_id: str = Field(pattern=r"^[0-9]{1,32}$")


def remote(
    cfg: Settings, path: str, *, token: str | None = None, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not cfg.n8n_allowed_ip:
        raise HTTPException(503, "n8n-Aufgabenverbindung noch nicht eingerichtet")
    address = ipaddress.ip_address(cfg.n8n_allowed_ip)
    if not address.is_global or address.version != 4:
        raise HTTPException(503, "n8n-Ziel nicht freigegeben")
    base = "https://" + str(address)
    # Callers construct only fixed API paths or UUID webhook paths.
    headers = {"Host": "n8n.schlueterbusch.de", "Accept-Encoding": "identity"}
    if token is None:
        headers["X-N8N-API-KEY"] = read_secret(cfg.n8n_api_key_file)
    else:
        headers["X-OBDAAI-WORKFLOW"] = token
    deadline = time.monotonic() + 20
    with httpx.Client(verify=True, trust_env=False, follow_redirects=False, timeout=12) as client:
        with client.stream(
            "GET" if payload is None else "POST",
            base + path,
            headers=headers,
            json=payload,
            extensions={"sni_hostname": "n8n.schlueterbusch.de"},
        ) as response:
            if response.status_code != 200:
                raise CheckError("n8n request failed; reconcile before retry")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise CheckError("Compressed n8n response rejected")
            data = bytearray()
            for chunk in response.iter_bytes(chunk_size=65536):
                data.extend(chunk)
                if len(data) > 1_000_000 or time.monotonic() > deadline:
                    raise CheckError("n8n response exceeds limit")
            try:
                value = json.loads(data)
            except (ValueError, RecursionError):
                raise CheckError("Invalid n8n response") from None
            if not isinstance(value, dict):
                raise CheckError("n8n response schema failed")
            return value


def install_workflow_api(app: FastAPI, cfg: Settings, factory: sessionmaker[Session]) -> None:
    def public(db: Session, binding: WorkflowBinding) -> dict[str, Any]:
        from hub.db import TaskRevision
        from hub.task_pipeline import plan

        revision = db.get(TaskRevision, (binding.task_id, binding.task_revision))
        from hub.task_api import TaskSpec

        pipeline = plan(TaskSpec.model_validate_json(revision.spec)) if revision else None
        return {
            "id": binding.id,
            "task_id": binding.task_id,
            "task_revision": binding.task_revision,
            "status": binding.status,
            "workflow_id": binding.remote_id,
            "workflow_version": binding.remote_version,
            "label": "LOCAL_ONLY",
            "contains_private_context": False,
            "pipeline": pipeline,
            "dispatches": [
                {
                    "id": d.id,
                    "status": d.status,
                    "run_id": d.run_id,
                    "execution_id": d.execution_id,
                    "created": d.created,
                }
                for d in db.scalars(
                    select(WorkflowDispatch)
                    .where(WorkflowDispatch.binding_id == binding.id)
                    .order_by(WorkflowDispatch.created.desc())
                    .limit(50)
                )
            ],
        }

    def bound(db: Session, binding_id: str) -> WorkflowBinding:
        b = db.get(WorkflowBinding, binding_id)
        if not b:
            raise HTTPException(404, "Workflowbindung fehlt")
        return b

    def review(db: Session, task_id: str, body: Review) -> Any:
        task, rev, spec = current(db, task_id)
        if (
            task.archived
            or task.revision != body.expected_revision
            or task.control_revision != body.expected_control_revision
            or rev.sha256 != body.spec_sha256
        ):
            raise HTTPException(409, "Aufgabe inzwischen geändert oder archiviert")
        check_bindings(db, spec)
        return task, rev, spec

    @app.get("/api/tasks/{task_id}/workflows")
    def listing(task_id: str, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            current(db, task_id)
            return {
                "configured": bool(cfg.n8n_allowed_ip and cfg.n8n_api_key_file),
                "bindings": [
                    public(db, b)
                    for b in db.scalars(
                        select(WorkflowBinding)
                        .where(WorkflowBinding.task_id == task_id)
                        .order_by(WorkflowBinding.created)
                    )
                ],
            }

    @app.post("/api/tasks/{task_id}/workflows")
    def prepare(task_id: str, body: Review, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            task, rev, _ = review(db, task_id, body)
            b = db.scalar(
                select(WorkflowBinding).where(
                    WorkflowBinding.task_id == task_id,
                    WorkflowBinding.task_revision == task.revision,
                )
            )
            if not b:
                bid = new_id()
                b = WorkflowBinding(
                    id=bid,
                    task_id=task_id,
                    task_revision=task.revision,
                    control_revision=task.control_revision,
                    spec_sha256=rev.sha256,
                    encrypted_secret=encrypt(cfg, "workflow:" + bid, secrets.token_urlsafe(32)),
                )
                db.add(b)
                db.commit()
            return public(db, b)

    @app.post("/api/workflows/{binding_id}/provisioning")
    def provisioning(binding_id: str, body: Review, auth: Auth) -> dict[str, Any]:
        # Explicit authenticated operator endpoint. Never called by the UI/model.
        with factory() as db:
            b = bound(db, binding_id)
            review(db, b.task_id, body)
            if b.status != "draft" or b.task_revision != body.expected_revision:
                raise HTTPException(409, "Nur unveröffentlichter Entwurf darf eingerichtet werden")
            return {
                "id": b.id,
                "task_id": b.task_id,
                "revision": b.task_revision,
                "credential": {
                    "name": "obdaAI task " + b.id,
                    "type": "httpHeaderAuth",
                    "data": {
                        "name": "X-OBDAAI-WORKFLOW",
                        "value": decrypt(cfg, "workflow:" + b.id, b.encrypted_secret),
                    },
                },
            }

    @app.post("/api/workflows/{binding_id}/register")
    def register(binding_id: str, body: Register, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            b = bound(db, binding_id)
            task_id, revision = b.task_id, b.task_revision
        with factory() as db:
            wait = current(db, task_id)[2].workflow_wait
        graph = task_workflow(
            binding_id,
            task_id,
            revision,
            body.header_credential_id,
            body.ca_credential_id,
            wait_for_completion=wait,
        )
        try:
            actual = remote(cfg, "/api/v1/workflows/" + body.workflow_id)
            verify_workflow(actual, graph, active=False, version=str(body.workflow_version))
        except (CheckError, httpx.HTTPError, ValueError, OSError):
            raise HTTPException(409, "n8n-Entwurf nicht exakt verifiziert") from None
        with factory() as db:
            lock(db)
            b = bound(db, binding_id)
            review(db, b.task_id, body)
            if b.task_revision != body.expected_revision or b.status != "draft":
                raise HTTPException(409, "Workflowbindung inzwischen geändert")
            b.graph, b.remote_id = encode(graph), body.workflow_id
            b.remote_version, b.status = str(body.workflow_version), "verified"
            db.commit()
            return public(db, b)

    @app.post("/api/workflows/{binding_id}/confirm-active")
    def confirm(binding_id: str, body: Review, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            b = bound(db, binding_id)
            if b.status not in ("verified", "ready") or not b.graph or not b.remote_id:
                raise HTTPException(409, "Workflow zuerst einrichten und prüfen")
            graph, remote_id, version = json.loads(b.graph), b.remote_id, b.remote_version
        try:
            actual = remote(cfg, "/api/v1/workflows/" + remote_id)
            verify_workflow(actual, graph, active=True, version=version)
        except (CheckError, httpx.HTTPError, ValueError, OSError):
            raise HTTPException(
                409, "Veröffentlichte n8n-Version nicht exakt verifiziert"
            ) from None
        with factory() as db:
            lock(db)
            b = bound(db, binding_id)
            review(db, b.task_id, body)
            if b.remote_id != remote_id or b.remote_version != version or b.graph != encode(graph):
                raise HTTPException(409, "Workflowbindung inzwischen geändert")
            b.status = "ready"
            db.commit()
            return public(db, b)

    @app.post("/api/workflows/{binding_id}/runs")
    async def dispatch(binding_id: str, body: RunInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            b = bound(db, binding_id)
            existing = db.get(WorkflowDispatch, str(body.request_id))
            if existing:
                if (
                    existing.binding_id != b.id
                    or existing.control_revision != body.expected_control_revision
                    or body.expected_revision != b.task_revision
                    or body.spec_sha256 != b.spec_sha256
                ):
                    raise HTTPException(409, "Anfrage-ID bereits anders gebunden")
                return public(db, b)
            task, rev, _ = review(db, b.task_id, Review(**body.model_dump(exclude={"request_id"})))
            if (
                task.paused
                or b.status != "ready"
                or b.task_revision != task.revision
                or b.spec_sha256 != rev.sha256
                or not b.graph
                or not b.remote_id
            ):
                raise HTTPException(409, "Workflow nicht bereit oder Aufgabe pausiert")
            if db.scalar(
                select(WorkflowDispatch.id).where(
                    WorkflowDispatch.binding_id == b.id,
                    WorkflowDispatch.status.in_(["prepared", "uncertain"]),
                )
            ):
                raise HTTPException(409, "Vorherigen Workflowaufruf zuerst abgleichen")
            if db.scalar(
                select(TaskRun.id).where(
                    TaskRun.task_id == task.id,
                    TaskRun.status.in_(["queued", "running", "awaiting_approval"]),
                )
            ):
                raise HTTPException(409, "Aufgabe läuft bereits")
            if db.scalar(select(TaskRun.id).where(TaskRun.request_key == str(body.request_id))):
                raise HTTPException(409, "Anfrage-ID gehört bereits zu anderem Aufgabenlauf")
            graph, remote_id, version = json.loads(b.graph), b.remote_id, b.remote_version
            token = decrypt(cfg, "workflow:" + b.id, b.encrypted_secret)
        try:
            actual = await asyncio.to_thread(remote, cfg, "/api/v1/workflows/" + remote_id)
            verify_workflow(actual, graph, active=True, version=version)
        except (CheckError, httpx.HTTPError, ValueError, OSError):
            raise HTTPException(
                409, "Workflowdrift oder n8n nicht erreichbar; kein Start"
            ) from None
        with factory() as db:
            lock(db)
            b = bound(db, binding_id)
            task, _, _ = review(db, b.task_id, Review(**body.model_dump(exclude={"request_id"})))
            if task.paused or b.status != "ready" or b.graph != encode(graph):
                raise HTTPException(409, "Aufgabe/Workflow während Prüfung geändert")
            if db.get(WorkflowDispatch, str(body.request_id)):
                return public(db, b)
            if db.scalar(
                select(WorkflowDispatch.id).where(
                    WorkflowDispatch.binding_id == b.id,
                    WorkflowDispatch.status.in_(["prepared", "uncertain"]),
                )
            ):
                raise HTTPException(409, "Workflowaufruf bereits offen")
            d = WorkflowDispatch(
                id=str(body.request_id), binding_id=b.id, control_revision=task.control_revision
            )
            db.add(d)
            db.commit()  # Intent precedes the only external POST.
        remote_result = None
        try:
            remote_result = await asyncio.to_thread(
                remote,
                cfg,
                "/webhook/obdaai-" + binding_id,
                token=token,
                payload={"dispatch_id": str(body.request_id)},
            )
        except (CheckError, httpx.HTTPError, ValueError, OSError):
            pass  # Never repeat POST. Only the durable callback can establish success.
        with factory() as db:
            lock(db)
            final_dispatch = db.get(WorkflowDispatch, str(body.request_id))
            assert final_dispatch is not None
            if final_dispatch.status == "prepared":
                final_dispatch.status = "uncertain"
            elif (
                final_dispatch.status == "accepted"
                and remote_result
                and (
                    remote_result.get("dispatch_id") == final_dispatch.id
                    and remote_result.get("run_id") == final_dispatch.run_id
                    and remote_result.get("execution_id") == final_dispatch.execution_id
                    and remote_result.get("complete") is True
                    and remote_result.get("succeeded") is True
                )
            ):
                completed = db.get(TaskRun, final_dispatch.run_id)
                waiting = current(db, bound(db, binding_id).task_id)[2].workflow_wait
                if waiting and completed and completed.status == "succeeded":
                    final_dispatch.status = "completed"
            db.commit()
            return public(db, bound(db, binding_id))

    @app.post("/api/workflow-dispatches/{dispatch_id}/cancel")
    def cancel_dispatch(dispatch_id: str, body: StrictInput, auth: Auth) -> dict[str, Any]:
        with factory() as db:
            lock(db)
            d = db.get(WorkflowDispatch, dispatch_id)
            if not d:
                raise HTTPException(404, "Workflowauftrag fehlt")
            if d.run_id:
                raise HTTPException(409, "Aufgabenlauf bereits angenommen; dort abbrechen")
            d.status = "cancelled"
            db.commit()
            return public(db, bound(db, d.binding_id))

    @app.post("/api/workflow-status/{binding_id}")
    def workflow_status(
        binding_id: str, body: Callback, x_obdaai_workflow: str = Header(default="", repr=False)
    ) -> dict[str, Any]:
        with factory() as db:
            b = bound(db, binding_id)
            secret = decrypt(cfg, "workflow:" + b.id, b.encrypted_secret)
            if not hmac.compare_digest(x_obdaai_workflow.encode(), secret.encode()):
                raise HTTPException(401, "Workflow-Zugang fehlt")
            d = db.get(WorkflowDispatch, str(body.dispatch_id))
            if not d or d.binding_id != b.id or d.execution_id != body.execution_id or not d.run_id:
                raise HTTPException(409, "Gebundener Ausführungsbeleg fehlt")
            run = db.get(TaskRun, d.run_id)
            task, rev, spec = current(db, b.task_id)
            if (
                not run
                or task.archived
                or task.paused
                or task.revision != b.task_revision
                or (task.control_revision != d.control_revision or rev.sha256 != b.spec_sha256)
            ):
                raise HTTPException(409, "Auftrag pausiert oder geändert")
            # Only operational completion metadata. Never errors, prompt, goal,
            # sources, report contents or condition results in n8n.
            terminal = run.status not in {"queued", "running", "awaiting_approval"}
            return {
                "dispatch_id": d.id,
                "execution_id": d.execution_id,
                "run_id": run.id,
                "complete": terminal,
                "succeeded": run.status == "succeeded",
            }

    @app.post("/api/workflow-callback/{binding_id}")
    async def callback(
        binding_id: str, body: Callback, x_obdaai_workflow: str = Header(default="", repr=False)
    ) -> dict[str, Any]:
        with factory() as lookup:
            binding = bound(lookup, binding_id)
            secret = decrypt(cfg, "workflow:" + binding.id, binding.encrypted_secret)
            if not hmac.compare_digest(x_obdaai_workflow.encode(), secret.encode()):
                raise HTTPException(401, "Workflow-Zugang fehlt")
            previous = lookup.get(WorkflowDispatch, str(body.dispatch_id))
            if not previous or previous.binding_id != binding.id:
                raise HTTPException(404, "Geprüfter Workflowauftrag fehlt")
            if previous.run_id:
                if previous.execution_id != body.execution_id:
                    raise HTTPException(409, "Anderer n8n-Lauf für denselben Auftrag")
                return {
                    "dispatch_id": previous.id,
                    "run_id": previous.run_id,
                    "execution_id": previous.execution_id,
                }
            if (
                previous.status not in ("prepared", "uncertain")
                or binding.status != "ready"
                or not binding.graph
                or not binding.remote_id
            ):
                raise HTTPException(409, "Workflowauftrag nicht mehr ausführbar")
            graph, wid, version = (
                json.loads(binding.graph),
                binding.remote_id,
                binding.remote_version,
            )
        try:
            actual = await asyncio.to_thread(remote, cfg, "/api/v1/workflows/" + wid)
            verify_workflow(actual, graph, active=True, version=version)
        except (CheckError, httpx.HTTPError, ValueError, OSError):
            raise HTTPException(409, "Workflowdrift am Rückruf; keine Ausführung") from None
        with factory() as db:
            lock(db)
            b = bound(db, binding_id)
            secret = decrypt(cfg, "workflow:" + b.id, b.encrypted_secret)
            if not hmac.compare_digest(x_obdaai_workflow.encode(), secret.encode()):
                raise HTTPException(401, "Workflow-Zugang fehlt")
            d = db.get(WorkflowDispatch, str(body.dispatch_id))
            if not d or d.binding_id != b.id:
                raise HTTPException(404, "Geprüfter Workflowauftrag fehlt")
            if d.run_id:
                if d.execution_id != body.execution_id:
                    raise HTTPException(409, "Anderer n8n-Lauf für denselben Auftrag")
                return {"dispatch_id": d.id, "run_id": d.run_id, "execution_id": d.execution_id}
            task, revision, spec = current(db, b.task_id)
            if (
                d.status not in ("prepared", "uncertain")
                or task.paused
                or task.archived
                or b.status != "ready"
                or task.revision != b.task_revision
                or task.control_revision != d.control_revision
                or revision.sha256 != b.spec_sha256
            ):
                raise HTTPException(409, "Auftrag widerrufen, pausiert oder geändert")
            if db.scalar(
                select(TaskRun.id).where(
                    TaskRun.task_id == task.id,
                    TaskRun.status.in_(["queued", "running", "awaiting_approval"]),
                )
            ):
                raise HTTPException(409, "Aufgabe läuft bereits")
            snapshot = check_bindings(db, spec)
            run = TaskRun(
                task_id=task.id,
                task_revision=task.revision,
                control_revision=task.control_revision,
                request_key=d.id,
                request_digest=digest(encode({"binding": b.id, "dispatch": d.id})),
                snapshot=encode(snapshot),
            )
            db.add(run)
            db.flush()
            from hub.task_writes import prepare_run

            prepare_run(db, run, spec)
            if run.status == "queued" and not cfg.database_url.startswith("sqlite"):
                from hub.jobs import enqueue_task_read

                enqueue_task_read(db, cfg, run.id)
            d.run_id, d.execution_id, d.status = run.id, body.execution_id, "accepted"
            db.commit()
            result = {"dispatch_id": d.id, "run_id": run.id, "execution_id": d.execution_id}
        if cfg.database_url.startswith("sqlite"):
            from hub.task_model import execute_task

            job = asyncio.create_task(execute_task(factory, cfg, run.id, app.state.providers))
            app.state.tasks.add(job)
            job.add_done_callback(app.state.tasks.discard)
        return result
