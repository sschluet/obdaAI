"""Task scheduling dispatches the same administration loop used by chat/projects."""

import json
from typing import Any

from sqlalchemy import select

from hub.action_api import digest, encode
from hub.agent_models import AgentJob
from hub.agent_runtime import create_job, execute_agent
from hub.db import Conversation, TaskRun
from hub.db_locks import ownership_lock
from hub.policy import ContextPart
from hub.task_api import AgentTaskStep, check_bindings, check_schedule, current


async def execute_agent_task(factory: Any, cfg: Any, run_id: str, providers: Any = None) -> None:
    with factory() as db:
        ownership_lock(db)
        run = db.get(TaskRun, run_id)
        if not run or run.status not in {"queued", "running"}:
            return
        old = db.scalar(select(AgentJob).where(AgentJob.task_run_id == run_id))
        if old:
            job_id = old.id
        else:
            check_schedule(db, run)
            task, revision, spec = current(db, run.task_id)
            if (
                task.paused
                or task.archived
                or task.revision != run.task_revision
                or (
                    task.control_revision != run.control_revision
                    or digest(encode(json.loads(run.snapshot)["spec"])) != revision.sha256
                    or json.loads(run.snapshot) != check_bindings(db, spec)
                )
            ):
                raise ValueError("Agent task or its context changed")
            step = spec.steps[0]
            if not isinstance(step, AgentTaskStep):
                raise ValueError("Not an agent task")
            conversation = Conversation(
                purpose="agent_task",
                title=spec.title,
                manual_title=True,
                project_id=str(spec.project_id) if spec.project_id else None,
                cloud_allowed=False,
            )
            db.add(conversation)
            db.flush()
            from hub.memory_task_context import assemble_task_context

            context = [
                part.model_dump(mode="json")
                for part in assemble_task_context(
                    db,
                    cfg,
                    spec.goal,
                    str(spec.project_id) if spec.project_id else None,
                    spec.sources,
                )
            ]
            for skill in json.loads(run.snapshot).get("skills_checked", []):
                context.append(
                    ContextPart(
                        content=skill["document"],
                        source_id="task-skill",
                        revision=skill["revision"],
                    ).model_dump(mode="json")
                )
            job = create_job(
                db,
                cfg,
                scope="task",
                owner_id=task.id,
                conversation_id=conversation.id,
                request_id=run.request_key,
                goal=spec.goal,
                research_allowed=step.parameters.research_allowed,
                task_run=run,
                context=context,
            )
            bindings = json.loads(job.bindings)
            bindings["autonomy_allowed"] = spec.autonomy == "bounded_autonomous"
            job.bindings = encode(bindings)
            job.timeout_seconds = min(job.timeout_seconds, spec.timeout_seconds)
            job_id, run.status = job.id, "running"
            db.commit()
    if providers is None:
        from hub.providers import Providers

        providers = Providers(cfg)
    await execute_agent(factory, cfg, providers, job_id)
