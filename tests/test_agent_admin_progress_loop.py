"""Actual worker/native/SSE loop: repair no-progress, preserve partial goal evidence."""

from test_agent_native_loop import scenario

pytest_plugins = ["test_agent_capability_runtime"]


def test_admin_duplicate_inventory_is_not_redispatched_and_changes_refresh_normally(
    ha, monkeypatch, tmp_path
):
    result, requests, calls = scenario(
        ha,
        monkeypatch,
        tmp_path,
        repeat_inventory=True,
        goal_outcome=True,
    )
    assert result["status"] == "succeeded"
    duplicate_feedback = [
        s
        for s in result["steps"]
        if s["kind"] == "feedback"
        and any(issue["type"] == "read_already_observed" for issue in s["document"]["issues"])
    ]
    assert len(duplicate_feedback) == 1
    feedback_text = duplicate_feedback[0]["document"]["issues"][0]["next_action"]
    assert "execution_state" in feedback_text
    assert "read-only job" not in feedback_text
    assert len([call for call in calls if call[1:] == ("GET", "/api/states")]) == 3
    assert len([call for call in calls if call[1] == "POST"]) == 2
    assert len([call for call in calls if call[0] == "http.verify"]) == 2
    assert len(requests) == 8


def test_backup_plus_one_verified_update_does_not_finish_another_pending_update(
    ha, monkeypatch, tmp_path
):
    result, _, calls = scenario(
        ha,
        monkeypatch,
        tmp_path,
        goal_outcome=True,
        remaining_update=True,
    )
    assert result["status"] == "unverified"
    assert len([call for call in calls if call[1] == "POST"]) == 2
    assert (
        len(
            [
                s
                for s in result["steps"]
                if s["kind"] == "effect" and s["result"].get("effect_verified")
            ]
        )
        == 2
    )
    assert "Synthetic backup and pending update verified." not in result["summary"]
    assert not any(s["status"] in {"prepared", "dispatching"} for s in result["steps"])


def test_legacy_unbound_entity_goal_remains_partial_after_verified_effects(
    ha, monkeypatch, tmp_path
):
    result, _, calls = scenario(
        ha,
        monkeypatch,
        tmp_path,
        goal_outcome=False,
        remaining_update=True,
        goal="Bitte aktualisiere die ausgewählten Komponenten in Home Assistant.",
    )
    assert result["status"] == "unverified"
    assert len([call for call in calls if call[1] == "POST"]) == 2
    assert "Synthetic backup and pending update verified." not in result["summary"]


def test_final_boundary_blocks_premature_backup_then_reports_empty_selection_without_effects(
    ha, monkeypatch
):
    import asyncio

    from hub import agent_runtime as runtime
    from hub.agent_intent import EntityOutcome, RequestIntent, Requirement
    from test_agent_capability_runtime import start

    app, client, _, cfg, target, *_ = ha
    chosen = []
    calls = []

    async def generate(factory, settings, providers, job_id, instruction, data):
        if data.get("intent_schema"):
            return RequestIntent(
                target_ids=[target],
                mode="admin",
                topic="system",
                requirements=[
                    Requirement(kind="entity_states", domain="update", integration_id=target),
                    Requirement(
                        kind="effect_postcondition",
                        integration_id=target,
                        outcome=EntityOutcome(
                            domain="update",
                            state="off",
                            scope="all_observed",
                            selection_state="on",
                            attribute_from_initial={"installed_version": "latest_version"},
                        ),
                    ),
                ],
            ).model_dump()
        chosen.append(data)
        if len(chosen) == 1:
            # Deliberately bypass model-schema compliance to test the actual final gate.
            return {
                "kind": "tool",
                "integration_id": target,
                "tool": "http",
                "message": "Backup",
                "arguments": {"method": "POST", "path": "/api/services/backup/create"},
            }
        if len(chosen) == 2:
            return {
                "kind": "tool",
                "integration_id": target,
                "tool": "http",
                "message": "Read",
                "arguments": {"method": "GET", "path": "/api/states"},
            }
        assert data["allow_finish"] and data["remaining_effects"] > 0
        return {"kind": "finish", "message": "SYNTHETIC_UNSUPPORTED_ALL_INSTALLED_CLAIM"}

    def invoke(cfg, config, secret, tool, args, rules, before_send):
        before_send()
        calls.append(args)
        assert args["method"] == "GET"
        body = (
            [{"entity_id": "update.synthetic", "state": "off"}]
            if (args["path"] == "/api/states")
            else {"message": "API running."}
        )
        if args.get("projection") is not None:
            from hub.agent_context import project

            body = project(body, args["projection"])
        return {"http_status": 200, "body": body, "effect_verified": False}

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "invoke", invoke)
    identifier = start(
        ha,
        "Bitte prüfe Home Assistant und spiele alle ausstehenden Update ein",
        research_allowed=False,
    )
    asyncio.run(runtime.execute_agent(app.state.sessions, cfg, None, identifier))
    result = client.get("/api/agent-runs/" + identifier).json()
    assert result["status"] == "observed"
    assert not any(s["kind"] == "effect" for s in result["steps"])
    assert any(
        s["kind"] == "feedback"
        and s["document"]["issues"][0]["type"] == "initial_outcome_baseline_required"
        for s in result["steps"]
    )
    assert "SYNTHETIC_UNSUPPORTED_ALL_INSTALLED_CLAIM" not in result["summary"]
    assert "keine Einträge" in result["summary"] and len(calls) == 2
