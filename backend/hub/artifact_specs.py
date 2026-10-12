"""Bounded data plans for offline artifacts; never executable model output."""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictFloat,
    StrictInt,
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
        for key in ("images", "pdf_export", "caption", "split_after", "template", "letter"):
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


class LetterFields(StrictPlan):
    recipient: list[Short] = Field(min_length=1, max_length=6)
    sender: list[Short] = Field(default_factory=list, max_length=6)
    subject: Short
    date: Short
    salutation: Short
    signature: list[Short] = Field(min_length=1, max_length=5)


class DocumentPlan(StrictPlan):
    kind: Literal["docx"]
    title: Short
    sections: list[Section] = Field(min_length=1, max_length=30)
    pdf_export: bool = False
    letter: LetterFields | None = None

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
    split_after: list[Annotated[int, Field(strict=True)]] = Field(
        default_factory=list, max_length=19
    )

    @model_validator(mode="after")
    def one_mode(self) -> "PdfPlan":
        if self.split_after and (
            not self.pages
            or any(type(n) is not int or not 1 <= n < len(self.pages) for n in self.split_after)
            or self.split_after != sorted(set(self.split_after))
        ):
            raise ValueError("PDF-Trennstellen müssen eindeutig aufsteigend zwischen Seiten liegen")
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


Cell = (
    Annotated[str, StringConstraints(max_length=2000)] | StrictBool | StrictInt | StrictFloat | None
)


class SpreadsheetSheet(StrictPlan):
    name: Annotated[str, StringConstraints(min_length=1, max_length=31)]
    columns: list[Short] = Field(min_length=1, max_length=20)
    rows: list[list[Cell]] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def sheet_shape(self) -> "SpreadsheetSheet":
        import math

        if any(char in self.name for char in "[]:*?/\\"):
            raise ValueError("Ungültiger Tabellenblattname")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Tabellenzeilen benötigen gleich viele Spalten")
        if any(
            isinstance(cell, float) and not math.isfinite(cell) for row in self.rows for cell in row
        ):
            raise ValueError("Tabellenzahlen müssen endlich sein")
        return self


class SpreadsheetPlan(StrictPlan):
    kind: Literal["xlsx"]
    title: Short
    sheets: list[SpreadsheetSheet] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def workbook_shape(self) -> "SpreadsheetPlan":
        if len({sheet.name.casefold() for sheet in self.sheets}) != len(self.sheets):
            raise ValueError("Tabellenblattnamen müssen eindeutig sein")
        if sum((len(sheet.rows) + 1) * len(sheet.columns) for sheet in self.sheets) > 10000:
            raise ValueError("Tabelle überschreitet das Zellenlimit")
        return self


Plan = Annotated[
    DocumentPlan | PresentationPlan | PdfPlan | ImagePlan | SpreadsheetPlan,
    Field(discriminator="kind"),
]


class TemplateBinding(StrictPlan):
    skill_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    revision: int = Field(ge=1, le=100000)
    bundle_sha256: Digest
    asset_path: str = Field(min_length=1, max_length=240)
    asset_sha256: Digest
    style: Literal["base", "modern"] = "base"

    @model_validator(mode="after")
    def relative_asset(self) -> "TemplateBinding":
        from pathlib import PurePosixPath

        parts = PurePosixPath(self.asset_path).parts
        if (
            self.asset_path.startswith("/")
            or "\\" in self.asset_path
            or any(part in {".", ".."} for part in self.asset_path.split("/"))
            or not parts
            or PurePosixPath(self.asset_path).as_posix() != self.asset_path
            or ":" in self.asset_path
        ):
            raise ValueError("Vorlagenpfad muss relativ und eindeutig sein")
        return self


class ArtifactSpec(StrictPlan):
    version: Literal[1] = 1
    label: Literal["LOCAL_ONLY"] = "LOCAL_ONLY"
    sources: list[SourceBinding] = Field(default_factory=list, max_length=20)
    plan: Plan
    template: TemplateBinding | None = None

    @model_validator(mode="after")
    def source_indices(self) -> "ArtifactSpec":
        if self.template and not isinstance(self.plan, (DocumentPlan, PresentationPlan)):
            raise ValueError("Vorlage nur für Word oder PowerPoint unterstützt")
        if (
            self.template
            and self.template.style == "modern"
            and not isinstance(self.plan, PresentationPlan)
        ):
            raise ValueError("Moderner Präsentationsstil nur für PowerPoint")
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
