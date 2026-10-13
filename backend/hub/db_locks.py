"""Stable global transaction-lock namespace; never reuse a key across resources.

42 source storage; 43 memory index; 44 skills; 45 tasks; 46 task execution
(two-key session locks); 47 artifact storage. 50 integration registry; 51 appearance preferences.
Keep deployed identifiers stable.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

MEMORY_INDEX = 791103043
ARTIFACT_STORAGE = 791103047
OWNERSHIP = 791103049


def ownership_lock(db: Session) -> None:
    """Serialize scoped mutations before subsystem locks and existence checks."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": OWNERSHIP})
