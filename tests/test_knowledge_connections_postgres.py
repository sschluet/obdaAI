"""Real PostgreSQL knowledge reader: fixed view, readonly transaction, bounded rows."""

import os
import uuid

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from hub.knowledge_clients import ConnectionInput, sql_documents
from sqlalchemy.engine import make_url


@pytest.mark.skipif(not os.getenv("HUB_CI_DATABASE_URL"), reason="Disposable PG fixture required")
def test_actual_knowledge_view_is_readonly_and_bounded(monkeypatch):
    url = make_url(os.environ["HUB_CI_DATABASE_URL"])
    assert url.host == "127.0.0.1" and url.database == "hub_ci"
    monkeypatch.setenv("HUB_DATABASE_URL", os.environ["HUB_CI_DATABASE_URL"])
    command.upgrade(Config("alembic.ini"), "head")
    view = "knowledge_fixture_" + uuid.uuid4().hex
    args = {
        "host": url.host,
        "port": url.port or 5432,
        "dbname": url.database,
        "user": url.username,
        "password": url.password,
    }
    with psycopg.connect(**args, autocommit=True) as db:
        db.execute(
            psycopg.sql.SQL(
                "CREATE VIEW {} AS SELECT 'synthetic' AS value, "
                "current_setting('transaction_read_only') AS readonly, "
                "generate_series(1,5) AS row"
            ).format(psycopg.sql.Identifier(view))
        )
    try:

        def fixture_host(host, port):
            assert host == "127.0.0.1" and port == (url.port or 5432)
            return host

        monkeypatch.setattr("hub.knowledge_clients.resolve_host", fixture_host)
        body = ConnectionInput(
            name="Own disposable PG view",
            kind="sql",
            server="127.0.0.1",
            database="hub_ci",
            username=url.username,
            table=view,
            port=url.port or 5432,
            tls=False,
            max_rows=2,
        )
        docs = list(sql_documents(body, url.password or "", False))
        assert len(docs) == 1 and docs[0].content.count(b'"readonly":"on"') == 2
        assert b'"row":3' not in docs[0].content
        assert list(sql_documents(body, url.password or "", True))[0].content == b""
    finally:
        with psycopg.connect(**args, autocommit=True) as db:
            db.execute(psycopg.sql.SQL("DROP VIEW {}").format(psycopg.sql.Identifier(view)))
