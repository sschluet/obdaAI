"""New scoped definitions and selections participate in confirmed project deletion."""

import uuid

from hub.integrations import Integration, IntegrationBinding
from hub.use_cases import UseCase, UseCaseRevision, UseCaseRun
from sqlalchemy import func, select
from test_actions import gateway  # noqa: F401


def test_project_deletion_cas_covers_cases_runs_and_bindings(gateway):  # noqa: F811
    app, client, headers, _ = gateway
    project = client.post("/api/projects", headers=headers, json={"name": "Owned lifecycle"}).json()
    root = "/api/projects/" + project["id"]
    spec = {
        "name": "Owned values",
        "fields": [{"key": "amount", "label": "Amount", "type": "number"}],
        "output_columns": [{"label": "Amount", "source": "amount"}],
    }
    created = client.post(root + "/use-cases", headers=headers, json={"spec": spec})
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
