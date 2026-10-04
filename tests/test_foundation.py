import pytest
from fastapi.testclient import TestClient
from hub.api import app
from hub.policy import CloudGrant, ContextPart, Privacy, check_egress, derived_label
from hub.routing import Route
from pydantic import ValidationError


def part(label: Privacy = Privacy.LOCAL_ONLY, revision: int = 1) -> ContextPart:
    return ContextPart(content="synthetic", source_id="fixture", revision=revision, label=label)


def test_health() -> None:
    assert TestClient(app).get("/api/health").json()["privacy_default"] == "LOCAL_ONLY"


@pytest.mark.parametrize("destination", ["openrouter", "web_search", "embedding", "n8n"])
def test_local_only_never_egresses(destination: str) -> None:
    grant = CloudGrant(source_id="fixture", revision=1, provider_id=destination)
    with pytest.raises(PermissionError):
        check_egress([part()], external=True, provider_id=destination, grants=[grant])


def test_grants_bound_to_revision_and_provider() -> None:
    grant = CloudGrant(source_id="fixture", revision=1, provider_id="openrouter")
    check_egress(
        [part(Privacy.CLOUD_ALLOWED)], external=True, provider_id="openrouter", grants=[grant]
    )
    for provider, revision in [("other", 1), ("openrouter", 2)]:
        with pytest.raises(PermissionError):
            check_egress(
                [part(Privacy.CLOUD_ALLOWED, revision)],
                external=True,
                provider_id=provider,
                grants=[grant],
            )


def test_derivatives_keep_restrictions() -> None:
    assert derived_label([part(Privacy.CLOUD_ALLOWED), part()]) == Privacy.LOCAL_ONLY
    assert derived_label([]) == Privacy.LOCAL_ONLY


def test_capabilities_are_independent_of_model() -> None:
    route = Route(
        capabilities=["web", "retrieval", "artifact"], model_class="local", reason="synthetic"
    )
    assert len(route.capabilities) == 3


def test_router_cannot_grant_permissions() -> None:
    with pytest.raises(ValidationError):
        Route.model_validate(
            {
                "capabilities": ["chat"],
                "model_class": "cloud",
                "reason": "synthetic",
                "grant_cloud": True,
            }
        )


def test_inline_answer_cannot_fake_tool_work() -> None:
    with pytest.raises(ValidationError):
        Route(capabilities=["tool"], model_class="local", reason="synthetic", answer="done")


@pytest.mark.parametrize("number,text", [(4, "4"), (4.0, "4"), (0, "0"), (2.5, "2.5")])
def test_numeric_inline_answer_keeps_model_and_capability_rules(number, text):
    value = {
        "capabilities": ["chat"],
        "model_class": "local",
        "reason": "arithmetic",
        "answer": number,
    }
    assert Route.model_validate(value).answer == text
    value["model_class"] = "cloud"
    with pytest.raises(ValueError):
        Route.model_validate(value)
    value["model_class"] = "local"
    value["capabilities"] = ["tool"]
    with pytest.raises(ValueError):
        Route.model_validate(value)


@pytest.mark.parametrize("invalid", [True, False, float("nan"), float("inf")])
def test_inline_answer_rejects_boolean_and_nonfinite_numbers(invalid):
    with pytest.raises(ValueError):
        Route.model_validate(
            {
                "capabilities": ["chat"],
                "model_class": "local",
                "reason": "fixture",
                "answer": invalid,
            }
        )
