"""Real queued workflow execution contracts with deterministic provider boundary doubles."""

import base64
import json
import time
from uuid import uuid4

import pytest
from hub.db import Conversation, Run
from hub.policy import check_egress
from hub.providers import AnswerLimitReached
from hub.use_case_ai import UseCaseDialogueTurn, validated_output
from hub.use_cases import Definition
from sqlalchemy import func, select

pytest_plugins = ["test_knowledge"]


def ai_spec(kind="chat", presentation="form", file=False):
    return {
        "execution_kind": "ai",
        "processing_prompt": "Erstelle eine begründete Auswertung aus bestätigten Daten.",
        "name": "Synthetic AI workflow",
        "presentation": presentation,
        "fields": [
            {"key": "goal", "label": "Ziel", "type": "text"},
            *([{"key": "input", "label": "Datei", "type": "file"}] if file else []),
        ],
        "output_kind": kind,
        "output_columns": []
        if kind == "chat"
        else [{"label": "Kategorie", "source": "category"}, {"label": "Gesamt", "source": "total"}],
    }


class Model:
    def __init__(self, responses, limited=False):
        self.responses = list(responses)
        self.calls = []
        self.limited = limited

    async def route(self, parts, roles):
        pytest.fail("Use Cases must not invoke actionable tool routing")

    async def stream(self, parts, roles, *, external, grants):
        check_egress(
            parts,
            external=external,
            provider_id="openrouter" if external else "local",
            grants=grants,
        )
        self.calls.append((parts, roles, external))
        yield self.responses.pop(0)
        if self.limited:
            raise AnswerLimitReached("Synthetic output limit")

    async def title(self, *args):
        pytest.fail("Hidden workflow executions must not generate chat titles")


def create(knowledge, spec=None):
    app, client, headers, _, _ = knowledge
    result = client.post("/api/use-cases", headers=headers, json={"spec": spec or ai_spec()})
    assert result.status_code == 200, result.text
    return app, client, headers, result.json()


def wait(client, path):
    for _ in range(200):
        response = client.get(path)
        assert response.status_code == 200, response.text
        value = response.json()
        if value["status"] not in {"queued", "routing", "streaming"}:
            return value
        time.sleep(0.01)
    pytest.fail("Durable execution did not finish")


def run(client, headers, case, values=None, request_id=None, **extra):
    result = client.post(
        "/api/use-cases/" + case["id"] + "/runs",
        headers=headers,
        json={
            "request_id": request_id or str(uuid4()),
            "expected_revision": case["revision"],
            "values": {"goal": "Synthetic concept"} if values is None else values,
            **extra,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_prompt_required_and_legacy_cannot_be_newly_created(knowledge):
    _, client, headers, _, _ = knowledge
    missing = ai_spec()
    missing.pop("processing_prompt")
    assert client.post("/api/use-cases", headers=headers, json={"spec": missing}).status_code == 422
    missing["execution_kind"] = "legacy"
    missing["output_columns"] = [{"label": "Ziel", "source": "goal"}]
    missing["text_template"] = "{goal}"
    assert client.post("/api/use-cases", headers=headers, json={"spec": missing}).status_code == 422


def test_form_real_run_prompt_is_frozen_and_replay_never_calls_twice(knowledge):
    app, client, headers, case = create(knowledge)
    model = app.state.providers = Model(["Actual generated synthetic concept"])
    request_id = str(uuid4())
    first = run(client, headers, case, request_id=request_id)
    done = wait(client, f"/api/use-cases/{case['id']}/runs/{first['id']}")
    assert done["status"] == "succeeded"
    assert (
        done["processing"] == "ai"
        and done["output"]["text"] == "Actual generated synthetic concept"
    )
    assert len(model.calls) == 1
    parts, roles, external = model.calls[0]
    assert roles[0] == "system" and "begründete Auswertung" in parts[0].content
    assert "Synthetic concept" not in parts[0].content
    assert external is False
    assert run(client, headers, case, request_id=request_id)["id"] == first["id"]
    assert len(model.calls) == 1
    with app.state.sessions() as db:
        execution = db.get(Run, first["execution_run_id"])
        assert db.get(Conversation, execution.conversation_id).purpose == "use_case"
        assert (
            json.loads(execution.context_snapshot)["use_case"]["spec"]["processing_prompt"]
            == case["spec"]["processing_prompt"]
        )
    assert client.get("/api/conversations").json() == []


def test_structured_model_output_exports_results_not_input_values(knowledge):
    app, client, headers, case = create(knowledge, ai_spec("xlsx"))
    app.state.providers = Model(
        [
            json.dumps(
                {
                    "rows": [
                        {"category": "=HYPERLINK(unsafe)", "total": 42},
                        {"category": "Synthetic", "total": 17},
                    ],
                    "text": "Calculated summary",
                }
            )
        ]
    )
    first = run(client, headers, case)
    done = wait(client, f"/api/use-cases/{case['id']}/runs/{first['id']}")
    assert done["output"]["rows"][1] == ["Synthetic", 17]
    root = f"/api/use-cases/{case['id']}/runs/{first['id']}"
    assert "'=HYPERLINK" in client.get(root + "/output.csv").text
    import io

    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(client.get(root + "/output.xlsx").content))
    assert workbook.active["A2"].data_type == "s"
    assert workbook.active["B3"].value == 17


def test_bad_structured_output_fails_preserves_raw_and_limit_is_not_false_success(knowledge):
    app, client, headers, case = create(knowledge, ai_spec("table"))
    app.state.providers = Model(['{"rows":[{"unknown":"value"}]}'])
    first = run(client, headers, case)
    done = wait(client, f"/api/use-cases/{case['id']}/runs/{first['id']}")
    assert done["status"] == "failed" and "unknown" in done["output"]["text"]
    assert (
        client.get(f"/api/use-cases/{case['id']}/runs/{first['id']}/output.csv").status_code == 409
    )
    app.state.providers = Model(['{"rows":'], limited=True)
    limited = run(client, headers, case)
    done = wait(client, f"/api/use-cases/{case['id']}/runs/{limited['id']}")
    assert done["status"] == "limited" and done["output"]["text"] == '{"rows":'


def test_upload_original_and_actual_file_context_are_local(knowledge):
    app, client, headers, case = create(knowledge, ai_spec(file=True))
    model = app.state.providers = Model(["File facts processed"])
    original = b"category;amount\nSynthetic invoice;42\n"
    upload = client.post(
        f"/api/use-cases/{case['id']}/uploads",
        headers=headers,
        json={"filename": "invoice.csv", "content_base64": base64.b64encode(original).decode()},
    )
    assert upload.status_code == 200, upload.text
    receipt = upload.json()
    assert (
        client.get(f"/api/use-cases/{case['id']}/uploads/{receipt['id']}/original").content
        == original
    )
    first = run(client, headers, case, values={"goal": "Summarize", "input": receipt["id"]})
    done = wait(client, f"/api/use-cases/{case['id']}/runs/{first['id']}")
    assert done["status"] == "succeeded"
    fileparts = [p for p in model.calls[0][0] if p.source_id.startswith("use-case-upload:")]
    assert len(fileparts) == 1 and "Synthetic invoice" in fileparts[0].content
    assert fileparts[0].label == "LOCAL_ONLY"
    assert not model.calls[0][2]


def test_actual_dialogue_collects_values_reviews_and_manual_final_processing(knowledge):
    app, client, headers, case = create(knowledge, ai_spec(presentation="dialogue"))
    model = app.state.providers = Model(
        [
            json.dumps(
                {
                    "question": "Welches Ziel soll das Konzept erreichen?",
                    "values": {},
                    "ready": False,
                }
            ),
            json.dumps(
                {
                    "question": "Ich habe das Ziel verstanden. Möchtest du es so übernehmen?",
                    "values": {"goal": "Entlastung"},
                    "ready": True,
                }
            ),
            json.dumps(
                {
                    "question": "Ziel wurde korrigiert.",
                    "values": {"goal": "Qualität"},
                    "ready": True,
                }
            ),
            "Final generated concept",
        ]
    )
    base = f"/api/use-cases/{case['id']}"
    first = client.post(
        base + "/dialogues",
        headers=headers,
        json={"request_id": str(uuid4()), "expected_revision": 1},
    ).json()
    path = base + "/dialogues/" + first["id"]
    question = wait(client, path)
    assert "Ziel" in question["messages"][0]["content"] and not question["ready"]
    request_id = str(uuid4())
    turn = {"request_id": request_id, "expected_turn": 1, "content": "Entlastung"}
    assert client.post(path + "/turns", headers=headers, json=turn).status_code == 200
    answered = wait(client, path)
    assert answered["ready"] and answered["values"] == {"goal": "Entlastung"}
    assert client.post(path + "/turns", headers=headers, json=turn).status_code == 200
    assert len(model.calls) == 2
    assert (
        client.post(
            path + "/turns",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "expected_turn": 2,
                "content": "Bitte Ziel auf Qualität ändern",
            },
        ).status_code
        == 200
    )
    corrected = wait(client, path)
    assert corrected["values"] == {"goal": "Qualität"}
    assert len(model.calls) == 3  # Completion must be a separate explicit action.
    final = run(client, headers, case, values={}, dialogue_id=first["id"])
    result = wait(client, base + "/runs/" + final["id"])
    assert result["status"] == "succeeded" and len(model.calls) == 4
    assert result["values"] == {"goal": "Qualität"}
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(UseCaseDialogueTurn)) == 3


@pytest.mark.parametrize(
    "text",
    [
        '{"rows":[]}',
        '{"rows":[{"category":"X","total":NaN}]}',
        '{"rows":[{"category":"X","total":true}]}',
    ],
)
def test_structured_validation_is_fail_closed(text):
    with pytest.raises(ValueError):
        validated_output(Definition.model_validate(ai_spec("bi")), text)


def test_local_dialogue_derivatives_cannot_be_relabelled_cloud_for_final_run(knowledge):
    app, client, headers, case = create(knowledge, ai_spec(presentation="dialogue"))
    model = app.state.providers = Model(
        [
            json.dumps(
                {"question": "Die lokalen Angaben sind vollständig.", "values": {}, "ready": True}
            )
        ]
    )
    base = f"/api/use-cases/{case['id']}"
    started = client.post(
        base + "/dialogues",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "model_mode": "local",
            "values": {"goal": "PRIVATE_LOCAL_GOAL"},
        },
    )
    assert started.status_code == 200, started.text
    dialogue = wait(client, base + "/dialogues/" + started.json()["id"])
    assert dialogue["ready"] and dialogue["model_mode"] == "local"
    with app.state.sessions() as db:
        before = db.scalar(select(func.count()).select_from(Run))
    rejected = client.post(
        base + "/runs",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "values": {},
            "dialogue_id": dialogue["id"],
            "model_mode": "cloud",
        },
    )
    assert rejected.status_code == 409
    assert "KI-Dialog behält" in rejected.json()["detail"]
    assert len(model.calls) == 1
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Run)) == before


def test_auto_dialogue_private_derivatives_stay_local_after_optional_file_removed(knowledge):
    from dataclasses import replace

    from hub.use_case_ai import create_ai_run
    from hub.use_cases import RunInput, UseCase

    spec = ai_spec(presentation="dialogue", file=True)
    spec["fields"][1]["required"] = False
    app, client, headers, case = create(knowledge, spec)
    app.state.providers = Model(
        [
            json.dumps(
                {
                    "question": "Die privaten Eingaben sind vollständig.",
                    "values": {"goal": "Derived private fact"},
                    "ready": True,
                }
            )
        ]
    )
    base = f"/api/use-cases/{case['id']}"
    uploaded = client.post(
        base + "/uploads",
        headers=headers,
        json={
            "filename": "private.txt",
            "content_base64": base64.b64encode(b"PRIVATE_FILE_FACT").decode(),
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    started = client.post(
        base + "/dialogues",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "model_mode": "auto",
            "values": {"input": uploaded.json()["id"]},
        },
    )
    assert started.status_code == 200, started.text
    dialogue = wait(client, base + "/dialogues/" + started.json()["id"])
    assert dialogue["ready"]
    cfg = replace(knowledge[3], cloud_enabled=True)
    with app.state.sessions() as db:
        result = create_ai_run(
            db,
            cfg,
            db.get(UseCase, case["id"]),
            RunInput(
                request_id=uuid4(),
                expected_revision=1,
                values={"input": None},
                model_mode="auto",
                dialogue_id=dialogue["id"],
            ),
        )
        execution = db.get(Run, result["execution_run_id"])
        snapshot = json.loads(execution.context_snapshot)
        assert snapshot["use_case"]["files"] == []
        assert snapshot["use_case"]["values"]["goal"] == "Derived private fact"
        assert all(part["label"] == "LOCAL_ONLY" for part in snapshot["parts"])
        assert not db.get(Conversation, execution.conversation_id).cloud_allowed
        db.rollback()


def test_invalid_control_character_in_model_table_is_retained_but_not_exported(knowledge):
    app, client, headers, case = create(knowledge, ai_spec("xlsx"))
    raw = json.dumps({"rows": [{"category": "Bad\u0001cell", "total": 42}]})
    app.state.providers = Model([raw])
    first = run(client, headers, case)
    base = f"/api/use-cases/{case['id']}/runs/{first['id']}"
    result = wait(client, base)
    assert result["status"] == "failed"
    assert result["output"]["text"] == raw
    assert client.get(base + "/output.csv").status_code == 409
    assert client.get(base + "/output.xlsx").status_code == 409


def test_frozen_model_instruction_explains_independent_output_column_labels(knowledge):
    spec = ai_spec("table")
    spec["output_columns"] = [
        {"source": "ergebnis", "label": "Begründung"},
        {"source": "spalte_2", "label": "Empfohlene Maßnahme"},
    ]
    app, client, headers, case = create(knowledge, spec)
    model = app.state.providers = Model(
        [
            json.dumps(
                {"rows": [{"ergebnis": "Synthetic reasoning", "spalte_2": "Synthetic action"}]}
            )
        ]
    )
    first = run(client, headers, case)
    result = wait(client, f"/api/use-cases/{case['id']}/runs/{first['id']}")
    assert result["status"] == "succeeded"
    system = model.calls[0][0][0].content
    assert '{"key": "ergebnis", "label": "Begründung"}' in system
    assert '{"key": "spalte_2", "label": "Empfohlene Maßnahme"}' in system
    assert system.index('"label": "Begründung"') < system.index('"label": "Empfohlene Maßnahme"')
    assert result["output"]["columns"] == ["Begründung", "Empfohlene Maßnahme"]
