"""Fixed, offline Office adapters. Imported skill scripts are never executed.

Office masters, styles, artwork and section geometry come from the verified
private template. The model supplies only the existing bounded data plan.
"""

import io
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree  # type: ignore[import-untyped]

from hub.artifact_specs import DocumentPlan, PresentationPlan

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
R = "http://schemas.openxmlformats.org/package/2006/relationships"


def _q(name: str) -> str:
    return "{" + W + "}" + name


def _xml(data: bytes) -> Any:
    return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))


def office_stream(path: Path, kind: str) -> io.BytesIO:
    """Convert template content types, retaining masters and verified static assets."""
    target = io.BytesIO()
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(target, "w") as output:
        fonts: dict[str, str] = {}
        if kind == "docx" and "word/theme/theme1.xml" in source.namelist():
            theme = _xml(source.read("word/theme/theme1.xml"))
            for category in ("major", "minor"):
                matches = theme.xpath(
                    "//*[local-name()='" + category + "Font']/*[local-name()='latin']/@typeface"
                )
                if matches:
                    fonts[category] = str(matches[0])
        infos = source.infolist()
        if len(infos) > 3000 or sum(i.file_size for i in infos) > 120 * 1024 * 1024:
            raise ValueError("Office-Vorlage überschreitet das Paketlimit")
        if len({i.filename for i in infos}) != len(infos):
            raise ValueError("Office-Vorlage enthält doppelte Teile")
        for info in infos:
            name = info.filename
            if name.startswith("/") or ".." in name.split("/") or "\\" in name:
                raise ValueError("Ungültiger Office-Vorlagenteil")
            if any(part in name.lower() for part in ("vbaproject", "/embeddings/", "activex")):
                raise ValueError("Aktiver Office-Inhalt ist nicht freigegeben")
            data = source.read(name)
            if name.endswith(".rels"):
                root = _xml(data)
                for relation in list(root):
                    if relation.get("TargetMode") == "External":
                        if not relation.get("Type", "").endswith("/hyperlink"):
                            raise ValueError("Externe Office-Inhalte sind nicht freigegeben")
                        root.remove(relation)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
            elif name == "[Content_Types].xml":
                root = _xml(data)
                for part in root:
                    if part.get("PartName") == "/word/document.xml" and kind == "docx":
                        part.set(
                            "ContentType",
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document.main+xml",
                        )
                    if part.get("PartName") == "/ppt/presentation.xml" and kind == "pptx":
                        part.set(
                            "ContentType",
                            "application/vnd.openxmlformats-officedocument."
                            "presentationml.presentation.main+xml",
                        )
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
            elif name.endswith(".xml"):
                # Strip template data bindings/fields and external-link references;
                # retained static artwork and section properties stay untouched.
                root = _xml(data)
                for font in root.iter(_q("rFonts")):
                    for slot in ("ascii", "hAnsi"):
                        reference = font.get(_q(slot + "Theme"), "")
                        family = fonts.get(reference[:5])
                        if family and not font.get(_q(slot)):
                            font.set(_q(slot), family.removesuffix(" Bold"))
                            font.attrib.pop(_q(slot + "Theme"), None)
                            if family.endswith(" Bold"):
                                parent = font.getparent()
                                if parent.find(_q("b")) is None:
                                    etree.SubElement(parent, _q("b"))
                for item in root.xpath("//*[local-name()='dataBinding']"):
                    item.getparent().remove(item)
                for link in root.xpath(
                    "//*[local-name()='hyperlink' or local-name()='hlinkClick']"
                ):
                    parent = link.getparent()
                    if link.tag == _q("hyperlink"):
                        index = parent.index(link)
                        for child in list(link):
                            parent.insert(index, child)
                            index += 1
                    parent.remove(link)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
            output.writestr(name, data)
    target.seek(0)
    return target


def _text(element: Any) -> str:
    return "".join(node.text or "" for node in element.iter(_q("t")))


def _replace(element: Any, text: str) -> None:
    """Retain first run styling; replace content, not drawing/paragraph geometry."""
    texts = list(element.iter(_q("t")))
    if texts:
        texts[0].text = text
        texts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        for node in texts[1:]:
            node.text = ""
    else:
        run = etree.SubElement(element, _q("r"))
        etree.SubElement(run, _q("t")).text = text
    for node in list(element.iter(_q("instrText"))) + list(element.iter(_q("fldChar"))):
        node.getparent().remove(node)


def _style(document: Any, *names: str) -> Any:
    for name in names:
        for style in document.styles:
            if style.style_id == name or style.name == name:
                return style
    return document.styles["Normal"]


def _letter(document: Any, plan: DocumentPlan) -> Any:
    if not plan.letter:
        raise ValueError("Briefvorlage benötigt Empfänger, Betreff, Datum, Anrede und Unterschrift")
    fields = plan.letter
    body = document.element.body
    # Content controls may wrap the subject. Unwrap after detaching data bindings.
    for control in list(body.iter(_q("sdt")))[::-1]:
        content = control.find(_q("sdtContent"))
        if content is not None:
            parent = control.getparent()
            index = parent.index(control)
            for child in list(content):
                parent.insert(index, child)
                index += 1
            parent.remove(control)
    tables = document.tables
    if len(tables) < 2:
        raise ValueError("Briefvorlage benötigt Anschrift- und Betrefftabelle")
    address, subject = tables[:2]
    if len(address.columns) < 2 or len(subject.rows) < 2 or len(subject.columns) < 3:
        raise ValueError("Briefvorlage hat keine unterstützten Anschriftfelder")
    for column, lines in ((0, fields.recipient), (1, fields.sender)):
        for index, row in enumerate(address.rows):
            cell = row.cells[column]
            first = cell.paragraphs[0]
            _replace(first._p, lines[index] if index < len(lines) else "")
            for paragraph in cell.paragraphs[1:]:
                _replace(paragraph._p, "")
    _replace(subject.rows[0].cells[0].paragraphs[0]._p, fields.subject)
    _replace(subject.rows[1].cells[2].paragraphs[0]._p, fields.date)
    for cell in subject.rows[1].cells[:2]:
        for paragraph in cell.paragraphs:
            _replace(paragraph._p, "")
    for paragraph in document.paragraphs:
        if paragraph.style.style_id == "FirstPage-details":
            _replace(paragraph._p, " · ".join(fields.sender))
    anchor = body.find(_q("sectPr"))
    children = list(body)
    for child in children[children.index(subject._tbl) + 1 : children.index(anchor)]:
        body.remove(child)
    return anchor


def _document_anchor(document: Any, plan: DocumentPlan) -> tuple[Any, bool]:
    body = document.element.body
    children = list(body)
    cover = children[0] if children and children[0].tag == _q("sdt") else None
    breaks = [child for child in children if child.find(_q("pPr") + "/" + _q("sectPr")) is not None]
    if cover is not None and breaks:
        anchor = breaks[-1]
        for child in children[1 : children.index(anchor)]:
            body.remove(child)
        for run in list(anchor.findall(_q("r"))):
            anchor.remove(run)
        title_found = False
        for control in cover.iter(_q("sdt")):
            alias = control.find(_q("sdtPr") + "/" + _q("alias"))
            if alias is not None and alias.get(_q("val")) == "Title":
                paragraph = control.find(".//" + _q("p"))
                if paragraph is not None:
                    _replace(paragraph, plan.title)
                    title_found = True
                else:
                    _replace(control.find(_q("sdtContent")), plan.title)
                    title_found = True
        for paragraph in cover.iter(_q("p")):
            text = _text(paragraph)
            if text == "[Document Template]":
                _replace(paragraph, plan.title)
                title_found = True
            elif text in {"For External Documents", "[First name Last name]", "[Email Address]"}:
                _replace(paragraph, "")
        if not title_found:
            raise ValueError("Dokumentvorlage hat kein unterstütztes Titelfeld")
        return anchor, True
    if plan.letter:
        return _letter(document, plan), False
    # Generic .dotx: preserve section properties, headers, footers and styles;
    # sample body is replaced. Explicit cover layouts use the branch above.
    anchor = body.find(_q("sectPr"))
    for child in list(body):
        if child is not anchor:
            body.remove(child)
    return anchor, False


def _letter_parts(plan: DocumentPlan) -> tuple[list[tuple[str | None, list[str]]], list[str]]:
    """Render structured letter boundaries once; do not rewrite substantive body text."""
    fields = plan.letter
    assert fields is not None

    def key(text: str) -> str:
        return " ".join(text.split()).casefold().rstrip(",.")

    closings = {
        "mit freundlichen grüßen",
        "freundliche grüße",
        "beste grüße",
        "kind regards",
        "best regards",
        "sincerely",
    }
    signer_placeholder = "unterzeichner ergänzen"
    missing_role = {"funktion ergänzen", "position ergänzen", "titel ergänzen", "[funktion]"}
    actual_signer = any(
        key(line) not in closings | missing_role | {signer_placeholder} for line in fields.signature
    )
    signature = [
        line for line in fields.signature if not (actual_signer and key(line) == signer_placeholder)
    ]
    removable = {key(line) for line in signature} | closings
    if actual_signer:
        removable.add(signer_placeholder)
    parts: list[tuple[str | None, list[str]]] = []
    for index, section in enumerate(plan.sections):
        heading: str | None = section.heading
        if index == 0 and key(section.heading) in {
            "brieftext",
            "brief",
            "anschreiben",
            "betreff",
            key(fields.subject),
            key(plan.title),
        }:
            heading = None
        parts.append((heading, list(section.paragraphs)))
    first = next((paragraphs for _, paragraphs in parts if paragraphs), None)
    if first:
        lines = first[0].splitlines()
        if lines and key(lines[0]) == key(fields.salutation):
            first[0] = "\n".join(lines[1:]).strip()
            if not first[0]:
                first.pop(0)
    body_closing = ""
    for _, paragraphs in reversed(parts):
        while paragraphs:
            lines = paragraphs[-1].splitlines()
            changed = False
            while lines and key(lines[-1]) in removable:
                line = lines.pop()
                if key(line) in closings:
                    body_closing = line
                changed = True
            if not changed:
                break
            if lines:
                paragraphs[-1] = "\n".join(lines)
                break
            paragraphs.pop()
        if paragraphs:
            break
    if body_closing and not any(key(line) in closings for line in signature):
        signature.insert(0, body_closing)
    # Exact duplicate signature lines are artifacts, never a request for a second signer.
    unique_signature = []
    seen: set[str] = set()
    for line in signature:
        if key(line) not in seen:
            unique_signature.append(line)
            seen.add(key(line))
    return parts, unique_signature


def document(plan: DocumentPlan, path: Path, template: Path, inputs: list[Path]) -> None:
    from docx import Document
    from docx.shared import Inches

    from hub.artifact_render import _read_image

    doc = Document(office_stream(template, "docx"))
    table_style = doc.tables[0].style if doc.tables else None
    # A recognizable letter template must not leak its example addresses.
    if (
        any(p.style is not None and p.style.style_id == "FirstPage-details" for p in doc.paragraphs)
        and not plan.letter
    ):
        raise ValueError("Briefvorlage benötigt die strukturierten Briefangaben")
    for section in doc.sections:
        for part in (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
            section.even_page_header,
            section.even_page_footer,
        ):
            for control in part._element.iter(_q("sdt")):
                alias = control.find(_q("sdtPr") + "/" + _q("alias"))
                content = control.find(_q("sdtContent"))
                if alias is not None and alias.get(_q("val")) == "Title" and content is not None:
                    _replace(content, plan.title)
                    placeholder = control.find(_q("sdtPr") + "/" + _q("showingPlcHdr"))
                    if placeholder is not None:
                        placeholder.getparent().remove(placeholder)
            for paragraph in part._element.iter(_q("p")):
                if _text(paragraph) == "[Document Template]":
                    _replace(paragraph, plan.title)
    anchor, covered = _document_anchor(doc, plan)
    body = doc.element.body

    def move(element: Any) -> None:
        body.remove(element)
        anchor.addprevious(element)

    if plan.letter:
        move(doc.add_paragraph(plan.letter.salutation)._p)
    elif not covered:
        move(doc.add_paragraph(plan.title, style=_style(doc, "Titel", "Title"))._p)
    parts, signature = (
        _letter_parts(plan)
        if plan.letter
        else ([(item.heading, list(item.paragraphs)) for item in plan.sections], [])
    )
    for item, (heading, paragraphs) in zip(plan.sections, parts, strict=True):
        if heading:
            move(
                doc.add_paragraph(
                    heading,
                    style=_style(doc, "Highlights" if plan.letter else "berschrift1", "Heading 1"),
                )._p
            )
        for text in paragraphs:
            move(doc.add_paragraph(text, style=_style(doc, "Standard", "Normal"))._p)
        if item.table:
            table = doc.add_table(rows=0, cols=len(item.table[0]))
            table.style = table_style or next(
                (s for s in doc.styles if s.type == 3), doc.styles["Normal Table"]
            )
            for row in item.table:
                for cell, text in zip(table.add_row().cells, row, strict=True):
                    cell.text = text
            move(table._tbl)
        for image in item.images:
            pixels = io.BytesIO()
            _read_image(inputs[image.source]).save(pixels, format="PNG")
            pixels.seek(0)
            paragraph = doc.add_paragraph()
            paragraph.add_run().add_picture(pixels, width=Inches(image.width_inches))
            move(paragraph._p)
            if image.caption:
                move(
                    doc.add_paragraph(
                        image.caption, style=_style(doc, "Beschriftung", "Caption")
                    )._p
                )
    if plan.letter:
        for line in signature:
            move(doc.add_paragraph(line)._p)
    doc.core_properties.title = plan.title
    doc.core_properties.author = "obdaAI"
    doc.save(str(path))
    check = Document(str(path))
    if not all(
        heading in "\n".join(p.text for p in check.paragraphs) for heading, _ in parts if heading
    ):
        raise ValueError("Word-Vorlagenprüfung fehlgeschlagen")


def presentation(plan: PresentationPlan, path: Path, template: Path, modern: bool) -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE, PP_PLACEHOLDER
    from pptx.util import Inches, Pt

    from hub.artifact_render import _fit_slide_text

    deck = Presentation(office_stream(template, "pptx"))
    for slide_id in list(deck.slides._sldIdLst):
        deck.part.drop_rel(slide_id.rId)
        deck.slides._sldIdLst.remove(slide_id)
    layouts = list(deck.slide_layouts)
    layout = next((x for x in layouts if x.name == "Text 2"), None)
    if layout is None:
        layout = next(
            (
                x
                for x in layouts
                if any(
                    p.placeholder_format.type in {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT}
                    for p in list(x.placeholders)
                )
            ),
            None,
        )
    if layout is None:
        raise ValueError("PowerPoint-Vorlage benötigt ein Titel-/Inhaltslayout")
    for item in plan.slides:
        slide = deck.slides.add_slide(layout)
        title = slide.shapes.title
        if title is None:
            raise ValueError("PowerPoint-Vorlage benötigt einen Titelplatzhalter")
        title.text = item.title
        _fit_slide_text(title.text_frame, maximum=28, minimum=16, bold=True)
        candidates = [
            p
            for p in slide.placeholders
            if p != title
            and p.placeholder_format.type in {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT}
        ]
        if not candidates:
            raise ValueError("PowerPoint-Vorlage benötigt einen Inhaltsplatzhalter")
        box = max(candidates, key=lambda p: p.width * p.height)
        if modern:
            box.text = ""
            count = len(item.bullets)
            height = box.height // count
            for index, text in enumerate(item.bullets):
                card = slide.shapes.add_shape(
                    MSO_SHAPE.ROUNDED_RECTANGLE,
                    box.left,
                    box.top + height * index,
                    box.width,
                    height - Inches(0.09),
                )
                card.fill.solid()
                card.fill.fore_color.rgb = RGBColor(0xF0, 0xF4, 0xFC)  # type: ignore[no-untyped-call]
                card.line.fill.background()
                card.text_frame.margin_left = Inches(0.2)
                card.text_frame.margin_right = Inches(0.2)
                card.text_frame.text = text
                _fit_slide_text(card.text_frame, maximum=20, minimum=14)
                for paragraph in card.text_frame.paragraphs:
                    paragraph.font.color.rgb = RGBColor(0x02, 0x06, 0x23)  # type: ignore[no-untyped-call]
        else:
            frame = box.text_frame
            frame.clear()
            for index, text in enumerate(item.bullets):
                paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
                paragraph.text = text
                paragraph.level = 0
                paragraph.space_after = Pt(12)
            _fit_slide_text(frame, maximum=22, minimum=14, spacing=12)
        slide.notes_slide.notes_text_frame.text = item.notes
    deck.core_properties.title = plan.title
    deck.core_properties.author = "obdaAI"
    deck.save(str(path))
    if len(Presentation(str(path)).slides) != len(plan.slides):
        raise ValueError("PowerPoint-Vorlagenprüfung fehlgeschlagen")
