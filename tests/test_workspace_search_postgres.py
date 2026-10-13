"""Actual SQL execution in an isolated schema, only on disposable loopback CI PG."""

import os
import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hub.auth import token_hash
from hub.db import (
    Artifact,
    ArtifactRevision,
    Base,
    Conversation,
    KnowledgeConnection,
    LoginSession,
    Message,
    Project,
    Run,
    Source,
    Task,
    TaskRevision,
)
from hub.workspace_search import install_workspace_search
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema
from test_workspace_search import seed


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable loopback PG required")
def test_workspace_search_actual_postgres():
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci is allowed")
    engine = create_engine(url)
    schema = "workspace_search_" + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        models = [
            LoginSession,
            Conversation,
            Message,
            Run,
            Project,
            Source,
            Artifact,
            ArtifactRevision,
            Task,
            TaskRevision,
            KnowledgeConnection,
        ]
        Base.metadata.create_all(isolated, tables=[model.__table__ for model in models])
        factory = sessionmaker(isolated, expire_on_commit=False)
        app = FastAPI()
        app.state.sessions = factory
        install_workspace_search(app, factory)
        seed(app)
        token = "synthetic-pg-search-session"
        with factory() as db:
            db.add(
                LoginSession(
                    token_hash=token_hash(token), csrf="synthetic", expires=time.time() + 300
                )
            )
            db.add(Conversation(title="ÄÖ %_ literal\\x"))
            db.commit()
        with TestClient(app) as client:
            client.cookies.set("hub_session", token)
            response = client.get("/api/workspace/search", params={"q": "Aurora"})
            assert response.status_code == 200, response.text
            results = response.json()["results"]
            assert {item["kind"] for item in results} == {
                "conversation",
                "project",
                "source",
                "artifact",
                "task",
                "knowledge",
            }
            assert next(item for item in results if item["kind"] == "task")["title"] == "Review"
            assert (
                next(item for item in results if item["kind"] == "artifact")["title"]
                == "Aurora report"
            )
            for query in ("äö", "%_", r"\x"):
                found = client.get("/api/workspace/search", params={"q": query}).json()["results"]
                assert [item["title"] for item in found] == ["ÄÖ %_ literal\\x"]
            for query in ("hiddenmarker", "obsoletephrase", "privatehidden"):
                assert (
                    client.get("/api/workspace/search", params={"q": query}).json()["results"] == []
                )
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
