"""Saved immutable Office revisions stay readable under tighter formula auditing."""

import json

import pytest
from hub.artifact_specs import ArtifactSpec
from hub.artifacts import digest, info, spec_for
from hub.db import ArtifactRevision
from pydantic import ValidationError


def data(rows, totals=None):
    sheet = {"name": "Input", "columns": ["Item", "Amount", "Result"], "rows": rows}
    if totals:
        sheet["totals"] = totals
    return {"plan": {"kind": "xlsx", "title": "Saved spreadsheet", "sheets": [sheet]}}


def saved_revision(document):
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return ArtifactRevision(
        artifact_id="11111111-1111-4111-8111-111111111111",
        revision=1,
        request_key="22222222-2222-4222-8222-222222222222",
        spec=encoded,
        spec_sha256=digest(encoded),
        status="needs_review",
    )


def duplicate_total():
    return data(
        [["First", 12, None], ["Second", 24, None], ["Total", {"formula": "=SUM(B2:B3)"}, None]],
        {"B": "sum"},
    )


def test_saved_duplicate_total_is_readable_but_new_revision_must_be_fixed():
    document = duplicate_total()
    row = saved_revision(document)
    original, original_hash = row.spec, row.spec_sha256
    legacy = spec_for(row)
    assert legacy.plan.sheets[0].rows[2][1].formula == "=SUM(B2:B3)"
    assert row.spec == original and row.spec_sha256 == original_hash
    with pytest.raises(ValidationError):
        ArtifactSpec.model_validate(legacy.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        ArtifactSpec.model_validate(document)


def test_saved_duplicate_total_gets_visible_warning_without_changing_status():
    row = saved_revision(duplicate_total())
    result = info(row)
    assert result["formula_warnings"]
    assert result["status"] == "needs_review"
    assert result["spec_sha256"] == row.spec_sha256
    assert result["spec"]["plan"]["sheets"][0]["totals"] == {"B": "sum"}


def test_saved_valid_formulas_have_no_warning():
    row = saved_revision(data([["First", 12, {"formula": "=B2*2"}]], {"B": "sum"}))
    assert not info(row).get("formula_warnings")


def test_saved_spec_integrity_is_verified_before_legacy_parsing():
    row = saved_revision(duplicate_total())
    row.spec_sha256 = "0" * 64
    with pytest.raises(ValueError, match="verändert"):
        spec_for(row)


@pytest.mark.parametrize(
    "formula",
    ["=1+", "=IF(1)", "=ROUND(1,2,3)", '=SUMIF(A2:A3,"First",B2:B2)', "=1e999"],
)
def test_legacy_new_audit_issues_stay_readable_but_warn(formula):
    document = data([["First", 12, {"formula": formula}], ["Second", 24, None]])
    row = saved_revision(document)
    assert spec_for(row).plan.sheets[0].rows[0][2].formula == formula
    assert info(row)["formula_warnings"]
    with pytest.raises(ValidationError):
        ArtifactSpec.model_validate(document)


@pytest.mark.parametrize(
    "formula",
    [
        '=WEBSERVICE("https://invalid.example")',
        "='[private.xlsx]Sheet1'!A2",
        "=SUM(B2:B9)",
        "=C2",
    ],
)
def test_legacy_read_keeps_baseline_safety_checks(formula):
    row = saved_revision(data([["First", 12, {"formula": formula}]]))
    with pytest.raises(ValueError):
        spec_for(row)
