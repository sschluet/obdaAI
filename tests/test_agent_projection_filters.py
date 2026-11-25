"""A requested filter must never silently become an unfiltered read."""

import pytest
from hub.agent_context import project
from hub.agent_native import NativeCallError, decode_calls
from hub.agent_tools import Projection
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_agent_native import call, http_binding, prepared


@pytest.mark.parametrize("filter_value", [
    {"where_prefix": "update."}, {"where_prefix": ""},
    {"where_equals": False}, {"where_equals": 0}, {"where_equals": ""},
])
@pytest.mark.parametrize("pointer", [{}, {"where_pointer": None}])
def test_filter_without_pointer_is_rejected_at_schema_and_tool_boundary(filter_value, pointer):
    invalid = {**pointer, **filter_value}
    assert not Draft202012Validator(Projection.model_json_schema()).is_valid(invalid)
    with pytest.raises(ValidationError, match="filter requires where_pointer"):
        Projection.model_validate(invalid)
    native = prepared()
    with pytest.raises(NativeCallError) as caught:
        decode_calls(native.metadata, [call(http_binding(native), {
            "method": "GET", "path": "/api/one/states", "projection": invalid,
        })])
    assert "schema_type:where_pointer:string" in caught.value.issues
    assert not any("update." in issue for issue in caught.value.issues)


@pytest.mark.parametrize("expected", [None, False, 0, ""])
def test_explicit_pointer_preserves_null_false_zero_and_empty_filters(expected):
    rule = Projection(where_pointer="/value", where_equals=expected).model_dump()
    assert Draft202012Validator(Projection.model_json_schema()).is_valid(rule)
    body = [{"value": value} for value in [None, False, 0, ""]]
    result = project(body, rule)
    assert result["matched"] == result["returned"] == 1
    assert type(result["items"][0]["value"]) is type(expected)
    assert result["items"][0]["value"] == expected


def test_no_filter_remains_an_explicit_unfiltered_projection():
    rule = Projection(limit=2).model_dump()
    assert Draft202012Validator(Projection.model_json_schema()).is_valid(rule)
    assert project([1, 2, 3], rule) == {"items": [1, 2], "matched": 3, "returned": 2}
