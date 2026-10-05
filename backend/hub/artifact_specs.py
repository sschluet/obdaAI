"""Bounded data plans for offline artifacts; never executable model output."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class StrictPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceBinding(StrictPlan):
    id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    revision: int = Field(ge=1, le=100000)
    sha256: Digest


class Section(StrictPlan):
    heading: Short
    paragraphs: list[Body] = Field(default_factory=list, max_length=30)
    table: list[list[Short]] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def rectangular(self) -> "Section":
        if self.table and (
            not 1 <= len(self.table[0]) <= 6
            or any(len(row) != len(self.table[0]) for row in self.table)
        ):
            raise ValueError("Tabelle benötigt gleich viele Spalten (maximal sechs)")
        return self


class DocumentPlan(StrictPlan):
    kind: Literal["docx"]
    title: Short
    sections: list[Section] = Field(min_length=1, max_length=30)


class Slide(StrictPlan):
    title: Short
    bullets: list[Annotated[str, StringConstraints(min_length=1, max_length=140)]] = Field(
        min_length=1, max_length=5
    )
    notes: str = Field(default="", max_length=4000)


class PresentationPlan(StrictPlan):
    kind: Literal["pptx"]
    title: Short
    slides: list[Slide] = Field(min_length=1, max_length=30)


class PageSelection(StrictPlan):
    source: int = Field(ge=0, le=19)
    page: int = Field(ge=1, le=1000)
    rotation: Literal[0, 90, 180, 270] = 0


class PdfPlan(StrictPlan):
    kind: Literal["pdf"]
    title: Short
    pages: list[PageSelection] = Field(min_length=1, max_length=100)


class ImageTile(StrictPlan):
    source: int = Field(ge=0, le=19)
    crop: tuple[float, float, float, float] = (0, 0, 1, 1)

    @model_validator(mode="after")
    def bounds(self) -> "ImageTile":
        left, top, right, bottom = self.crop
        if not 0 <= left < right <= 1 or not 0 <= top < bottom <= 1:
            raise ValueError("Zuschnitt muss innerhalb des Bildes liegen")
        return self


class ImagePlan(StrictPlan):
    kind: Literal["image"]
    title: Short
    tiles: list[ImageTile] = Field(min_length=1, max_length=12)
    columns: int = Field(default=1, ge=1, le=4)
    tile_width: int = Field(default=1024, ge=128, le=2048)
    tile_height: int = Field(default=768, ge=128, le=2048)
    format: Literal["png", "jpeg"] = "png"

    @model_validator(mode="after")
    def pixel_limit(self) -> "ImagePlan":
        rows = (len(self.tiles) + self.columns - 1) // self.columns
        if rows * self.columns * self.tile_width * self.tile_height > 24_000_000:
            raise ValueError("Collage überschreitet das Pixellimit")
        return self


Plan = Annotated[
    DocumentPlan | PresentationPlan | PdfPlan | ImagePlan, Field(discriminator="kind")
]


class ArtifactSpec(StrictPlan):
    version: Literal[1] = 1
    label: Literal["LOCAL_ONLY"] = "LOCAL_ONLY"
    sources: list[SourceBinding] = Field(default_factory=list, max_length=20)
    plan: Plan

    @model_validator(mode="after")
    def source_indices(self) -> "ArtifactSpec":
        if len({s.id for s in self.sources}) != len(self.sources):
            raise ValueError("Quelle darf nur einmal gebunden sein")
        selections = (
            self.plan.pages if isinstance(self.plan, PdfPlan)
            else self.plan.tiles if isinstance(self.plan, ImagePlan) else []
        )
        if any(item.source >= len(self.sources) for item in selections):
            raise ValueError("Quelldatei fehlt")
        return self
