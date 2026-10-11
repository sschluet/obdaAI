"""Use-case dispatch and result lifecycle on real disposable PostgreSQL transactions."""

import asyncio
import os
from uuid import uuid4

import pytest
from hub.config import Settings
from hub.db import Conversation, Run, session_factory
from hub.execution import execute_run
from hub.use_case_ai import ai_run_info, cleanup_case_ai, create_ai_run
from hub.use_cases import Definition, RunInput, UseCase, UseCaseRevision, digest, encode
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from test_use_case_ai import Model, ai_spec


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable loopback PG required")
def test_ai_queue_is_atomic_idempotent_and_executes_actual_run_pipeline():
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci is allowed")
    cfg = Settings(database_url=url)
    factory = session_factory(url)
    case_id = None
    run_id = None
    try:
        with factory() as db:
            case = UseCase(project_id=None)
            db.add(case)
            db.flush()
            case_id = case.id
            spec = encode(Definition.model_validate(ai_spec()).model_dump())
            db.add(UseCaseRevision(use_case_id=case.id, revision=1, spec=spec, sha256=digest(spec)))
            db.commit()
        body = RunInput(
            request_id=uuid4(), expected_revision=1, values={"goal": "Synthetic PG concept"}
        )
        with factory() as db:
            answer = create_ai_run(db, cfg, db.get(UseCase, case_id), body)
            rolled_id = answer["execution_run_id"]
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM hub_queue.procrastinate_jobs "
                        "WHERE args->>'run_id'=:id"
                    ),
                    {"id": rolled_id},
                )
                == 1
            )
            db.rollback()
            assert db.get(Run, rolled_id) is None
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM hub_queue.procrastinate_jobs "
                        "WHERE args->>'run_id'=:id"
                    ),
                    {"id": rolled_id},
                )
                == 0
            )
        with factory() as db:
            answer = create_ai_run(db, cfg, db.get(UseCase, case_id), body)
            run_id = answer["execution_run_id"]
            result_id = answer["id"]
            db.commit()
        with factory() as db:
            replay = create_ai_run(db, cfg, db.get(UseCase, case_id), body)
            assert replay["id"] == result_id
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM hub_queue.procrastinate_jobs "
                        "WHERE args->>'run_id'=:id"
                    ),
                    {"id": run_id},
                )
                == 1
            )
            db.rollback()
        model = Model(["Synthetic real PG workflow result"])
        asyncio.run(execute_run(factory, cfg, model, run_id))
        asyncio.run(execute_run(factory, cfg, model, run_id))
        assert len(model.calls) == 1
        with factory() as db:
            from hub.use_cases import UseCaseRun

            result = ai_run_info(db, db.get(UseCaseRun, result_id))
            assert result["status"] == "succeeded"
            assert result["output"]["text"] == "Synthetic real PG workflow result"
            assert db.get(Conversation, db.get(Run, run_id).conversation_id).purpose == "use_case"
    finally:
        if case_id:
            with factory() as db:
                if run_id:
                    db.execute(
                        text("DELETE FROM hub_queue.procrastinate_jobs WHERE args->>'run_id'=:id"),
                        {"id": run_id},
                    )
                # Test failures preserve no running fixture job.
                for run in db.scalars(select(Run).where(Run.context_snapshot.contains(case_id))):
                    run.status = (
                        "interrupted"
                        if run.status in {"queued", "routing", "streaming"}
                        else run.status
                    )
                db.flush()
                cleanup_case_ai(db, cfg, case_id)
                db.execute(delete(UseCaseRevision).where(UseCaseRevision.use_case_id == case_id))
                db.execute(delete(UseCase).where(UseCase.id == case_id))
                db.commit()
        factory.kw["bind"].dispose()
