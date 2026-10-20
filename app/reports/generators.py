"""Generación de reportes en PDF y XLSX (RF-15)."""
from __future__ import annotations

from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, Paragraph, Spacer, TableStyle

FORMULA_PREFIXES = ("=", "+", "-", "@")


def _safe(value):
    """Neutraliza inyección de fórmulas de Excel prefijando comilla simple."""
    if value is None:
        return value
    text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return value


def generate_xlsx(title, headers, rows, totals=None):
    """Genera un XLSX con encabezados estilizados, anchos automáticos y totales."""
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    header_fill = PatternFill(start_color="1F2A44", end_color="1F2A44", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
    for row in rows:
        ws.append([_safe(v) for v in row])
    if totals:
        ws.append([])
        ws.append([_safe(v) for v in totals])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for idx, header in enumerate(headers, start=1):
        width = max(len(str(header)) + 2, 10)
        ws.column_dimensions[get_column_letter(idx)].width = width
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def generate_pdf(title, headers, rows, totals=None, user="", date_from=None, date_to=None):
    """Genera un PDF con tabla, encabezado y pie con número de página."""
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            title=title)
    styles = getSampleStyleSheet()
    elements = [Paragraph(title, styles["Title"]), Spacer(1, 0.15 * inch)]
    meta = f"Generado por: {user or 'sistema'}"
    if date_from or date_to:
        meta += f" | Rango: {date_from or '-'} a {date_to or '-'}"
    elements.append(Paragraph(meta, styles["Normal"]))
    elements.append(Spacer(1, 0.15 * inch))
    data = [headers] + [[_safe(v) for v in row] for row in rows]
    if totals:
        data.append([_safe(v) for v in totals])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2A44")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(table)

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(letter[0] - 0.5 * inch, 0.4 * inch, f"Página {doc_.page}")
        canvas.restoreState()

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return buf
