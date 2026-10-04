from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Capability(StrEnum):
    CHAT = "chat"
    WEB = "web"
    RETRIEVAL = "retrieval"
    TOOL = "tool"
    ARTIFACT = "artifact"
    TASK = "task"
    WORKFLOW = "workflow"


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capabilities: list[Capability] = Field(min_length=1, max_length=7)
    model_class: Literal["local", "cloud"]
    source_scopes: list[str] = Field(default_factory=list, max_length=10)
    reason: str = Field(max_length=240)
    answer: str | None = Field(default=None, max_length=16000)

    @model_validator(mode="after")
    def valid(self) -> "Route":
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("Duplicate capabilities")
        if self.answer and (self.model_class != "local" or self.capabilities != [Capability.CHAT]):
            raise ValueError("Inline answers are restricted to simple local chat")
        return self
