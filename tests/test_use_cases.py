"""Declarative forms are local, validated, revision-bound and safe to export."""

import csv
import io
from uuid import uuid4

import pytest
from hub.use_cases import Definition, validated_values
from openpyxl import load_workbook
from pydantic import ValidationError

pytest_plugins = ["test_knowledge"]


def spec(kind="table"):
    return {
        "name": "Synthetic monthly overview",
        "fields": [
            {"key": "name", "label": "Object", "type": "text"},
            {"key": "amount", "label": "Amount", "type": "number"},
            {"key": "date", "label": "Date", "type": "date", "required": False},
        ],
        "output_kind": kind,
        "output_columns": [
            {"label": "Amount", "source": "amount"},
            {"label": "Object", "source": "name"},
        ],
        "text_template": "Object {name}: {amount}",
    }


def setup(knowledge, kind="table"):
    app, client, headers, cfg, vault = knowledge
    project = client.post("/api/projects", json={"name": "Synthetic forms"}, headers=headers).json()
    base = f"/api/projects/{project['id']}/use-cases"
    created = client.post(base, json={"spec": spec(kind)}, headers=headers)
    assert created.status_code == 200, created.text
    return client, headers, project, base, created.json()


def submit(client, headers, base, case, name="Synthetic", amount=0, request_id=None):
    return client.post(
        base + f"/{case['id']}/runs",
        json={
            "request_id": request_id or str(uuid4()),
            "expected_revision": case["revision"],
            "values": {"name": name, "amount": amount},
        },
        headers=headers,
    )


def test_form_revision_snapshots_and_exact_replay(knowledge):
    client, headers, project, base, case = setup(knowledge, "chat")
    request_id = str(uuid4())
    first = submit(client, headers, base, case, amount=0, request_id=request_id)
    assert first.status_code == 200
    assert first.json()["output"]["text"] == "Object Synthetic: 0"
    assert first.json()["processing"] == "local_form"
    replay = submit(client, headers, base, case, request_id=request_id)
    assert replay.json()["id"] == first.json()["id"]
    assert submit(client, headers, base, case, amount=10, request_id=request_id).status_code == 409
    updated = client.put(
        base + "/" + case["id"], json={"spec": spec("bi"), "expected_revision": 1}, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert submit(client, headers, base, case).status_code == 409
    assert (
        submit(client, headers, base, case, request_id=request_id).json()["id"]
        == first.json()["id"]
    )
    runs = client.get(base + "/" + case["id"] + "/runs").json()
    assert runs[0]["spec"]["output_kind"] == "chat"
    assert runs[0]["revision"] == 1
    csv_output = client.get(base + "/" + case["id"] + "/output.csv")
    assert (
        len(list(csv.reader(io.StringIO(csv_output.content.decode("utf-8-sig")), delimiter=";")))
        == 1
    )


def test_csv_xlsx_formula_injection_and_numeric_types(knowledge):
    client, headers, project, base, case = setup(knowledge)
    assert (
        submit(
            client, headers, base, case, name='=HYPERLINK("https://example.invalid")', amount=-5
        ).status_code
        == 200
    )
    assert submit(client, headers, base, case, name="  @SUM(1)", amount=3.5).status_code == 200
    rows = list(
        csv.reader(
            io.StringIO(
                client.get(base + "/" + case["id"] + "/output.csv").content.decode("utf-8-sig")
            ),
            delimiter=";",
        )
    )
    assert rows[1][0] == "-5"
    assert rows[1][1].startswith("'=")
    assert rows[2][1].startswith("'  @")
    workbook = load_workbook(
        io.BytesIO(client.get(base + "/" + case["id"] + "/output.xlsx").content)
    )
    assert workbook.active["A2"].value == -5
    assert workbook.active["A2"].data_type == "n"
    assert workbook.active["B2"].data_type == "s"
    assert workbook.active["B2"].hyperlink is None


@pytest.mark.parametrize(
    "values",
    [
        {"name": "A", "amount": True},
        {"name": "A", "amount": "1"},
        {"name": "A", "amount": 1e16},
        {"amount": 1},
        {"name": "A", "amount": 1, "date": "2026-02-30"},
        {"name": "A", "amount": 1, "secret": "x"},
    ],
)
def test_invalid_inputs_rejected(values):
    with pytest.raises(Exception) as error:
        validated_values(Definition.model_validate(spec()), values)
    assert error.value.status_code == 422


def test_invalid_definition_references_and_no_executable_templates():
    for changes in (
        {"output_columns": [{"source": "missing", "label": "x"}]},
        {"text_template": "{name.__class__}"},
        {"fields": [{"key": "name", "label": "X", "type": "choice", "choices": ["A", "A"]}]},
    ):
        with pytest.raises(ValidationError):
            Definition.model_validate({**spec(), **changes})


def test_scope_auth_archive_delete_and_csrf(knowledge):
    client, headers, project, base, case = setup(knowledge)
    second = client.post("/api/projects", json={"name": "Other"}, headers=headers).json()
    assert (
        client.get(f"/api/projects/{second['id']}/use-cases/{case['id']}/runs").status_code == 404
    )
    assert client.post(base, json={"spec": spec()}).status_code == 403
    assert submit(client, headers, base, case).status_code == 200
    assert (
        client.request(
            "DELETE", base + "/" + case["id"], json={"expected_revision": 2}, headers=headers
        ).status_code
        == 409
    )
    assert (
        client.request(
            "DELETE", base + "/" + case["id"], json={"expected_revision": 1}, headers=headers
        ).status_code
        == 200
    )
    assert client.get(base).json() == []
    assert client.get(base + "/" + case["id"] + "/output.xlsx").status_code == 404
    client.patch(
        "/api/projects/" + project["id"],
        json={"name": "Synthetic forms", "revision": 1, "archived": True},
        headers=headers,
    )
    assert client.post(base, json={"spec": spec()}, headers=headers).status_code == 409
    client.cookies.clear()
    assert client.get(base).status_code == 401


def test_invalid_json_number_and_surrogate_return_422_not_500(knowledge):
    client, headers, project, base, case = setup(knowledge)
    for value in ["NaN", "Infinity", '"\\ud800"']:
        content = (
            '{"request_id":"' + str(uuid4()) + '","expected_revision":1,'
            '"values":{"name":"Synthetic","amount":' + value + "}}"
        )
        response = client.post(
            base + "/" + case["id"] + "/runs",
            content=content,
            headers={**headers, "Content-Type": "application/json"},
        )
        assert response.status_code == 422
    assert client.get(base + "/" + case["id"] + "/runs").json() == []
