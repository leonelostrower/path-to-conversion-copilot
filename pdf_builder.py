"""
Renders a ReportSpec to .pdf, keeping the .monks deliverable styling from
docx_builder.py: Helvetica Neue type scale, green-header tables, captioned
figures and a cover page.

The document structure comes from the spec so the narrative agent's rewrites
flow through without touching this file.
"""

from __future__ import annotations

import os
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table as RLTable, TableStyle,
)

from report_core import LOGO_PATH
from report_spec import Bullets, Figure, Prose, ReportSpec, Table, parse_inline_bold

CONTENT_WIDTH = 6.0 * inch
PAGE_WIDTH, PAGE_HEIGHT = letter
LEFT_MARGIN = RIGHT_MARGIN = 1.25 * inch
TOP_MARGIN = BOTTOM_MARGIN = 1.0 * inch

INK = HexColor('#212121')
CAPTION_GRAY = HexColor('#666666')
TABLE_HEADER_FILL = HexColor('#356854')
TABLE_HEADER_EDGE = HexColor('#284e3f')
TABLE_GRID = HexColor('#cccccc')

_FONT_REGULAR = 'Helvetica'
_FONT_BOLD = 'Helvetica-Bold'
_FONT_LIGHT = 'Helvetica'
_FONTS_READY = False

_HELVETICA_NEUE_CANDIDATES = (
    '/System/Library/Fonts/HelveticaNeue.ttc',
    '/System/Library/Fonts/Supplemental/HelveticaNeue.ttc',
    '/Library/Fonts/HelveticaNeue.ttf',
    '/Library/Fonts/Helvetica Neue.ttf',
)


def _try_register(name: str, path: str, subfont_index: int | None = None) -> bool:
    try:
        kwargs = {} if subfont_index is None else {'subfontIndex': subfont_index}
        pdfmetrics.registerFont(TTFont(name, path, **kwargs))
        return True
    except Exception:
        return False


def _ensure_fonts() -> None:
    global _FONT_REGULAR, _FONT_BOLD, _FONT_LIGHT, _FONTS_READY
    if _FONTS_READY:
        return
    _FONTS_READY = True

    ttc = next((p for p in _HELVETICA_NEUE_CANDIDATES if os.path.exists(p)), None)
    if not ttc:
        return

    if ttc.endswith('.ttc'):
        if _try_register('HelveticaNeue', ttc, 0):
            _FONT_REGULAR = 'HelveticaNeue'
            _FONT_LIGHT = 'HelveticaNeue'
            if _try_register('HelveticaNeue-Bold', ttc, 1):
                _FONT_BOLD = 'HelveticaNeue-Bold'
            if _try_register('HelveticaNeue-Light', ttc, 2):
                _FONT_LIGHT = 'HelveticaNeue-Light'
    else:
        if _try_register('HelveticaNeue', ttc):
            _FONT_REGULAR = 'HelveticaNeue'
            _FONT_BOLD = 'HelveticaNeue'
            _FONT_LIGHT = 'HelveticaNeue'


def _styles() -> dict[str, ParagraphStyle]:
    _ensure_fonts()
    return {
        'cover_title': ParagraphStyle(
            'CoverTitle', fontName=_FONT_BOLD, fontSize=31, leading=36,
            textColor=INK, spaceAfter=0, alignment=TA_LEFT,
        ),
        'cover_sub': ParagraphStyle(
            'CoverSub', fontName=_FONT_REGULAR, fontSize=24, leading=28,
            textColor=INK, spaceAfter=24, alignment=TA_LEFT,
        ),
        'meta': ParagraphStyle(
            'CoverMeta', fontName=_FONT_LIGHT, fontSize=11, leading=14,
            textColor=black, spaceAfter=2, alignment=TA_LEFT,
        ),
        'heading': ParagraphStyle(
            'SectionHeading', fontName=_FONT_REGULAR, fontSize=19, leading=23,
            textColor=black, spaceBefore=18, spaceAfter=6, alignment=TA_LEFT,
        ),
        'body': ParagraphStyle(
            'Body', fontName=_FONT_REGULAR, fontSize=10, leading=11.5,
            textColor=INK, spaceAfter=10, alignment=TA_JUSTIFY,
        ),
        'bullet': ParagraphStyle(
            'Bullet', fontName=_FONT_REGULAR, fontSize=10, leading=11.5,
            textColor=INK, spaceAfter=8, leftIndent=0.25 * inch,
            bulletIndent=0.08 * inch, alignment=TA_JUSTIFY,
        ),
        'caption': ParagraphStyle(
            'Caption', fontName=_FONT_REGULAR, fontSize=8, leading=10,
            textColor=CAPTION_GRAY, spaceAfter=14, alignment=TA_CENTER,
        ),
        'cell': ParagraphStyle(
            'TableCell', fontName=_FONT_REGULAR, fontSize=9, leading=11,
            textColor=INK, alignment=TA_LEFT,
        ),
        'cell_header': ParagraphStyle(
            'TableHeader', fontName=_FONT_BOLD, fontSize=9, leading=11,
            textColor=white, alignment=TA_LEFT,
        ),
    }


def _rich(text: str, bold: bool | None = None) -> str:
    """markdown-lite (**bold**) to ReportLab mini-HTML."""
    if bold is True:
        return f'<b>{xml_escape(text)}</b>'
    if bold is False:
        return xml_escape(text)
    parts = []
    for chunk, is_bold in parse_inline_bold(text):
        esc = xml_escape(chunk).replace('\n', '<br/>')
        parts.append(f'<b>{esc}</b>' if is_bold else esc)
    return ''.join(parts)


def _add_cover(story: list, spec: ReportSpec, styles: dict, logo_path: str | None) -> None:
    logo_path = LOGO_PATH if logo_path is None else logo_path
    if logo_path and os.path.exists(logo_path):
        ir = ImageReader(logo_path)
        iw, ih = ir.getSize()
        width = 2.2 * inch
        height = width * ih / iw if iw else width
        img = Image(logo_path, width=width, height=height)
        img.hAlign = 'LEFT'
        story.append(img)
        story.append(Spacer(1, 36))

    head, _, tail = spec.title.partition(':')
    story.append(Paragraph(_rich(f'{head}:' if tail else head, True), styles['cover_title']))
    if tail:
        story.append(Paragraph(_rich(tail.strip(), True), styles['cover_title']))
    story.append(Paragraph(xml_escape(spec.subtitle), styles['cover_sub']))
    for line in spec.cover_lines:
        story.append(Paragraph(xml_escape(line), styles['meta']))

    story.append(Paragraph('Index', styles['heading']))
    story.append(Spacer(1, 0))
    story.append(PageBreak())


def _add_table(story: list, block: Table, styles: dict) -> None:
    n = len(block.headers)
    if n == 0 or not block.rows:
        return
    widths = block.widths or [CONTENT_WIDTH / n / inch] * n
    col_widths = [w * inch for w in widths]

    header = [Paragraph(xml_escape(str(h)), styles['cell_header']) for h in block.headers]
    data = [header]
    for row in block.rows:
        data.append([Paragraph(xml_escape(str(val)), styles['cell']) for val in row])

    table = RLTable(data, colWidths=col_widths, repeatRows=1)
    table.hAlign = 'LEFT'
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_FILL),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 1), (-1, -1), INK),
        ('BACKGROUND', (0, 1), (-1, -1), white),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('BOX', (0, 0), (-1, 0), 0.5, TABLE_HEADER_EDGE),
        ('INNERGRID', (0, 0), (-1, 0), 0.5, TABLE_HEADER_EDGE),
        ('BOX', (0, 1), (-1, -1), 0.5, TABLE_GRID),
        ('INNERGRID', (0, 1), (-1, -1), 0.5, TABLE_GRID),
    ]))
    story.append(table)
    story.append(Spacer(1, 4))


def _add_figure(story: list, path: str | None, caption: str, styles: dict) -> None:
    if not path or not os.path.exists(path):
        return
    ir = ImageReader(path)
    iw, ih = ir.getSize()
    width = CONTENT_WIDTH
    height = width * ih / iw if iw else width
    img = Image(path, width=width, height=height)
    img.hAlign = 'CENTER'
    story.append(KeepTogether([
        img,
        Paragraph(xml_escape(caption), styles['caption']),
    ]))


def build_pdf(spec: ReportSpec, out_path: str, logo_path: str | None = None) -> str:
    """Render the spec to a PDF, honouring each section's block order."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    _ensure_fonts()
    styles = _styles()

    doc = SimpleDocTemplate(
        out_path,
        pagesize=letter,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=spec.title,
        author=spec.client_name,
    )

    story: list = []
    _add_cover(story, spec, styles, logo_path)

    for section in spec.sections:
        story.append(Paragraph(xml_escape(section.heading), styles['heading']))
        for block in section.blocks:
            if isinstance(block, Prose):
                if block.text.strip():
                    story.append(Paragraph(_rich(block.text), styles['body']))
            elif isinstance(block, Bullets):
                for item in block.items:
                    if item.strip():
                        story.append(Paragraph(_rich(item), styles['bullet'],
                                              bulletText='•'))
            elif isinstance(block, Table):
                _add_table(story, block, styles)
            elif isinstance(block, Figure):
                _add_figure(story, block.path, block.caption, styles)
        if section.page_break_after:
            story.append(PageBreak())

    doc.build(story)
    return out_path
