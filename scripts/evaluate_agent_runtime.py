"""Opt-in real local-model agent evaluation against isolated synthetic systems.

Default invocation prints its contract and does nothing else. Run only in a reviewed
application container with its existing local provider/key mounts. Production SQL
is restricted to local ProviderConfig reads; all application writes use a temporary
SQLite database. No real integration transport, cloud model or web search is used.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

SQL_COUNTS = {"reads": 0, "protocol": 0, "blocked_writes": 0}


@contextmanager
def temporary_environment(key: str, value: str):
    previous = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


@contextmanager
def patched_attributes(changes):
    previous = [(owner, name, getattr(owner, name)) for owner, name, _ in changes]
    try:
        for owner, name, value in changes:
            setattr(owner, name, value)
        yield
    finally:
        for owner, name, value in reversed(previous):
            setattr(owner, name, value)


def production_read_only(statement: str) -> bool:
    normalized = " ".join(statement.strip().upper().split())
    if ";" in normalized.rstrip(";"):
        return False
    return normalized.startswith(("SELECT ", "SHOW ")) or normalized == "SET TRANSACTION READ ONLY"


def synthetic_target_allowed(config: dict[str, Any]) -> bool:
    return config.get("url") == {
        "home_assistant": "https://synthetic-ha.example.invalid",
        "paperless": "https://synthetic-archive.example.invalid",
    }.get(config.get("kind")) and config.get("kind") in {"home_assistant", "paperless"}


DIAGNOSTIC_TOKENS = frozenset({
    "schema", "grammar", "unsupported", "invalid", "anyof", "oneof", "pattern",
    "regex", "enum", "required", "constraint", "token", "json", "validation",
    "timeout", "capacity", "context", "parse", "unexpected", "additionalproperties",
})
SAFE_REASONS = frozenset({
    "local_model_failed", "local_model_timeout", "context_budget_exceeded",
    "Provider nicht verfügbar oder ungültige Antwort",
})
SAFE_ERROR_TYPES = frozenset({
    "HTTPStatusError", "ReadTimeout", "ConnectTimeout", "ConnectError", "TimeoutError",
    "AgentPlanningError", "AgentContextLimitError", "ValueError", "ValidationError",
    "PermissionError", "RuntimeError", "JSONDecodeError",
})


def private_error_info(value: Any) -> dict[str, Any]:
    """Only app-authored known values and an opaque digest leave the process."""
    if value is None:
        return {"present": False}
    if type(value) is not str:
        return {"present": True, "reason": "unrecognized_error"}
    return {"present": True, "reason": value if value in SAFE_REASONS else "unrecognized_error",
            "sha256": hashlib.sha256(value.encode()).hexdigest()}


def response_error_info(status: int, body: bytes, truncated: bool = False) -> dict[str, Any]:
    text = body.decode("utf-8", errors="ignore").casefold()
    text = re.sub(r"https?://[^\s\"<>]+", "", text)
    words = set(re.findall(r"[a-z]+", text))
    return {"http_status": status, "response_error_body_sha256": hashlib.sha256(body).hexdigest(),
            "response_error_body_truncated": truncated,
            "diagnostic_tokens": sorted(words & DIAGNOSTIC_TOKENS)}


async def observe_response_error(response) -> dict[str, Any]:
    body = bytearray()
    truncated = False
    try:
        async for piece in response.aiter_bytes():
            room = 65536 - len(body)
            body.extend(piece[:room])
            if len(piece) > room:
                truncated = True
                break
        # Error bodies remain available for the ordinary provider failure path.
        response._content = bytes(body)
        return response_error_info(response.status_code, bytes(body), truncated)
    except Exception:
        return {"http_status": response.status_code, "response_error_body_unavailable": True}


def grade_case(case_id: str, item: dict[str, Any], summary: str,
               calls: list[dict[str, Any]]) -> dict[str, bool]:
    """Grade synthetic evidence and answer meaning, never terminal status alone."""
    common = item["status"] == "observed" and item["model_calls"] > 0
    text = summary.casefold()
    searches = [c for c in calls if c.get("tool") == "paperless.read"
                and c.get("arguments", {}).get("operation") == "search"]
    doc7_reads = any(c.get("tool") == "paperless.read"
                     and c.get("arguments", {}).get("operation") == "document"
                     and c["arguments"].get("document_id") == 7 for c in calls)
    if case_id == "ha_sensor_inventory":
        checks = {"observed_with_actual_model": common,
                  "fresh_state_read": any(
                      c["arguments"].get("path") == "/api/states" for c in calls),
                  "observed_sensor_answer": "sensor.synthetic_temperature" in summary
                  or ("synthetic temperature" in text and "20" in text)}
    elif case_id == "archive_search":
        checks = {"observed_with_actual_model": common,
                  "actual_alpha_search": any("alpha" in c["arguments"].get("query", "").casefold()
                                             for c in searches),
                  "doc7_observed_in_search": any(c.get("synthetic_result_document_ids") == [7]
                                                for c in searches),
                  "alpha_answer": "alpha" in text}
    elif case_id == "archive_followup":
        checks = {"observed_with_actual_model": common,
                  "bound_displayed_source": item["has_bound_displayed_source"],
                  "fresh_doc7_read": doc7_reads,
                  "period_answer": bool(re.search(r"\b17\s*(?:tage[n]?|days?)\b", text))}
    elif case_id == "archive_empty":
        no_results = bool(re.search(
            r"(?:keine?\s+(?:passenden?\s+|weiteren?\s+)?(?:dokumente?|unterlagen?|treffer|ergebnisse?|verträge?)"
            r"|(?:nichts|nicht|keine)\s+gefunden|0\s+(?:treffer|ergebnisse?|dokumente?)"
            r"|no\s+(?:matching\s+)?(?:documents?|results?|matches|records))", text))
        checks = {"observed_with_actual_model": common,
                  "actual_beta_search": any("beta" in c["arguments"].get("query", "").casefold()
                                            for c in searches),
                  "empty_search_evidence": bool(searches) and all(
                      c.get("synthetic_result_document_ids") == [] for c in searches),
                  "explicit_no_results_answer": no_results,
                  "no_hallucinated_doc7": not doc7_reads and "alpha" not in text
                  and not re.search(r"(?:document|dokument|id)\s*[:#]?\s*7\b", text)}
    else:
        raise ValueError("Unknown synthetic case")
    return checks


FEEDBACK_TYPES = frozenset({
    "json_invalid", "missing", "extra_forbidden", "literal_error", "value_error",
    "string_pattern_mismatch", "string_too_long", "string_too_short", "int_type",
    "concrete_private_read_required", "alternative_read_required",
    "private_read_question_not_allowed", "private_read_terminal_not_available",
    "document_content_read_required", "private_data_not_queried", "read_already_observed",
    "preparation_already_observed",
})


def diagnostic_arguments(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, allowed in {
        "method": {"GET"}, "path": {"/api/", "/api/states", "/api/services"},
        "operation": {"search", "document"}, "query": {"ALPHA", "BETA", ""},
    }.items():
        if key in value:
            selected = value[key]
            result[key] = selected if type(selected) is str and selected in allowed else "other"
    if type(value.get("document_id")) is int:
        result["document_id"] = value["document_id"] if value["document_id"] == 7 else "other"
    projection = value.get("projection")
    if isinstance(projection, dict):
        projected = {}
        for key in ("items_path", "where_pointer", "where_prefix"):
            selected = projection.get(key)
            if selected is None or (type(selected) is str and re.fullmatch(
                r"[/a-zA-Z0-9_.-]{0,80}", selected
            )):
                projected[key] = selected
            else:
                projected[key] = "other"
        fields = projection.get("fields")
        if isinstance(fields, list):
            projected["fields"] = [field if type(field) is str and re.fullmatch(
                r"/[a-zA-Z0-9_/]{1,80}", field
            ) else "other" for field in fields[:20]]
        if type(projection.get("limit")) is int:
            projected["limit"] = projection["limit"]
        if "where_equals" in projection:
            projected["where_equals"] = (projection["where_equals"]
                if projection["where_equals"] is None or (type(projection["where_equals"]) is str
                    and projection["where_equals"] in {"on", "off", "unknown", "unavailable"})
                else "other")
        result["projection"] = projected
    return result


def synthetic_trace(job, steps) -> dict[str, Any]:
    """Only reviewed opt-in synthetic jobs enter here, never production chat rows."""
    from hub.agent_intent import RequestIntent, adequacy

    def document(value):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}

    def intent(value):
        if not isinstance(value, dict):
            return None
        try:
            selected = RequestIntent.model_validate(value).model_dump(mode="json")
            def identifier(item):
                return (item if re.fullmatch(r"[0-9a-f-]{36}|synthetic-[a-z-]{1,50}", item)
                        else "other")
            selected["target_ids"] = [identifier(item) for item in selected["target_ids"]]
            for requirement in selected["requirements"]:
                requirement["integration_id"] = identifier(requirement["integration_id"])
            return selected
        except (ValueError, TypeError):
            return {"invalid_contract": True}

    frozen = intent(document(job.bindings).get("intent"))
    proof = None
    if frozen and not frozen.get("invalid_contract"):
        try:
            actual = adequacy(frozen, steps)
            proof = {"satisfied": actual["satisfied"], "missing": actual["missing"]}
        except (ValueError, TypeError):
            proof = {"invalid_contract": True}
    history = []
    for step in steps[:40]:
        doc, result = document(step.document), document(step.result)
        row = {"sequence": step.sequence, "kind": step.kind, "status": step.status}
        if step.kind in {"read", "effect"}:
            row["tool"] = doc.get("tool") if doc.get("tool") in {
                "http", "paperless.read", "inspect_capabilities"
            } else "other"
            row["arguments"] = diagnostic_arguments(doc.get("arguments"))
            row["capability_inspection"] = doc.get("capability_inspection") is True
        if step.kind == "model":
            row["decision_kind"] = result.get("kind") if result.get("kind") in {
                "tool", "finish", "ask", "stop"
            } else None
            row["intent_interpretation"] = doc.get("intent_interpretation") is True
            row["summarize_only"] = doc.get("summarize_only") is True
            if "mode" in result or "intent" in result:
                row["model_intent"] = intent(result.get("intent", result))
            if result.get("kind") == "tool":
                row["tool"] = result.get("tool") if result.get("tool") in {
                    "http", "paperless.read", "inspect_capabilities"
                } else "other"
                row["arguments"] = diagnostic_arguments(result.get("arguments"))
        if step.kind == "feedback":
            row["feedback_types"] = [issue.get("type") if issue.get("type") in FEEDBACK_TYPES
                else "other" for issue in doc.get("issues", [])[:20] if isinstance(issue, dict)]
        history.append(row)
    return {"request_intent": frozen, "adequacy": proof, "steps": history,
            "steps_truncated": len(steps) > 40,
            "synthetic_summary": job.summary[:4000], "summary_truncated": len(job.summary) > 4000}


def evaluation_report(results, *, diagnostic_case=None) -> dict[str, Any]:
    return {
        "synthetic_only": True, "production_writes": 0,
        "production_reads": SQL_COUNTS["reads"],
        "production_blocked_writes": SQL_COUNTS["blocked_writes"],
        "cloud_calls": 0, "actual_runtime_and_model": True,
        "scope": ({"ha_sensor_inventory": "development_ha_only",
                   "archive_search_followup": "development_archive_pair"}.get(
                       diagnostic_case, "four_case_runtime")),
        "diagnostic_schema_version": 3,
        "private_synthetic_summary_included": True,
        "cases": results,
        "passed": SQL_COUNTS["blocked_writes"] == 0 and all(
            item["passed"] and item["no_effects"] and item["all_model_calls_local"]
            for item in results
        ),
    }


async def evaluate(*, diagnostic_case: str | None = None) -> dict[str, Any]:
    if diagnostic_case not in {None, "ha_sensor_inventory", "archive_search_followup"}:
        raise ValueError("Only reviewed isolated development diagnostics are supported")
    # Delay every application import until the explicit opt-in, and redirect the
    # API module's global factory before importing it. It never sees production.
    import httpx
    from hub.config import Settings
    from hub.db import ProviderConfig, session_factory
    from sqlalchemy import event, select

    original_cfg = Settings.from_env()
    if not original_cfg.database_url.startswith("postgresql"):
        raise ValueError("Reviewed container with PostgreSQL configuration required")
    SQL_COUNTS.update(reads=0, protocol=0, blocked_writes=0)
    production = session_factory(original_cfg.database_url)
    engine = production.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def readonly_sql(conn, cursor, statement, parameters, context, executemany):
        if not production_read_only(statement):
            SQL_COUNTS["blocked_writes"] += 1
            raise PermissionError("Production writes are forbidden in synthetic evaluation")
        SQL_COUNTS["reads" if statement.lstrip().upper().startswith("SELECT ") else "protocol"] += 1

    @event.listens_for(engine, "begin")
    def readonly_transaction(connection):
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")

    with production() as db:
        local = db.scalar(
            select(ProviderConfig).where(
                ProviderConfig.kind == "local",
                ProviderConfig.enabled.is_(True),
                ProviderConfig.is_default.is_(True),
            )
        )
        if local is None:
            raise ValueError("No currently enabled default local model")
        # Keep the actual encrypted key only on the detached in-memory object.
        db.expunge(local)

    def current_local() -> None:
        with production() as db:
            current = db.get(ProviderConfig, local.id)
            if (
                not current
                or not current.enabled
                or not current.is_default
                or current.revision != local.revision
                or current.config != local.config
            ):
                raise PermissionError("Local provider changed during synthetic evaluation")

    with tempfile.TemporaryDirectory(prefix="obdaai-synthetic-runtime-") as temporary:
        root = Path(temporary)
        os.chmod(root, 0o700)
        url = "sqlite:///" + str(root / "synthetic.sqlite")
        with temporary_environment("HUB_DATABASE_URL", url):
            from hub import agent_runtime as runtime
            from hub import execution
            from hub.agent_context import project
            from hub.agent_models import AgentJob, AgentPolicy
            from hub.agent_read_references import bind
            from hub.agent_tools import Rules
            from hub.api import (
                create_app,  # noqa: F401 -- register all metadata, no lifespan/startup
            )
            from hub.db import ActionPolicy, Base, Conversation, Message, Run
            from hub.integrations import Integration, IntegrationBinding
            from hub.provider_api import adapter
            from hub.providers import Providers

            cfg = replace(
                original_cfg,
                database_url=url,
                cloud_enabled=False,
                openrouter_model="",
                openrouter_key_file="",
                integration_targets_enabled=True,
            )
            factory = session_factory(url)
            Base.metadata.create_all(factory.kw["bind"])
            with factory() as db:
                db.add(ActionPolicy(id=1, paused=True))
                db.add(
                    ProviderConfig(
                        id=local.id,
                        name="Synthetic local evaluation",
                        kind="local",
                        enabled=True,
                        is_default=True,
                        revision=local.revision,
                        config=local.config,
                        encrypted_secret=None,
                    )
                )
                db.commit()

            def local_runtime_provider(_factory, _cfg, **kwargs):
                if kwargs.get("cloud_only"):
                    raise PermissionError("Cloud is forbidden in synthetic evaluation")
                current_local()
                provider = adapter(local, cfg)
                configured = json.loads(local.config)
                provider.settings = replace(
                    provider.settings,
                    cloud_enabled=False,
                    openrouter_model="",
                    openrouter_key_file="",
                    local_max_tokens=configured["output_tokens"],
                    context_limit=configured["context_chars"],
                )
                with factory() as db:
                    selected = db.get(ProviderConfig, local.id)
                    db.expunge(selected)
                return provider.settings, provider, {"local": selected}

            model_diagnostics: list[dict[str, Any]] = []
            original_send = httpx.AsyncClient.send

            async def observed_send(client, request, **kwargs):
                response = await original_send(client, request, **kwargs)
                if response.is_error:
                    model_diagnostics.append(await observe_response_error(response))
                return response

            original_stream = Providers.stream

            async def local_stream(self, *args, **kwargs):
                if kwargs.get("external"):
                    raise PermissionError("Cloud is forbidden in synthetic evaluation")
                previous = self.before_send

                def final_permission():
                    current_local()
                    if previous:
                        previous()

                self.before_send = final_permission
                try:
                    async for chunk in original_stream(self, *args, **kwargs):
                        yield chunk
                except Exception as error:
                    category = type(error).__name__
                    model_diagnostics.append({"error_type": category if category in SAFE_ERROR_TYPES
                                              else "unrecognized_error"})
                    raise
                finally:
                    self.before_send = previous

            calls: list[dict[str, Any]] = []
            scenario = {"empty": False}
            states = [
                {
                    "entity_id": "sensor.synthetic_temperature",
                    "state": "20",
                    "attributes": {"friendly_name": "Synthetic temperature"},
                },
                {
                    "entity_id": "light.synthetic_desk",
                    "state": "on",
                    "attributes": {"friendly_name": "Synthetic desk"},
                },
            ]
            document = {
                "id": 7,
                "title": "ALPHA synthetic contract",
                "created": "2026-01-01",
                "correspondent": None,
                "document_type": None,
                "tags": [],
                "content": "The synthetic cancellation period is 17 days.",
                "content_truncated": False,
            }

            def synthetic_invoke(_cfg, config, secret, tool, arguments, rules, before_send):
                if not synthetic_target_allowed(config) or secret:
                    raise PermissionError("Only synthetic integration targets are permitted")
                before_send()
                calls.append({"kind": config["kind"], "tool": tool, "arguments": arguments})
                if tool == "paperless.read":
                    if arguments["operation"] == "document":
                        if arguments["document_id"] != 7:
                            raise ValueError("Only an observed synthetic document may be read")
                        return {"label": "LOCAL_ONLY", "operation": "document", "data": document}
                    rows = (
                        []
                        if scenario["empty"]
                        else [
                            {
                                k: v
                                for k, v in document.items()
                                if k not in {"content", "content_truncated"}
                            }
                        ]
                    )
                    calls[-1]["synthetic_result_document_ids"] = [row["id"] for row in rows]
                    return {
                        "label": "LOCAL_ONLY",
                        "operation": "search",
                        "data": {
                            "count": len(rows),
                            "results": rows,
                            "page": arguments["page"],
                            "page_size": arguments["limit"],
                            "has_next": False,
                        },
                    }
                if tool != "http" or arguments["method"] != "GET":
                    raise PermissionError("Synthetic harness never dispatches changes")
                path = arguments["path"]
                if path == "/api/":
                    return {"http_status": 200, "body": {"message": "API running."}}
                if path == "/api/states":
                    body = (
                        project(states, arguments["projection"])
                        if arguments.get("projection")
                        else states
                    )
                    return {"http_status": 200, "body": body}
                if path == "/api/services":
                    return {"http_status": 200, "body": [{"domain": "light", "services": {}}]}
                return {"http_status": 404, "body": {"message": "Synthetic endpoint not found"}}

            def prepare(kind: str, goal: str, conversation=None, profile=None, references=None):
                with factory() as db:
                    if conversation is None:
                        chat = Conversation(title="Synthetic evaluation", manual_title=True)
                        target = Integration(
                            name="Synthetic " + kind,
                            kind=kind,
                            enabled=True,
                            writes_enabled=False,
                            config=json.dumps(
                                {
                                    "kind": kind,
                                    "auth": "none",
                                    "url": (
                                        "https://synthetic-ha.example.invalid"
                                        if kind == "home_assistant"
                                        else "https://synthetic-archive.example.invalid"
                                    ),
                                }
                            ),
                        )
                        db.add_all([chat, target])
                        db.flush()
                        db.add(
                            IntegrationBinding(
                                scope="conversation",
                                owner_id=chat.id,
                                integration_ids=json.dumps([target.id]),
                            )
                        )
                        db.add(
                            AgentPolicy(
                                integration_id=target.id,
                                profile_revision=target.revision,
                                rules=Rules(
                                    enabled=True,
                                    http_prefixes=["/api/"],
                                    http_methods=["GET"],
                                    max_effects=0,
                                    max_steps=6,
                                    timeout_seconds=300,
                                ).model_dump_json(),
                            )
                        )
                        db.flush()
                    else:
                        chat, target = (
                            db.get(Conversation, conversation),
                            db.get(Integration, profile),
                        )
                    job = runtime.create_job(
                        db,
                        cfg,
                        scope="conversation",
                        owner_id=chat.id,
                        conversation_id=chat.id,
                        request_id=str(uuid4()),
                        goal=goal,
                        research_allowed=False,
                        read_only=True,
                    )
                    if references:
                        profiles = runtime.gate(db, cfg, job)
                        job.context = json.dumps(bind(db, job, references, profiles))
                    db.commit()
                    return job.id, chat.id, target.id

            async def run_case(case_id, kind, goal, **kwargs):
                start = len(calls)
                diagnostic_start = len(model_diagnostics)
                job_id, chat, profile = prepare(kind, goal, **kwargs)
                await runtime.execute_agent(factory, cfg, Providers(cfg), job_id)
                with factory() as db:
                    job = db.get(AgentJob, job_id)
                    steps = runtime.steps(db, job_id)
                    model_steps = [s for s in steps if s.kind == "model" and s.model_run_id]
                    models = [db.get(Run, s.model_run_id) for s in model_steps]
                    source = Message(
                        conversation_id=chat,
                        role="assistant",
                        content=job.summary,
                        agent_job_id=job.id,
                    )
                    db.add(source)
                    db.commit()
                    db.expunge(source)
                    case_calls = calls[start:]
                    result = {
                        "case_id": case_id,
                        "status": job.status,
                        "model_calls": len(models),
                        "model_runs": [{"status": r.status, "error": private_error_info(r.error)}
                                       for r in models],
                        "model_diagnostics": model_diagnostics[diagnostic_start:],
                        "error_steps": [
                            {"status": step.status,
                             "error_type": (
                                 json.loads(step.document).get("type")
                                 if json.loads(step.document).get("type") in SAFE_ERROR_TYPES
                                 else "unrecognized_error"
                             ),
                             "error_reason": private_error_info(
                                 json.loads(step.result).get("reason")
                                 or json.loads(step.document).get("reason")),
                             "document_sha256": hashlib.sha256(step.document.encode()).hexdigest()}
                            for step in steps if step.kind == "error" or step.status == "failed"
                        ],
                        "successful_model_calls": sum(r.status == "succeeded" for r in models),
                        "all_model_calls_local": all(r.provider == "local" for r in models),
                        "tool_reads": len(case_calls),
                        "has_bound_displayed_source": any(
                            str(part.get("source_id", "")).startswith("agent-read:")
                            for part in json.loads(job.context)
                        ),
                        "no_effects": not any(s.kind == "effect" for s in steps),
                        "summary_sha256": hashlib.sha256(job.summary.encode()).hexdigest(),
                        "synthetic_trace": synthetic_trace(job, steps),
                    }
                    return result, source, chat, profile, job.summary, case_calls

            results = []
            with patched_attributes(
                [
                    (execution, "runtime_provider", local_runtime_provider),
                    (Providers, "stream", local_stream),
                    (runtime, "invoke", synthetic_invoke),
                    (httpx.AsyncClient, "send", observed_send),
                ]
            ):
                try:
                    if diagnostic_case != "archive_search_followup":
                        item, _, _, _, summary, case_calls = await run_case(
                            "ha_sensor_inventory",
                            "home_assistant",
                            "Welche Sensoren habe ich in Home Assistant?",
                        )
                        item["grade_checks"] = grade_case(
                            item["case_id"], item, summary, case_calls
                        )
                        item["passed"] = all(item["grade_checks"].values())
                        results.append(item)
                        if diagnostic_case == "ha_sensor_inventory":
                            return evaluation_report(results, diagnostic_case=diagnostic_case)
                    item, message, chat, target, summary, case_calls = await run_case(
                        "archive_search",
                        "paperless",
                        "Finde meinen ALPHA Vertrag in Paperless.",
                    )
                    item["grade_checks"] = grade_case(item["case_id"], item, summary, case_calls)
                    item["passed"] = all(item["grade_checks"].values())
                    results.append(item)
                    item, _, _, _, summary, case_calls = await run_case(
                        "archive_followup",
                        "paperless",
                        "Was steht darin zur Kündigungsfrist?",
                        conversation=chat,
                        profile=target,
                        references=[message],
                    )
                    item["grade_checks"] = grade_case(item["case_id"], item, summary, case_calls)
                    item["passed"] = all(item["grade_checks"].values())
                    results.append(item)
                    if diagnostic_case == "archive_search_followup":
                        return evaluation_report(results, diagnostic_case=diagnostic_case)
                    scenario["empty"] = True
                    item, _, _, _, summary, case_calls = await run_case(
                        "archive_empty",
                        "paperless",
                        "Finde meine BETA Unterlagen in Paperless.",
                    )
                    item["grade_checks"] = grade_case(item["case_id"], item, summary, case_calls)
                    item["passed"] = all(item["grade_checks"].values())
                    results.append(item)
                    return evaluation_report(results)
                finally:
                    factory.kw["bind"].dispose()
                    engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-reviewed-in-container", action="store_true")
    parser.add_argument("--diagnostic-case",
                        choices=["ha_sensor_inventory", "archive_search_followup"])
    args = parser.parse_args()
    if not args.execute_reviewed_in_container:
        print(
            json.dumps(
                {
                    "prepare_only": True,
                    "model_calls": 0,
                    "target_calls": 0,
                    "requires_reviewed_container_opt_in": True,
                    "cases": [
                        "ha_sensor_inventory",
                        "archive_search",
                        "archive_followup",
                        "archive_empty",
                    ],
                    "production_writes": 0,
                }
            )
        )
        return
    try:
        result = asyncio.run(evaluate(diagnostic_case=args.diagnostic_case))
    except Exception as error:
        result = {
            "passed": False,
            "synthetic_only": True,
            "error_type": type(error).__name__,
            "production_reads": SQL_COUNTS["reads"],
            "production_blocked_writes": SQL_COUNTS["blocked_writes"],
        }
    print(json.dumps(result))
    raise SystemExit(0 if result.get("passed") else 1)


if __name__ == "__main__":
    main()
