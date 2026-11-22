"""Probe-role migration preserves historical test evidence and guards lossy downgrade."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_probe_role_additive_migration_and_loss_guard(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "probe.sqlite")
    monkeypatch.setenv("HUB_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "0048")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO provider_tests "
                "(id,provider_id,revision,status,result,created) "
                "VALUES ('old','local',7,'succeeded','PRESERVE EXACT EVIDENCE',0)"
            )
        )
    command.upgrade(Config("alembic.ini"), "0049")
    with engine.begin() as db:
        assert db.execute(text("SELECT mode,result,revision FROM provider_tests")).one() == (
            "model",
            "PRESERVE EXACT EVIDENCE",
            7,
        )
        db.execute(
            text(
                "INSERT INTO provider_tests "
                "(id,provider_id,revision,status,result,created,mode) "
                "VALUES ('new','local',7,'succeeded','SYNTHETIC PLANNER',1,'planner')"
            )
        )
    import pytest

    with pytest.raises(RuntimeError, match="preserve"):
        command.downgrade(Config("alembic.ini"), "0048")
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM provider_tests")) == 2
        assert db.scalar(text("SELECT result FROM provider_tests WHERE id='old'")) == (
            "PRESERVE EXACT EVIDENCE"
        )
    engine.dispose()
