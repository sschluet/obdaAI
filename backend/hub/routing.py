import math
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    read_tool: (
        Literal["hub.inspect", "ha.inspect", "ha.backups.inspect", "ha.maintenance.plan"] | None
    ) = None

    @field_validator("answer", mode="before")
    @classmethod
    def numeric_answer(cls, value: object) -> object:
        # A JSON number is a complete arithmetic answer, not a new capability.
        # Booleans and non-finite values remain invalid. Scope checks stay strict.
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        if isinstance(value, float) and math.isfinite(value):
            return str(int(value)) if value.is_integer() else str(value)
        return value

    @model_validator(mode="after")
    def valid(self) -> "Route":
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("Duplicate capabilities")
        if self.read_tool is not None and Capability.TOOL not in self.capabilities:
            raise ValueError("Read selector requires tool capability")
        if self.answer and (self.model_class != "local" or self.capabilities != [Capability.CHAT]):
            raise ValueError("Inline answers are restricted to simple local chat")
        return self
