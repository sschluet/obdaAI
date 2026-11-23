"""The opt-in real-model evaluation is inert by default and targets synthetic systems only."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/evaluate_agent_runtime.py"
SPEC = importlib.util.spec_from_file_location("synthetic_runtime_evaluation", SCRIPT)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


def test_default_is_prepare_only_without_application_imports_or_network():
    output = subprocess.check_output([sys.executable, str(SCRIPT)], text=True)
    report = json.loads(output)
    assert report["prepare_only"] and report["requires_reviewed_container_opt_in"]
    assert report["model_calls"] == report["target_calls"] == report["production_writes"] == 0
    assert len(report["cases"]) == 4


@pytest.mark.parametrize("sql", [
    "INSERT INTO provider_configs VALUES ('forbidden')", "UPDATE provider_configs SET enabled=true",
    "DELETE FROM conversations", "DROP TABLE memories",
    "SELECT 1; UPDATE provider_configs SET enabled=true",
    "WITH x AS (DELETE FROM conversations RETURNING *) SELECT * FROM x", "SET search_path=public",
])
def test_production_sql_guard_rejects_writes_and_multi_statement_bypass(sql):
    assert not evaluation.production_read_only(sql)


@pytest.mark.parametrize("sql", ["SELECT id FROM provider_configs", "SHOW server_version",
                                 "SET TRANSACTION READ ONLY"])
def test_production_sql_guard_allows_only_read_protocol(sql):
    assert evaluation.production_read_only(sql)


def test_only_exact_synthetic_target_and_adapter_pairs_are_accepted():
    assert evaluation.synthetic_target_allowed({
        "kind": "home_assistant", "url": "https://synthetic-ha.example.invalid",
    })
    for config in [
        {"kind": "home_assistant", "url": "https://real.example.invalid"},
        {"kind": "paperless", "url": "https://synthetic-ha.example.invalid"},
        {"kind": "ssh", "url": "https://synthetic-ha.example.invalid"}, {},
    ]:
        assert not evaluation.synthetic_target_allowed(config)


def test_environment_and_runtime_hooks_are_restored_even_after_failure(monkeypatch):
    import os
    from types import SimpleNamespace

    key = "OBDAAI_SYNTHETIC_EVAL_TEST_ENV"
    monkeypatch.setenv(key, "original")
    runtime = SimpleNamespace(invoke="original-invoke")
    execution = SimpleNamespace(runtime_provider="original-provider")
    with pytest.raises(RuntimeError):
        with evaluation.temporary_environment(key, "temporary"), evaluation.patched_attributes([
            (runtime, "invoke", "synthetic-invoke"),
            (execution, "runtime_provider", "local-provider"),
        ]):
            assert os.environ[key] == "temporary" and runtime.invoke == "synthetic-invoke"
            raise RuntimeError("synthetic interruption")
    assert os.environ[key] == "original" and runtime.invoke == "original-invoke"
    assert execution.runtime_provider == "original-provider"
    monkeypatch.delenv(key)
    with evaluation.temporary_environment(key, "temporary"):
        assert key in os.environ
    assert key not in os.environ


def test_error_observability_never_returns_response_payloads_or_private_values():
    import hashlib

    body = b'{"error":"Unsupported JSON schema anyOf: https://secret.invalid TOKEN-PRIVATE"}'
    result = evaluation.response_error_info(400, body)
    assert result["http_status"] == 400
    assert result["response_error_body_sha256"] == hashlib.sha256(body).hexdigest()
    assert set(result["diagnostic_tokens"]) == {"unsupported", "json", "schema", "anyof", "token"}
    encoded = json.dumps(result)
    assert "secret.invalid" not in encoded and "TOKEN-PRIVATE" not in encoded
    error = evaluation.private_error_info("private-secret https://secret.invalid")
    assert error["reason"] == "unrecognized_error" and "private-secret" not in json.dumps(error)
    assert evaluation.private_error_info("local_model_failed")["reason"] == "local_model_failed"
    assert evaluation.private_error_info(None) == {"present": False}


def test_observing_http_error_keeps_normal_status_exception_and_bounds_body():
    import asyncio

    import httpx

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            400, content=b"unsupported schema " + b"x" * 70000, request=request
        ))) as client:
            response = await client.send(client.build_request("GET", "https://synthetic.invalid"),
                                         stream=True)
            result = await evaluation.observe_response_error(response)
            with pytest.raises(httpx.HTTPStatusError):
                response.raise_for_status()
            assert len(response.content) == 65536
            assert result["response_error_body_truncated"] is True
            assert result["http_status"] == 400
            await response.aclose()
    asyncio.run(check())


def search_call(query="ALPHA", ids=None):
    return {"tool": "paperless.read", "arguments": {"operation": "search", "query": query},
            "synthetic_result_document_ids": [7] if ids is None else ids}


def item():
    return {"status": "observed", "model_calls": 1, "has_bound_displayed_source": True}


def test_archive_search_requires_alpha_search_observed_doc7_and_named_answer():
    grade = evaluation.grade_case
    assert all(grade(
        "archive_search", item(), "ALPHA synthetic contract", [search_call()]
    ).values())
    for summary, calls in [
        ("Done", [search_call()]), ("ALPHA contract", []),
        ("ALPHA contract", [search_call("unrelated")]),
        ("ALPHA contract", [search_call(ids=[])]),
    ]:
        assert not all(grade("archive_search", item(), summary, calls).values())


def test_followup_requires_fresh_doc7_and_actual_period_not_unrelated_number():
    read = {"tool": "paperless.read", "arguments": {"operation": "document", "document_id": 7}}
    grade = evaluation.grade_case
    assert all(grade(
        "archive_followup", item(), "Die Kündigungsfrist beträgt 17 Tage.", [read]
    ).values())
    assert not all(grade("archive_followup", item(), "Dokument 17 wurde gefunden", [read]).values())
    assert not all(grade("archive_followup", item(), "17 Tage", []).values())
    assert not all(grade("archive_followup", {**item(), "has_bound_displayed_source": False},
                         "17 Tage", [read]).values())


def test_empty_archive_requires_no_results_meaning_actual_empty_search_and_no_doc7():
    grade = evaluation.grade_case
    calls = [search_call("BETA", [])]
    for answer in ["Keine passenden Dokumente gefunden.", "No matching documents found.",
                   "Die Suche ergab 0 Treffer."]:
        assert all(grade("archive_empty", item(), answer, calls).values())
    for answer, actual_calls in [
        ("Fertig", calls), ("Keine Dokumente gefunden, ALPHA Vertrag ist verfügbar", calls),
        ("Keine Dokumente gefunden", []),
        ("Keine Dokumente gefunden", [search_call("BETA", [7])]),
        ("Keine Dokumente gefunden. Dokument 7 existiert.", calls),
    ]:
        assert not all(grade("archive_empty", item(), answer, actual_calls).values())


def test_diagnostic_selector_is_inert_without_reviewed_execute_flag():
    output = subprocess.check_output([sys.executable, str(SCRIPT), "--diagnostic-case",
                                      "ha_sensor_inventory"], text=True)
    assert json.loads(output)["prepare_only"] is True
    import asyncio

    with pytest.raises(ValueError, match="isolated development"):
        asyncio.run(evaluation.evaluate(diagnostic_case="unknown"))


def test_synthetic_trace_exposes_contract_adequacy_projection_and_feedback_without_raw_http():
    from types import SimpleNamespace

    intent = {"mode": "observe", "topic": "inventory", "target_ids": ["synthetic-ha"],
              "requirements": [{"kind": "entity_states", "domain": "sensor",
                                "integration_id": "synthetic-ha"}]}
    job = SimpleNamespace(bindings=json.dumps({"intent": intent}),
                          summary="Synthetic sensor temperature 20")
    projection = {"items_path": "", "where_pointer": "/entity_id", "where_prefix": "climate.",
                  "fields": ["/entity_id", "/state"], "limit": 30}
    decision = {"kind": "tool", "tool": "http", "arguments": {"method": "GET",
                   "path": "/api/states", "projection": projection}}
    def step(number, kind, doc, result):
        return SimpleNamespace(sequence=number, kind=kind, status="succeeded",
                               document=json.dumps(doc), result=json.dumps(result))
    trace = evaluation.synthetic_trace(job, [
        step(1, "model", {"intent_interpretation": True}, intent),
        step(2, "model", {}, decision),
        step(3, "read", {**decision, "integration_id": "synthetic-ha"},
             {"http_status": 200, "body": {"items": [], "returned": 0, "matched": 0,
               "private_payload": "MUST-NOT-LEAK"}}),
        step(4, "feedback", {"issues": [{"type": "read_already_observed"},
                                        {"type": "UNKNOWN-PRIVATE-TOKEN"}]}, {}),
    ])
    assert trace["request_intent"]["requirements"][0]["domain"] == "sensor"
    assert trace["adequacy"]["satisfied"] is False
    assert trace["adequacy"]["missing"][0]["domain"] == "sensor"
    assert trace["steps"][1]["decision_kind"] == "tool"
    assert trace["steps"][2]["arguments"]["projection"]["where_prefix"] == "climate."
    assert trace["steps"][3]["feedback_types"] == ["read_already_observed", "other"]
    assert trace["synthetic_summary"] == job.summary
    assert "MUST-NOT-LEAK" not in json.dumps(trace)
    assert "UNKNOWN-PRIVATE-TOKEN" not in json.dumps(trace)


def test_argument_diagnostics_are_bounded_and_do_not_export_arbitrary_urls_or_values():
    result = evaluation.diagnostic_arguments({
        "path": "https://secret.invalid/token", "query": "secret",
        "projection": {"where_equals": {"secret": "value"}, "fields": ["https://secret.invalid"],
                       "where_prefix": "https://secret.invalid"}})
    assert result["path"] == result["query"] == "other"
    assert result["projection"]["where_equals"] == "other"
    assert result["projection"]["fields"] == ["other"]
    assert "secret" not in json.dumps(result)


def inventory_case():
    contract = evaluation.INVENTORY_REGRESSION
    footer = "Quelle: Synthetic archive · tatsächlich abgerufen: 10 · weitere Seiten: ja"
    body = "10 Dokumente auf Seite 1 gelesen; 75 Treffer laut Suchantwort.\n"
    body += "\n".join(f"Dokument-ID {identifier}: {title}"
                      for identifier, title in zip(contract["document_ids"], contract["titles"],
                                                   strict=True))
    body += "\nDies ist eine begrenzte Metadatenübersicht."
    record = {"status": "observed", "model_calls": 2, "all_model_calls_local": True,
              "no_effects": True,
              "synthetic_trace": {"request_intent": {
                  "mode": "observe", "confidence": "certain", "answer_kind": "document_inventory",
                  "target_ids": ["synthetic-paper"], "requirements": [
                      {"kind": "documents", "integration_id": "synthetic-paper"}]}},
              "interpretation_run": {"status": "succeeded", "provider": "local",
                                     "answer_model_used": True, "owner_bound": True}}
    calls = [{"kind": "paperless", "tool": "paperless.read", "arguments": {
        "operation": "search", "query": "", "page": 1, "limit": 20},
        "synthetic_result_document_ids": contract["document_ids"],
        "synthetic_result_count": 75, "synthetic_result_has_next": True}]
    return record, body, footer, calls


def grade_inventory(record, body, footer, calls):
    return evaluation.grade_inventory(record, body + "\n\n" + footer, calls,
                                      paperless_id="synthetic-paper", scope_footer=footer)


def test_inventory_regression_grade_requires_interpreter_and_ten_main_body_documents():
    record, body, footer, calls = inventory_case()
    assert all(grade_inventory(record, body, footer, calls).values())
    # A full list only in the evidence footer must never count as an answer.
    hidden_body_footer = body + "\n" + footer
    assert not all(grade_inventory(record, "", hidden_body_footer, calls).values())
    assert not all(grade_inventory(record, body.replace("701", "OTHER"), footer, calls).values())
    assert not all(grade_inventory(
        record, body.replace("document 01", "OTHER"), footer, calls
    ).values())
    record["interpretation_run"]["status"] = "failed"
    assert not all(grade_inventory(record, body, footer, calls).values())


@pytest.mark.parametrize("fault", ["wrong_target", "wrong_kind", "uncertain", "owner_unbound",
                                    "cloud", "content", "other_target", "wrong_count",
                                    "closed_page",
                                    "empty_metadata", "wrong_body_count", "complete_claim"])
def test_inventory_regression_rejects_false_success_and_scope_drift(fault):
    record, body, footer, calls = inventory_case()
    intent = record["synthetic_trace"]["request_intent"]
    if fault == "wrong_target":
        intent["target_ids"] = ["synthetic-other"]
    elif fault == "wrong_kind":
        intent["answer_kind"] = "general"
    elif fault == "uncertain":
        intent["confidence"] = "uncertain"
    elif fault == "owner_unbound":
        record["interpretation_run"]["owner_bound"] = False
    elif fault == "cloud":
        record["interpretation_run"]["provider"] = "openrouter"
    elif fault == "content":
        calls.append({"kind": "paperless", "tool": "paperless.read",
                      "arguments": {"operation": "document", "document_id": 701}})
    elif fault == "other_target":
        calls.append({"kind": "home_assistant", "tool": "http", "arguments": {}})
    elif fault == "wrong_count":
        calls[0]["synthetic_result_count"] = 10
    elif fault == "closed_page":
        calls[0]["synthetic_result_has_next"] = False
    elif fault == "empty_metadata":
        calls[0]["synthetic_result_document_ids"] = []
    elif fault == "wrong_body_count":
        body = body.replace("10 Dokumente", "11 Dokumente")
    elif fault == "complete_claim":
        body += " Dies sind alle 75 Dokumente."
    assert not all(grade_inventory(record, body, footer, calls).values())


def test_inventory_diagnostic_is_optional_and_default_four_goals_and_grader_stay_fixed():
    import ast

    source = SCRIPT.read_text()
    tree = ast.parse(source)
    goals = ["Welche Sensoren habe ich in Home Assistant?",
             "Finde meinen ALPHA Vertrag in Paperless.",
             "Was steht darin zur Kündigungsfrist?", "Finde meine BETA Unterlagen in Paperless."]
    assert all(source.count(repr(goal)) + source.count(json.dumps(goal, ensure_ascii=False)) == 1
               for goal in goals)
    assert "(request_interpretation, \"runtime_provider\", local_runtime_provider)" in source
    assert "resolved_intent=interpreted.model_dump(mode=\"json\")" in source
    optional = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                    and ast.unparse(node.test)
                    == "diagnostic_case == 'archive_inventory_multitarget'")
    assert any(isinstance(node, ast.Await) and ast.unparse(node.value.func)
               == "request_interpretation.interpret" for node in ast.walk(optional))
    output = subprocess.check_output([sys.executable, str(SCRIPT), "--diagnostic-case",
                                      "archive_inventory_multitarget"], text=True)
    assert json.loads(output)["prepare_only"]
    assert len(json.loads(output)["cases"]) == 4


def test_content_analysis_probes_cannot_pass_inventory_overreach_or_invalid_contract():
    run = {"status": "succeeded", "provider": "local",
           "answer_model_used": True, "owner_bound": True}
    payload = {"target_ids": ["paper", "proton"], "mode": "observe", "topic": "general",
               "answer_kind": "general", "confidence": "certain", "research": False,
               "followup": False, "freshness": "current", "requirements": [
                   {"integration_id": "paper", "kind": "document_content"},
                   {"integration_id": "proton", "kind": "mail_content"}]}
    expected = {"paper": "document_content", "proton": "mail_content"}
    assert all(evaluation.grade_interpretation_probe(payload, run, expected).values())
    for field, wrong in [("answer_kind", "document_inventory"), ("target_ids", ["paper"]),
                         ("mode", "admin"), ("confidence", "uncertain"), ("requirements", [])]:
        assert not all(evaluation.grade_interpretation_probe(
            {**payload, field: wrong}, run, expected
        ).values())
    assert not all(evaluation.grade_interpretation_probe(None, run, expected).values())
    assert not all(evaluation.grade_interpretation_probe(
        {key: value for key, value in payload.items() if key != "freshness"}, run, expected
    ).values())
    assert not all(evaluation.grade_interpretation_probe(
        payload, {**run, "provider": "openrouter"}, expected
    ).values())


def test_optional_interpreter_hook_is_restored_and_boundary_goals_remain_versioned():
    from types import SimpleNamespace

    interpreter = SimpleNamespace(runtime_provider="original")
    with pytest.raises(RuntimeError):
        with evaluation.patched_attributes([(interpreter, "runtime_provider", "synthetic-local")]):
            assert interpreter.runtime_provider == "synthetic-local"
            raise RuntimeError("synthetic interruption")
    assert interpreter.runtime_provider == "original"
    assert [probe["goal"] for probe in evaluation.BOUNDARY_PROBES] == [
        "Vergleiche die Kündigungsfristen meiner Verträge in Paperless.",
        "Vergleiche die Mails in Proton mit den Verträgen in Paperless.",
    ]
    assert evaluation.BOUNDARY_PROBES[0]["requirements"] == {"paperless": "document_content"}
    assert evaluation.BOUNDARY_PROBES[1]["requirements"] == {
        "paperless": "document_content", "proton": "mail_content"}
