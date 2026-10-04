"""Fail closed at every outbound boundary. Router output never grants permission."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Privacy(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    CLOUD_ALLOWED = "CLOUD_ALLOWED"


class ContextPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    label: Privacy = Privacy.LOCAL_ONLY
    source_id: str
    revision: int = Field(ge=1)


class CloudGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    revision: int = Field(ge=1)
    provider_id: str


def check_egress(
    parts: list[ContextPart], *, external: bool, provider_id: str, grants: list[CloudGrant]
) -> None:
    if not external:
        return
    approved = {(g.source_id, g.revision, g.provider_id) for g in grants}
    for part in parts:
        if part.label != Privacy.CLOUD_ALLOWED:
            raise PermissionError("LOCAL_ONLY context cannot leave the local boundary")
        if (part.source_id, part.revision, provider_id) not in approved:
            raise PermissionError("Missing explicit source/revision/provider grant")


def derived_label(parts: list[ContextPart]) -> Privacy:
    if not parts or any(p.label == Privacy.LOCAL_ONLY for p in parts):
        return Privacy.LOCAL_ONLY
    return Privacy.CLOUD_ALLOWED
