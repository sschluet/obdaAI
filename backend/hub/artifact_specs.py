"""Bounded data plans for offline artifacts; never executable model output."""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictFloat,
    StrictInt,
    StringConstraints,
    ValidationInfo,
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
        for key in (
            "images",
            "pdf_export",
            "caption",
            "split_after",
            "template",
            "letter",
            "number_formats",
            "charts",
            "no_stripes",
            "totals",
            "highlight_cells",
            "column_groups",
        ):
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


class VisualItem(StrictPlan):
    label: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    text: str = Field(default="", max_length=220)
    value: str = Field(default="", max_length=24)
    lane: str = Field(default="", max_length=60)
    start: float | None = Field(default=None, ge=0, le=12, allow_inf_nan=False)
    end: float | None = Field(default=None, ge=0, le=12, allow_inf_nan=False)
    period: int | None = Field(default=None, ge=0, le=11)
    from_period: str | None = Field(default=None, min_length=1, max_length=50)
    to_period: str | None = Field(default=None, min_length=1, max_length=50)

    @model_serializer(mode="wrap")
    def compatible_periods(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for key in ("from_period", "to_period"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class VisualSeries(StrictPlan):
    name: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    values: list[Annotated[float, Field(allow_inf_nan=False, ge=-1e12, le=1e12)]] = Field(
        min_length=1, max_length=12
    )


class SlideVisual(StrictPlan):
    kind: Literal[
        "process",
        "swimlane",
        "cycle",
        "timeline",
        "matrix",
        "kpi",
        "layers",
        "comparison",
        "dot_matrix",
        "status_bars",
        "chart",
        "messages",
    ]
    items: list[VisualItem] = Field(default_factory=list, max_length=24)
    columns: list[Annotated[str, StringConstraints(min_length=1, max_length=50)]] = Field(
        default_factory=list, max_length=12
    )
    series: list[VisualSeries] = Field(default_factory=list, max_length=4)
    chart_type: Literal["column", "bar", "line", "area", "pie", "doughnut"] = "column"
    center_label: str = Field(default="", max_length=60)
    center_value: str = Field(default="", max_length=24)
    annotation: str = Field(default="", max_length=450)

    @model_validator(mode="after")
    def valid_geometry(self) -> "SlideVisual":
        if self.kind != "timeline" and any(
            i.from_period is not None or i.to_period is not None for i in self.items
        ):
            raise ValueError("Benannte Zeiträume sind nur für Zeitstrahlen vorgesehen")
        if self.kind in {"chart", "status_bars"}:
            if not self.columns or not self.series:
                raise ValueError("Diagramm benötigt Kategorien und Datenreihen")
            if any(len(row.values) != len(self.columns) for row in self.series):
                raise ValueError("Diagramm benötigt gleich viele Werte je Kategorie")
            if self.kind == "status_bars" and any(v < 0 for r in self.series for v in r.values):
                raise ValueError("Statusbalken benötigen nichtnegative Werte")
            if self.chart_type in {"pie", "doughnut"} and (
                len(self.series) != 1
                or any(v < 0 for v in self.series[0].values)
                or sum(self.series[0].values) <= 0
            ):
                raise ValueError("Anteilsdiagramme benötigen eine positive Datenreihe")
        elif not self.items:
            raise ValueError("Schaubild benötigt Inhalt")
        limits = {
            "process": 6,
            "cycle": 6,
            "kpi": 4,
            "layers": 6,
            "comparison": 12,
            "messages": 6,
            "dot_matrix": 4,
        }
        if self.kind in limits and len(self.items) > limits[self.kind]:
            raise ValueError("Zu viele Elemente für diesen Schaubildtyp")
        if self.kind == "cycle" and len(self.items) < 4:
            raise ValueError("Kreislauf benötigt vier bis sechs Schritte")
        if self.kind == "swimlane" and (
            any(not i.lane for i in self.items)
            or len({i.lane for i in self.items}) > 4
            or any(sum(j.lane == i.lane for j in self.items) > 6 for i in self.items)
        ):
            raise ValueError("Swimlane benötigt maximal vier Bahnen mit je sechs Schritten")
        if self.kind == "comparison" and len({i.lane for i in self.items}) != 2:
            raise ValueError("Vergleich benötigt genau zwei benannte Seiten")
        if self.kind in {"timeline", "matrix"}:
            if not self.columns or len({i.lane for i in self.items}) > 6:
                raise ValueError("Zeitdarstellung benötigt Zeiträume und maximal sechs Bahnen")
            if any(not i.lane for i in self.items):
                raise ValueError("Zeitdarstellung benötigt benannte Bahnen")
            if len(set(self.columns)) != len(self.columns):
                raise ValueError("Zeiträume müssen eindeutig benannt sein")
            if self.kind == "timeline":
                for item in self.items:
                    semantic = item.from_period is not None or item.to_period is not None
                    if semantic:
                        if (
                            item.from_period not in self.columns
                            or item.to_period not in self.columns
                            or item.start is not None
                            or item.end is not None
                            or self.columns.index(item.from_period)
                            > self.columns.index(item.to_period)
                        ):
                            raise ValueError("Zeitraum benötigt eindeutige vorhandene Spaltennamen")
                    elif (
                        item.start is None
                        or item.end is None
                        or not item.start < item.end <= len(self.columns)
                    ):
                        raise ValueError("Zeitraum muss innerhalb der Zeitachse liegen")
            if self.kind == "matrix" and any(
                i.period is None or i.period >= len(self.columns) for i in self.items
            ):
                raise ValueError("Matrix benötigt gültige Zeitraum-Indizes")
        if self.kind == "dot_matrix":
            try:
                counts = [int(i.value) for i in self.items]
            except ValueError as exc:
                raise ValueError("Punktmatrix benötigt ganzzahlige Mengen") from exc
            if any(n < 0 for n in counts) or not 1 <= sum(counts) <= 150:
                raise ValueError("Punktmatrix benötigt insgesamt 1 bis 150 Punkte")
        return self


class Slide(StrictPlan):
    title: Short
    bullets: list[Annotated[str, StringConstraints(min_length=1, max_length=140)]] = Field(
        min_length=1, max_length=5
    )
    notes: str = Field(default="", max_length=4000)
    layout: Literal["content", "cover", "end"] = "content"
    kicker: str = Field(default="", max_length=80)
    subtitle: str = Field(default="", max_length=180)
    footer: str = Field(default="", max_length=140)
    visual: SlideVisual | None = None

    @model_serializer(mode="wrap")
    def compatible_slide(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for key in ("visual", "kicker", "subtitle", "footer"):
            if not data.get(key):
                data.pop(key, None)
        if data.get("layout") == "content":
            data.pop("layout", None)
        return data


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


class FormulaCell(StrictPlan):
    formula: Annotated[str, StringConstraints(min_length=2, max_length=2000)]


class SpreadsheetChart(StrictPlan):
    type: Literal["bar", "line", "pie", "area", "scatter"]
    title: Short
    categories: Annotated[
        str, StringConstraints(pattern=r"^[A-T][1-9][0-9]{0,2}:[A-T][1-9][0-9]{0,2}$")
    ]
    series: list[
        Annotated[str, StringConstraints(pattern=r"^[A-T][1-9][0-9]{0,2}:[A-T][1-9][0-9]{0,2}$")]
    ] = Field(min_length=1, max_length=8)
    anchor: Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,2}[1-9][0-9]{0,2}$")] = "G2"


Cell = (
    Annotated[str, StringConstraints(max_length=2000)]
    | StrictBool
    | StrictInt
    | StrictFloat
    | FormulaCell
    | None
)


class ColumnGroup(StrictPlan):
    start: Annotated[str, StringConstraints(pattern=r"^[A-T]$")]
    end: Annotated[str, StringConstraints(pattern=r"^[A-T]$")]


class SpreadsheetSheet(StrictPlan):
    name: Annotated[str, StringConstraints(min_length=1, max_length=31)]
    columns: list[Short] = Field(min_length=1, max_length=20)
    rows: list[list[Cell]] = Field(default_factory=list, max_length=500)
    number_formats: dict[
        Annotated[str, StringConstraints(pattern=r"^[A-T]$")],
        Literal["currency", "percent", "integer", "decimal", "date"],
    ] = Field(default_factory=dict, max_length=20)
    charts: list[SpreadsheetChart] = Field(default_factory=list, max_length=6)
    no_stripes: bool = False
    totals: dict[
        Annotated[str, StringConstraints(pattern=r"^[A-T]$")],
        Literal["sum", "average", "count", "min", "max"],
    ] = Field(default_factory=dict, max_length=20)
    highlight_cells: list[Annotated[str, StringConstraints(pattern=r"^[A-T][1-9][0-9]{0,2}$")]] = (
        Field(default_factory=list, max_length=100)
    )
    column_groups: list[ColumnGroup] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def sheet_shape(self) -> "SpreadsheetSheet":
        import math

        if any(char in self.name for char in "[]:*?/\\"):
            raise ValueError("Ungültiger Tabellenblattname")
        native_features = (
            self.charts
            or self.totals
            or self.highlight_cells
            or self.column_groups
            or any(isinstance(cell, FormulaCell) for row in self.rows for cell in row)
        )
        if native_features and len({column.casefold() for column in self.columns}) != len(
            self.columns
        ):
            raise ValueError("Tabellenköpfe müssen eindeutig sein")
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
    def workbook_shape(self, info: ValidationInfo) -> "SpreadsheetPlan":
        if len({sheet.name.casefold() for sheet in self.sheets}) != len(self.sheets):
            raise ValueError("Tabellenblattnamen müssen eindeutig sein")
        if sum((len(sheet.rows) + 1) * len(sheet.columns) for sheet in self.sheets) > 10000:
            raise ValueError("Tabelle überschreitet das Zellenlimit")
        from .spreadsheet_features import validate_workbook

        validate_workbook(self, strict=not bool((info.context or {}).get("legacy_formula_read")))
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
    _legacy_formula_warning: bool = PrivateAttr(default=False)
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
