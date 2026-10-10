"""Actual 0030 migration in an isolated disposable PostgreSQL schema."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from hub.db import PersonalProfile
from hub.personal_profile import read_profile
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable loopback PG required")
def test_personal_profile_migration_actual_postgres(monkeypatch):
    url = os.environ["HUB_CI_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or parsed.database != "hub_ci":
        pytest.fail("Only disposable loopback hub_ci is allowed")
    engine = create_engine(url)
    schema = "personal_profile_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        spec = importlib.util.spec_from_file_location(
            "personal_profile_migration", Path("migrations/versions/0030_personal_profile.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
            connection.execute(text("CREATE TABLE originals (id text PRIMARY KEY, content text)"))
            connection.execute(text("INSERT INTO originals VALUES ('original', 'PRESERVED')"))
            module.upgrade()
            assert connection.scalar(text("SELECT content FROM originals")) == "PRESERVED"
            factory = sessionmaker(connection, expire_on_commit=False)
            with factory() as db:
                original = read_profile(db)
                assert original["revision"] == 0 and not original["enabled"]
                assert original["cloud_fields"] == []
                assert all(v == "" for v in original["fields"].values())
                row = db.get(PersonalProfile, 1)
                row.revision = 1
                row.fields = '{"name":"Synthetic Person"}'
                db.flush()
                assert read_profile(db)["fields"]["name"] == "Synthetic Person"
                with pytest.raises(RuntimeError, match="Preserve"):
                    module.downgrade()
                row.revision, row.fields = 0, "{}"
                db.flush()
            module.downgrade()
            assert connection.scalar(text("SELECT content FROM originals")) == "PRESERVED"
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
