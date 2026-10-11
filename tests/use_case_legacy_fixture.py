"""Seed pre-AI immutable definitions; public creation now requires a processing prompt."""

import httpx
from hub.use_cases import UseCase, UseCaseRevision, digest, encode


def legacy(app, spec, project_id=None):
    with app.state.sessions() as db:
        row = UseCase(project_id=project_id)
        db.add(row)
        db.flush()
        document = encode(spec)
        db.add(
            UseCaseRevision(use_case_id=row.id, revision=1, spec=document, sha256=digest(document))
        )
        result = {
            "id": row.id,
            "revision": 1,
            "project_id": project_id,
            "spec": spec,
            "label": "LOCAL_ONLY",
        }
        db.commit()
    return httpx.Response(200, json=result)
