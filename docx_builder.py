"""
Renders a ReportSpec to .docx, keeping the .monks deliverable styling from
generate_report.py: Helvetica Neue type scale, green-header tables, captioned
figures and a cover page.

The styling helpers are unchanged in behaviour; what changed is that the document
structure now comes from the spec rather than being hardcoded inline, so the
narrative agent's rewrites flow through without touching this file.
"""

from __future__ import annotations

import os

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from report_core import LOGO_PATH
from report_spec import Bullets, Figure, Prose, ReportSpec, Table, parse_inline_bold

BODY_FONT = 'Helvetica Neue'
LIGHT_FONT = 'Helvetica Neue Light'
BODY_SIZE = Pt(10)
HEADING_SIZE = Pt(19)
COVER_TITLE_SIZE = Pt(31)
COVER_SUB_SIZE = Pt(24)
META_SIZE = Pt(11)
CAPTION_SIZE = Pt(8)
TABLE_SIZE = Pt(9)

INK = RGBColor(0x21, 0x21, 0x21)
BLACK = RGBColor(0x00, 0x00, 0x00)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CAPTION_GRAY = RGBColor(0x66, 0x66, 0x66)

TABLE_HEADER_FILL = '356854'
TABLE_HEADER_EDGE = '284e3f'
TABLE_GRID = 'cccccc'

CONTENT_WIDTH_IN = 6.0


def _apply_font(el, font):
    """Set ascii/hAnsi/cs/eastAsia together so Word does not substitute the face."""
    rPr = el.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    for attr in ('w:ascii', 'w:hAnsi', 'w:cs', 'w:eastAsia'):
        rFonts.set(qn(attr), font)


def style_run(run, size=BODY_SIZE, bold=False, color=None, font=BODY_FONT):
    run.font.size = size
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    _apply_font(run._element, font)
    return run


def new_document():
    doc = Document()

    normal = doc.styles['Normal']
    normal.font.size = BODY_SIZE
    _apply_font(normal.element, BODY_FONT)
    normal.paragraph_format.space_after = Pt(10)
    normal.paragraph_format.line_spacing = 1.15

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.left_margin = sec.right_margin = Inches(1.25)
    sec.top_margin = sec.bottom_margin = Inches(1)
    return doc


def add_heading(doc, text):
    """Heading 1 so the text still lands in the document outline / Index,
    restyled to the deliverable's type scale."""
    h = doc.add_heading(text, level=1)
    h.paragraph_format.space_before = Pt(18)
    h.paragraph_format.space_after = Pt(6)
    for run in h.runs:
        style_run(run, size=HEADING_SIZE, color=BLACK)
    return h


def add_body(doc, segments, justify=True, size=BODY_SIZE, font=BODY_FONT,
             color=None, space_after=Pt(10)):
    """segments: a string, or a list of strings / (text, bold) pairs."""
    p = doc.add_paragraph()
    if justify:
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = space_after
    for seg in ([segments] if isinstance(segments, str) else segments):
        text, bold = (seg, False) if isinstance(seg, str) else seg
        style_run(p.add_run(text), size=size, bold=bold, color=color, font=font)
    return p


def add_bullets(doc, items):
    """items: markdown-lite strings; **bold** becomes a bold run."""
    for item in items:
        p = doc.add_paragraph(style='List Bullet')
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.left_indent = Inches(0.25)
        p.paragraph_format.space_after = Pt(8)
        for text, bold in parse_inline_bold(item):
            style_run(p.add_run(text), bold=bold)


def _shade_cell(cell, fill):
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:fill'), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _border_cell(cell, color):
    borders = OxmlElement('w:tcBorders')
    for edge in ('top', 'left', 'bottom', 'right'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), '4')
        el.set(qn('w:color'), color)
        borders.append(el)
    cell._tc.get_or_add_tcPr().append(borders)


def _write_cell(cell, text, bold=False, color=None, fill=None, border=TABLE_GRID):
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    style_run(p.add_run(str(text)), size=TABLE_SIZE, bold=bold, color=color)
    if fill:
        _shade_cell(cell, fill)
    _border_cell(cell, border)


def add_table(doc, headers, rows, widths=None):
    """Green-header table matching the deliverable's table treatment."""
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False

    layout = OxmlElement('w:tblLayout')
    layout.set(qn('w:type'), 'fixed')
    table._tbl.tblPr.append(layout)

    if widths is None:
        widths = [CONTENT_WIDTH_IN / len(headers)] * len(headers)

    for cell, head, w in zip(table.rows[0].cells, headers, widths):
        cell.width = Inches(w)
        _write_cell(cell, head, bold=True, color=WHITE,
                    fill=TABLE_HEADER_FILL, border=TABLE_HEADER_EDGE)

    for row in rows:
        cells = table.add_row().cells
        for cell, val, w in zip(cells, row, widths):
            cell.width = Inches(w)
            _write_cell(cell, val)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    return table


def add_figure(doc, path, caption, width_in=CONTENT_WIDTH_IN):
    if not path or not os.path.exists(path):
        return
    doc.add_picture(path, width=Inches(width_in))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_after = Pt(14)
    style_run(cap.add_run(caption), size=CAPTION_SIZE, color=CAPTION_GRAY)


def add_cover(doc, spec: ReportSpec, logo_path: str | None = None):
    logo_path = LOGO_PATH if logo_path is None else logo_path
    # The logo is optional: a missing asset must not break report generation.
    if logo_path and os.path.exists(logo_path):
        doc.add_picture(logo_path, width=Inches(2.2))
        doc.paragraphs[-1].paragraph_format.space_after = Pt(36)

    head, _, tail = spec.title.partition(':')
    add_body(doc, [(f"{head}:" if tail else head, True)], justify=False,
             size=COVER_TITLE_SIZE, color=INK, space_after=Pt(0))
    if tail:
        add_body(doc, [(tail.strip(), True)], justify=False,
                 size=COVER_TITLE_SIZE, color=INK, space_after=Pt(0))
    add_body(doc, spec.subtitle, justify=False, size=COVER_SUB_SIZE,
             color=INK, space_after=Pt(24))

    for line in spec.cover_lines:
        add_body(doc, line, justify=False, size=META_SIZE, font=LIGHT_FONT,
                 color=BLACK, space_after=Pt(2))

    add_heading(doc, 'Index')
    add_body(doc, '', space_after=Pt(0))
    doc.add_page_break()


def build_docx(spec: ReportSpec, out_path: str, logo_path: str | None = None) -> str:
    """Render the spec to a Word file, honouring each section's block order."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    doc = new_document()
    add_cover(doc, spec, logo_path)

    for section in spec.sections:
        add_heading(doc, section.heading)
        for block in section.blocks:
            if isinstance(block, Prose):
                if block.text.strip():
                    add_body(doc, parse_inline_bold(block.text))
            elif isinstance(block, Bullets):
                add_bullets(doc, [i for i in block.items if i.strip()])
            elif isinstance(block, Table):
                if block.rows:
                    add_table(doc, block.headers, block.rows, block.widths)
            elif isinstance(block, Figure):
                add_figure(doc, block.path, block.caption)
        if section.page_break_after:
            doc.add_page_break()

    doc.save(out_path)
    return out_path
