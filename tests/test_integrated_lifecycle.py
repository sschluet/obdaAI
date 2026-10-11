"""New scoped definitions and selections participate in confirmed project deletion."""

import uuid

from hub.integrations import Integration, IntegrationBinding
from hub.use_cases import UseCase, UseCaseRevision, UseCaseRun
from sqlalchemy import func, select
from test_actions import gateway  # noqa: F401
from use_case_legacy_fixture import legacy


def test_project_deletion_cas_covers_cases_runs_and_bindings(gateway):  # noqa: F811
    app, client, headers, _ = gateway
    project = client.post("/api/projects", headers=headers, json={"name": "Owned lifecycle"}).json()
    root = "/api/projects/" + project["id"]
    spec = {
        "name": "Owned values",
        "fields": [{"key": "amount", "label": "Amount", "type": "number"}],
        "output_columns": [{"label": "Amount", "source": "amount"}],
    }
    created = legacy(app, spec, project["id"])
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    first = client.get(root + "/deletion").json()
    run = client.post(
        root + "/use-cases/" + case_id + "/runs",
        headers=headers,
        json={"expected_revision": 1, "request_id": str(uuid.uuid4()), "values": {"amount": 12.5}},
    )
    assert run.status_code == 200, run.text
    assert (
        client.request(
            "DELETE", root, headers=headers, json={"expected_state": first["expected_state"]}
        ).status_code
        == 409
    )
    second = client.get(root + "/deletion").json()
    integration = client.post(
        "/api/integrations",
        headers=headers,
        json={
            "name": "Owned draft",
            "kind": "mcp",
            "url": "https://example.org/mcp",
            "auth": "none",
        },
    ).json()
    binding = client.put(
        "/api/integration-bindings/project/" + project["id"],
        headers=headers,
        json={
            "expected_revision": 0,
            "integration_ids": [integration["id"]],
            "selection_mode": "manual",
        },
    )
    assert binding.status_code == 200, binding.text
    assert (
        client.request(
            "DELETE", root, headers=headers, json={"expected_state": second["expected_state"]}
        ).status_code
        == 409
    )
    third = client.get(root + "/deletion").json()
    assert third["counts"]["use_cases"] == third["counts"]["use_case_runs"] == 1
    assert third["counts"]["integration_bindings"] == 1
    deleted = client.request(
        "DELETE", root, headers=headers, json={"expected_state": third["expected_state"]}
    )
    assert deleted.status_code == 200, deleted.text
    with app.state.sessions() as db:
        for model in (UseCase, UseCaseRun, UseCaseRevision, IntegrationBinding):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.get(Integration, integration["id"]) is not None
    assert client.get(root + "/use-cases").status_code == 404


def test_detach_invalidates_project_delete_witness_and_preserves_standalone_runs(gateway):  # noqa: F811
    app, client, headers, _ = gateway
    project = client.post("/api/projects", headers=headers, json={"name": "Optional owner"}).json()
    root = "/api/projects/" + project["id"]
    definition = {
        "name": "Keep my result",
        "fields": [{"key": "amount", "label": "Amount", "type": "number"}],
        "output_columns": [{"label": "Amount", "source": "amount"}],
    }
    bound = legacy(app, definition, project["id"]).json()
    url = "/api/use-cases/" + bound["id"]
    run = client.post(
        url + "/runs",
        headers=headers,
        json={"expected_revision": 1, "request_id": str(uuid.uuid4()), "values": {"amount": 42}},
    ).json()
    before = client.get(root + "/deletion").json()
    assert before["counts"]["use_cases"] == before["counts"]["use_case_runs"] == 1
    detached = client.put(
        url,
        headers=headers,
        json={
            "spec": {
                **definition,
                "execution_kind": "ai",
                "processing_prompt": "Synthetic processing",
            },
            "project_id": None,
            "expected_revision": 1,
        },
    )
    assert detached.status_code == 200, detached.text
    assert (
        client.request(
            "DELETE", root, headers=headers, json={"expected_state": before["expected_state"]}
        ).status_code
        == 409
    )
    after = client.get(root + "/deletion").json()
    assert after["counts"]["use_cases"] == after["counts"]["use_case_runs"] == 0
    assert (
        client.request(
            "DELETE", root, headers=headers, json={"expected_state": after["expected_state"]}
        ).status_code
        == 200
    )
    assert client.get(url).json()["project_id"] is None
    assert client.get(url + "/runs/" + run["id"]).json()["output"]["row"] == [42]
    # A deleted project cannot be rebound to, and a failed edit preserves the new owner/revision.
    rejected = client.put(
        url,
        headers=headers,
        json={
            "spec": {
                **definition,
                "execution_kind": "ai",
                "processing_prompt": "Synthetic processing",
            },
            "project_id": project["id"],
            "expected_revision": 2,
        },
    )
    assert rejected.status_code == 404
    assert client.get(url).json()["revision"] == 2
