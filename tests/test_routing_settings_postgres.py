"""0029 upgrade and CAS row are exercised in an isolated disposable PostgreSQL schema."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from hub.db import RoutingSettings
from hub.routing_settings import read_options
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable loopback PG required")
def test_routing_settings_migration_actual_postgres(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci is allowed")
    engine = create_engine(url)
    schema = "routing_settings_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        spec = importlib.util.spec_from_file_location(
            "routing_settings_migration", Path("migrations/versions/0029_routing_settings.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
            connection.execute(text("CREATE TABLE runs (id text PRIMARY KEY, content text)"))
            connection.execute(text("INSERT INTO runs VALUES ('original', 'PRESERVED')"))
            module.upgrade()
            assert connection.execute(text(
                "SELECT content, routing_trace FROM runs WHERE id = 'original'"
            )).one() == ("PRESERVED", "{}")
            factory = sessionmaker(connection, expire_on_commit=False)
            with factory() as db:
                assert read_options(db) == {
                    "revision": 0,
                    "strategy": "balanced",
                    "complex_research_cloud": True,
                }
                row = db.get(RoutingSettings, 1)
                row.revision = 1
                row.strategy = "cloud_first"
                db.flush()
                assert read_options(db)["strategy"] == "cloud_first"
                with pytest.raises(RuntimeError, match="Preserve"):
                    module.downgrade()
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
