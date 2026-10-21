"""Synthetic whole-display evidence, distinct from mailbox completeness."""

import json

import pytest
from hub import agent_mail_cohort as cohort
from hub import agent_read_references as refs
from hub.action_api import digest, encode
from hub.agent_models import AgentStep
from hub.agent_runtime import mail_overview_summary
from test_agent_read_references import receipt  # noqa: F401


@pytest.fixture
def context(receipt):  # noqa: F811
    db, job, source, message, step, profile, policy, profiles = receipt
    source.goal = "Was gab es heute für neue Mails?"
    source.bindings = encode(
        {
            **json.loads(source.bindings),
            "clock": {
                "today_start": "2026-10-21T00:00:00+02:00",
                "today_end_exclusive": "2026-10-22T00:00:00+02:00",
            },
        }
    )
    rules = profiles[profile.id][1]
    rules.mcp_read_tools.update({"read_email": "b" * 64, "list_folders": "c" * 64})
    policy.rules = rules.model_dump_json()
    return receipt


def freeze(context, rows):
    db, job, source, message, step, _, _, profiles = context
    step.result = encode({"response": {"content": [encode({"messages": rows})]}})
    clock = json.loads(source.bindings)["clock"]
    source.summary = mail_overview_summary([step], clock, source.goal, profiles)
    message.content = source.summary
    job.context = encode(refs.bind(db, job, [message], profiles))
    db.flush()


def row(uid, **updates):
    return {
        "uid": uid,
        "message_id": f"<{uid}@synthetic.invalid>",
        "folder": "INBOX",
        "subject": f"Synthetic {uid}",
        "received": "2026-10-21T09:00:00+02:00",
        **updates,
    }


def call(context, history=None):
    return cohort.cohort_evidence(context[0], context[1], context[-1], history or [])


def current(context, name, payload, seq=1):
    _, job, _, _, original, profile, _, _ = context
    document = json.loads(original.document)
    document["arguments"] = {
        "name": name,
        "schema_sha256": ("c" * 64 if name == "list_folders" else "b" * 64),
        "arguments": {},
    }
    return AgentStep(
        job_id=job.id,
        sequence=seq,
        kind="read",
        status="succeeded",
        document=encode(document),
        sha256=digest(encode(document)),
        result=encode({"response": {"content": [encode(payload)]}}),
    )


def test_whole_display_flags_and_false_is_not_negative(context):
    freeze(context, [row(1, answered=True), row(2, answered=False), row(3)])
    result = call(context)
    assert result["cohort_known"] is True
    assert result["rows"] == [
        [1, True, False, None],
        [2, False, False, None],
        [3, None, False, None],
    ]
    assert result["unknown_flag_count"] == 1
    assert result["marked_answered_count"] == 1
    assert result["false_flag_means_unanswered"] is False
    assert result["sent_coverage_complete"] is False
    assert not context[0].dirty


def test_window_sort_dedup_and_cap_before_flags(context):
    rows = [row(99, received="2026-10-20T09:00:00+02:00", answered=True)]
    rows += [row(n, answered=n % 2 == 0) for n in range(1, 25)]
    rows.insert(3, row(1, answered=False))
    freeze(context, rows)
    selected = cohort.selected_receipt_rows(context[0], context[1], context[-1])
    assert [r["row"]["uid"] for r in selected["rows"]] == list(range(1, 21))
    result = call(context)
    assert result["displayed_count"] == 20
    assert len(result["rows"]) == 20
    assert len(encode(result).encode()) <= 1400
    assert result["unknown_flag_count"] == 0


def test_unknown_dates_kept_after_actual_window_and_end_excluded(context):
    freeze(
        context, [row(1, received="unknown"), row(2), row(3, received="2026-10-22T00:00:00+02:00")]
    )
    selected = cohort.selected_receipt_rows(context[0], context[1], context[-1])
    assert [r["row"]["uid"] for r in selected["rows"]] == [2, 1]


@pytest.mark.parametrize("change", ["summary", "content", "goal", "clock"])
def test_cannot_reconstruct_edited_source(context, change):
    freeze(context, [row(1)])
    _, _, source, message, _, _, _, _ = context
    if change == "summary":
        source.summary = "unverified alternate answer"
    elif change == "content":
        message.content = "edited source prose"
    elif change == "goal":
        source.goal = "unsupported detailed analysis"
    else:
        source.bindings = encode({**json.loads(source.bindings), "clock": {}})
    assert call(context)["cohort_known"] is False


@pytest.mark.parametrize("change", ["revoked", "revision", "result"])
def test_current_revocation_gate_not_bypassed(context, change):
    freeze(context, [row(1)])
    if change == "revoked":
        context[5].enabled = False
    elif change == "revision":
        context[3].revision += 1
    else:
        context[4].result += " "
    with pytest.raises(PermissionError):
        call(context)


def test_current_exact_flag_refresh_and_sent_positive(context):
    freeze(context, [row(1, answered=False), row(2)])
    detail = current(context, "read_email", row(1, answered=True))
    sent = current(
        context, "read_email", row(88, folder="Sent", in_reply_to="<2@synthetic.invalid>"), 2
    )
    folders = current(
        context, "list_folders", [{"name": "Sent", "flags": ["\\Sent"], "selectable": True}], 3
    )
    result = call(context, [detail, sent, folders])
    assert result["rows"] == [[1, True, True, None], [2, None, False, True]]
    assert result["current_flag_count"] == 1


@pytest.mark.parametrize(
    "variant", ["all_mail", "foreign_account", "other_id", "tampered", "wrong_job"]
)
def test_unrelated_or_unbound_details_never_prove_reply(context, variant):
    freeze(context, [row(1, answered=False)])
    candidate = row(77, folder="Sent", references="<1@synthetic.invalid>", answered=True)
    folders = current(
        context, "list_folders", [{"name": "Sent", "flags": ["\\Sent"], "selectable": True}], 2
    )
    if variant == "all_mail":
        candidate["folder"] = "All Mail"
    elif variant == "other_id":
        candidate["references"] = "<foreign@synthetic.invalid>"
    sent = current(context, "read_email", candidate)
    if variant == "foreign_account":
        document = json.loads(sent.document)
        document["integration_id"] = "different-account"
        sent.document, sent.sha256 = encode(document), digest(encode(document))
    elif variant == "tampered":
        sent.sha256 = "0" * 64
    elif variant == "wrong_job":
        sent.job_id = "other-job"
    assert call(context, [sent, folders])["rows"] == [[1, False, False, None]]


def test_unbound_query_cannot_silently_expand_original_display(context):
    freeze(context, [row(1)])
    _, _, source, message, step, _, _, profiles = context
    other = AgentStep(
        job_id=source.id,
        sequence=2,
        kind="read",
        status="succeeded",
        document=step.document,
        sha256=step.sha256,
        result=encode({"response": {"content": [encode({"messages": [row(2)]})]}}),
    )
    source.summary = mail_overview_summary(
        [step, other], json.loads(source.bindings)["clock"], source.goal, profiles
    )
    message.content = source.summary
    assert call(context)["cohort_known"] is False


def test_empty_verified_cohort(context):
    freeze(context, [])
    result = call(context)
    assert result["cohort_known"] is True and result["rows"] == []


def test_real_two_account_binding_and_display_ordinals(context):
    from hub.agent_models import AgentPolicy
    from hub.integrations import Integration

    db, job, source, message, step, profile, policy, profiles = context
    second = Integration(
        kind=profile.kind, name="Second synthetic mailbox", enabled=True, config=profile.config
    )
    db.add(second)
    db.flush()
    second_policy = AgentPolicy(
        integration_id=second.id, profile_revision=second.revision, rules=policy.rules
    )
    db.add(second_policy)
    db.flush()
    profiles[second.id] = (second, profiles[profile.id][1], profiles[profile.id][2])
    for bound in (source, job):
        bindings = json.loads(bound.bindings)
        bindings["profiles"].append(
            {
                "id": second.id,
                "profile_revision": second.revision,
                "policy_revision": second_policy.revision,
            }
        )
        bound.bindings = encode(bindings)
    first_rows = [row(n, answered=True) for n in range(1, 11)]
    freeze(context, first_rows)
    document = json.loads(step.document)
    document["integration_id"] = second.id
    other = AgentStep(
        job_id=source.id,
        sequence=2,
        kind="read",
        status="succeeded",
        document=encode(document),
        sha256=digest(encode(document)),
        result=encode(
            {
                "response": {
                    "content": [
                        encode(
                            {
                                "messages": [
                                    row(n, answered=False, received="2026-10-21T10:00:00+02:00")
                                    for n in range(1, 11)
                                ]
                            }
                        )
                    ]
                }
            }
        ),
    )
    other.created = step.created
    db.add(other)
    db.flush()
    source.summary = mail_overview_summary(
        [step, other], json.loads(source.bindings)["clock"], source.goal, profiles
    )
    message.content = source.summary
    job.context = encode(refs.bind(db, job, [message], profiles))
    db.flush()
    selected = cohort.selected_receipt_rows(db, job, profiles)
    assert [r["integration_id"] for r in selected["rows"]] == [profile.id] * 10 + [second.id] * 10
    result = call(context)
    assert result["cohort_known"] is True
    assert [r[1] for r in result["rows"]] == [True] * 10 + [False] * 10
    assert len(encode(result).encode()) <= 1400


def test_same_uid_different_message_id_cannot_refresh(context):
    freeze(context, [row(1, answered=False)])
    detail = current(
        context, "read_email", row(1, message_id="<replacement@synthetic.invalid>", answered=True)
    )
    assert call(context, [detail])["rows"] == [[1, False, False, None]]


def test_unknown_display_still_keeps_bounded_current_actual_proof(context):
    freeze(context, [row(1)])
    context[2].summary = "A source answer that is not the deterministic overview"
    detail = current(context, "read_email", row(1, answered=True))
    result = call(context, [detail])
    assert result["cohort_known"] is False
    assert result["proofs"][0]["marked_answered"] is True
    assert len(encode(result).encode()) <= 1400


def test_remote_account_field_cannot_cross_join_current_sent_copy(context):
    freeze(context, [row(1, answered=False, account_id="forged-remote")])
    detail = current(context, "read_email", row(1, answered=True, account_id="forged-other"))
    result = call(context, [detail])
    assert result["rows"] == [[1, True, True, None]]


def test_oversized_subjects_never_remove_ordinal_statuses(context):
    freeze(
        context, [row(n, answered=True, subject="Large 😸 subject " * 200) for n in range(1, 21)]
    )
    result = call(context)
    assert len(result["rows"]) == 20 and result["examples_omitted"] > 0
    assert len(encode(result).encode()) <= 1400
