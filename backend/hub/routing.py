import math
import re
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


def conversational_research(route: Route, request: str, *, private_context: bool) -> Route:
    """Narrow a definite text-research request; never add an action or a grant.

    Only the latest authenticated request is eligible. Topics such as future
    services or workflows are not scheduled actions. Ambiguous or mixed requests
    retain the classifier result and all existing execution gates.
    """
    direct = re.search(
        r"^\s*(?:(?:bitte|please)\s+)?(?:"
        r"(?:erstelle|erarbeite|verfasse|create|write|prepare)\s+"
        r"(?:(?:eine?|an?|the)\s+)?(?:(?:komplexe?|umfassende?|detaillierte?|"
        r"ausführliche?|gründliche?|complex|comprehensive|detailed|in-depth)\s+)*"
        r"(?:recherche|research|analyse|analysis)\b|recherchiere\b|research\b)",
        request,
        re.I,
    )
    if not direct:
        return route
    # Explicit outputs, private-source commands and further imperative clauses
    # are deliberately excluded rather than silently dropping requested work.
    explicit = re.search(
        r"\b(?:docx|pptx|pdf|word|powerpoint|präsentation|presentation|datei|file|"
        r"download|herunterlad\w*|anhang|attachment|vault|projektunterlagen|"
        r"projektquellen|hochgeladen\w*|uploaded|dokument\w*|documents?)\b|"
        r"\.(?:xlsx?|csv|txt|md|docx?|pptx?|pdf|png|jpe?g)\b|"
        r"\b(?:als|as)\s+(?:(?:eine?|an?)\s+)?(?:aufgabe|task|workflow)\b|"
        r"\b(?:jeden|jede|täglich|wöchentlich|daily|weekly|every)\b|"
        r"\b(?:aus|in|from)\s+(?:(?:den|dem|the|my|meinen)\s+)?"
        r"(?:dokument\w*|documents?|datei\w*|files?|vault)\b|"
        r"\b(?:plane|planen|schedule|scheduled|scheduling|erinnere|remind|"
        r"aktiviere|activate|führe|execute|run|automatisiere|automate|installiere|"
        r"install|repariere|repair|ändere|change|speichere|save|sende|send|"
        r"prüfe|inspect|check|lösche|delete|starte|start|stoppe|stop|aktualisiere|update|"
        r"neustart\w*|restart|reboot|deploy\w*|nutze|benutze|use|"
        r"exportiere|export|erstelle|create|generiere|generate)\b",
        request[direct.end() :],
        re.I,
    )
    if explicit:
        return route
    allowed = {Capability.CHAT, Capability.WEB}
    if private_context:
        allowed.add(Capability.RETRIEVAL)
    capabilities = [cap for cap in route.capabilities if cap in allowed]
    if Capability.CHAT not in capabilities:
        capabilities.insert(0, Capability.CHAT)
    return route.model_copy(
        update={
            "capabilities": capabilities,
            "answer": None,
            "read_tool": None,
            "reason": "Textrecherche; keine Datei oder Systemaktion angefordert",
        }
    )
