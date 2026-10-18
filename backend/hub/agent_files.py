"""Only explicitly authorized originals already bound to the current local context."""

import json
from pathlib import Path
from typing import Any

from hub.db import Source
from hub.knowledge import original


def bound_sources(db: Any, job: Any) -> list[Source]:
    result: dict[str, Source] = {}
    for part in json.loads(job.context):
        source = db.get(Source, part["source_id"])
        if source and source.revision == part["revision"] and source.status == "ready":
            result[source.id] = source
    return list(result.values())


def check(db: Any, job: Any, args: dict[str, Any]) -> Source:
    source = next((s for s in bound_sources(db, job) if s.id == args["source_id"]), None)
    if (
        not source
        or source.revision != args["source_revision"]
        or source.sha256 != args["source_sha256"]
    ):
        raise PermissionError("Originaldatei ist nicht aktuell an diesen Auftrag gebunden")
    if source.size > 20_000_000:
        raise ValueError("Originaldatei überschreitet das Transferlimit")
    return source


def payload(db: Any, cfg: Any, job: Any, args: dict[str, Any]) -> tuple[str, str, bytes]:
    source = check(db, job, args)
    data = original(cfg, source).read_bytes()
    if len(data) != source.size or len(data) > 20_000_000:
        raise ValueError("Originaldatei wurde verändert")
    filename = Path(source.name).name[:200]
    if not filename or any(ord(c) < 32 for c in filename):
        raise ValueError("Ungültiger Originaldateiname")
    return args["form_field"], filename, data
