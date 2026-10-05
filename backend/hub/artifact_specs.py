"""Bounded data plans for offline artifacts; never executable model output."""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class StrictPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_serializer(mode="wrap")
    def compatible_data(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        # Absent extensions retain the exact canonical shape of existing V1
        # requests and receipts. Never invalidate an old immutable version.
        for key in ("images", "pdf_export", "caption"):
            if not data.get(key):
                data.pop(key, None)
        if data.get("kind") == "pdf" and not data.get("sections"):
            data.pop("sections", None)
        return data


class SourceBinding(StrictPlan):
    id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    revision: int = Field(ge=1, le=100000)
    sha256: Digest


class DocumentImage(StrictPlan):
    source: int = Field(ge=0, le=19)
    caption: str = Field(default="", max_length=160)
    width_inches: float = Field(default=5.5, ge=0.5, le=6.5)


class Section(StrictPlan):
    heading: Short
    paragraphs: list[Body] = Field(default_factory=list, max_length=30)
    table: list[list[Short]] = Field(default_factory=list, max_length=30)
    images: list[DocumentImage] = Field(default_factory=list, max_length=4)

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
    pdf_export: bool = False

    @model_validator(mode="after")
    def image_limit(self) -> "DocumentPlan":
        if sum(len(section.images) for section in self.sections) > 12:
            raise ValueError("Maximal zwölf Bilder je Dokument")
        return self


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
    pages: list[PageSelection] = Field(default_factory=list, max_length=100)
    sections: list[Section] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def one_mode(self) -> "PdfPlan":
        if bool(self.pages) == bool(self.sections):
            raise ValueError("PDF benötigt entweder Seiten oder Dokumentinhalt")
        if sum(len(section.images) for section in self.sections) > 12:
            raise ValueError("Maximal zwölf Bilder je Dokument")
        return self


class ImageTile(StrictPlan):
    source: int = Field(ge=0, le=19)
    crop: tuple[float, float, float, float] = (0, 0, 1, 1)
    caption: str = Field(default="", max_length=140)

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


Plan = Annotated[DocumentPlan | PresentationPlan | PdfPlan | ImagePlan, Field(discriminator="kind")]


class ArtifactSpec(StrictPlan):
    version: Literal[1] = 1
    label: Literal["LOCAL_ONLY"] = "LOCAL_ONLY"
    sources: list[SourceBinding] = Field(default_factory=list, max_length=20)
    plan: Plan

    @model_validator(mode="after")
    def source_indices(self) -> "ArtifactSpec":
        if len({s.id for s in self.sources}) != len(self.sources):
            raise ValueError("Quelle darf nur einmal gebunden sein")
        selections: list[Any] = (
            self.plan.pages
            if isinstance(self.plan, PdfPlan)
            else self.plan.tiles
            if isinstance(self.plan, ImagePlan)
            else []
        )
        if isinstance(self.plan, DocumentPlan) or (
            isinstance(self.plan, PdfPlan) and self.plan.sections
        ):
            selections = [image for section in self.plan.sections for image in section.images]
        if any(item.source >= len(self.sources) for item in selections):
            raise ValueError("Quelldatei fehlt")
        return self
