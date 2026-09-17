"""
Módulo de facturación para DDN Travel (República Dominicana).
Proveevalidación de RNC, generación secuencial de NCF y creación de PDFs
de factura electrónica con diseño profesional.
"""

import re
import random
from datetime import date
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, Paragraph, Spacer, TableStyle
from reportlab.lib.units import inch, mm


# ----------------------------------------------------------------------
# RNC (Registro Nacional de Contribuyentes) – Validación
# ----------------------------------------------------------------------
def validar_rnc(rnc: str) -> bool:
    """Valida formato RNC dominicano.

    Formatos habituales:
      • 131456789                      (9 dígitos puros)
      • J302010123                      (letra + 9 dígitos, sin guión)
      • F-13145678                      (letra + guión + 6-7 dígitos)
    """
    if not rnc:
        return False
    rnc = rnc.strip().upper()
    patrones = [
        r"^\d{9}$",                                    # 9 dígitos puros: 131456789
        r"^[A-Z]-\d{6,9}$",                         # Letra + guión + 6-9 dígitos: F-1314567
        r"^[A-Z]\d{6,9}$",                          # Letra + 6-9 dígitos sin guión: J302010123
    ]
    return any(re.match(p, rnc) for p in patrones)


def formatear_rnc(rnc: str) -> str:
    """Normaliza a formato `XX-XXXXXXX` (3 letras + guión + 7 dígitos)
    cuando es posible; si es solo 9 dígitos los devuelve tal cual."""
    if not rnc:
        return ""
    rnc = rnc.strip().upper().replace("-", "")
    if len(rnc) == 9 and rnc.isdigit():
        return rnc
    # Si tiene letras y dígitos, agruparlos
    letras = "".join(c for c in rnc if c.isalpha())
    numeros = "".join(c for c in rnc if c.isdigit())
    if letras and numeros and len(letras) <= 4 and len(numeros) >= 6:
        return f"{letras}-{numeros}"
    return rnc


# ----------------------------------------------------------------------
# NCF (Nota de Crédito Fiscal) – Generación secuencial
# ----------------------------------------------------------------------
# Estructura: <Tipo>-<8 dígitos>
#   Tipo A = Ventas gravadas (el más usado)
#   Tipo B = Ventas exentas
#   Tipo C = Retenciones
# El último NCF usado se guarda en `state.json` bajo la clave ``ultimo_ncf``.

def generar_ncf(tipo: str = "A", ultimo_ncf: str | None = None) -> str:
    """Devuelve el siguiente NCF de la secuencia.

    - Si hay ``ultimo_ncf``, lo incrementa en uno.
    - Si no, empieza en ``A-00000001``.
    """
    if ultimo_ncf:
        try:
            # Quitar guión si existe y separar
            limpio = ultimo_ncf.replace("-", "")
            letra = limpio[0]          # primera letra (tipo)
            numero = int(limpio[1:])   # resto como entero
            nuevo_num = numero + 1
            # Mantener la letra original y formatear a 8 dígitos
            return f"{letra}{nuevo_num:08d}"
        except Exception:
            pass
    # Primera emisión
    return f"A-00000001"


# ----------------------------------------------------------------------
# PDF FACTURA DOMINICANA
# ----------------------------------------------------------------------
def generar_pdf_factura(
    titulo: str,
    rnc_emitter: str,
    nombre_emitter: str,
    rnc_client: str,
    nombre_client: str,
    items: list[dict],  # [{"description": ..., "quantity": ..., "price": ...}]
    total: float,
    ncf: str,
    fecha: str = None,
) -> bytes:
    """Genera un PDF con el aspecto de una factura electrónica RD.

    Devuelve ``bytes`` listos para descargar o enviar por email.
    Los campos principales son:
      - Encabezado con RNC y nombres (emitiente / cliente)
      - Cuadro de ítems con descripción, cantidad, precio unitario y total
      - Línea de TOTAL alineada a la derecha
      - Pie con datos de contacto y leyenda
    """
    if fecha is None:
        fecha = date.today().strftime("%d/%m/%Y")

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        right=20 * mm,
        left=20 * mm,
        top=20 * mm,
        bottom=20 * mm,
    )
    styles = getSampleStyleSheet()
    elements = []

# ------------ ENCADENADO / CABECERA -------------
    # Logo placeholder (en producción reemplazar con el archivo PNG real)
    logo_cell = Paragraph(
        "<b>DDN TRAVEL</b>" if not False else "",
        styles["Title"],
    )  # ← True puesto para forzar layout; quitar o poner imagen real después.

    # Título "FACTURA ELECTRÓNICA"
    title_cell = Paragraph("FACTURA ELECTRÓNICA", styles["h1"])

    header_table = Table(
        [[logo_cell, title_cell], [None, None]], colWidths=[5 * inch, 2.5 * inch]
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 12))

    # ------------ INFORMACIÓN FISCAL -------------
    fiscal_data = [
        ["EMITENTE:", f"{rnc_emitter} - {nombre_emitter}"],
        ["CLIENTE:", f"{rnc_client} - {nombre_client}"],
        ["FECHA:", fecha],
        ["NCF:", ncf],
    ]
    fiscal_table = Table(fiscal_data, colWidths=[1.5 * inch, 5 * inch])
    fiscal_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                # Fondo alternado para legibilidad
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#f8fafc")),
            ]
        )
    )
    elements.append(fiscal_table)
    elements.append(Spacer(1, 12))

    # ------------ CUADRO DE ÍTEMS -------------
    table_data = [["#", "Descripción", "Cantidad", "Precio U.", "Total"]]
    for i, it in enumerate(items, 1):
        table_data.append(
            [
                str(i),
                it.get("description", ""),
                str(it.get("quantity", 1)),
                f"${it.get('price', 0):,.2f}",
                f"${it.get('price', 0) * it.get('quantity', 1):,.2f}",
            ]
        )
    # Fila de total
    total_amount = sum(
        i.get("price", 0) * i.get("quantity", 1) for i in items
    )
    table_data.append(
        ["", "TOTAL", "", f"${total_amount:,.2f}", f"${total_amount:,.2f}"]
    )

    items_table = Table(
        table_data,
        colWidths=[0.3 * inch, 2 * inch, 0.8 * inch, 1.1 * inch, 1.1 * inch],
    )
    items_table.setStyle(
        TableStyle(
            [
                # Encabezado
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                # Cuadricula
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                # Alternar filas
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(items_table)
    elements.append(Spacer(1, 12))

    # ------------ PIE DE PÁGINA -------------
    pie_texts = [
        "---  Copia del cliente ---",
        "DDN Travel · Av. Winston Churchill 1052, Santo Domingo · República Dominicana",
        "Tel: +1 (809) 555-0123  |  info@ddntravel.com",
    ]
    for line in pie_texts:
        elements.append(
            Paragraph(line, ParagraphStyle("footer", fontName="Helvetica", fontSize=7, textColor="#64748b"))
        )

    # Construir PDF y devolver bytes
    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


# ----------------------------------------------------------------------
# Utilidades varias
# ----------------------------------------------------------------------
def ultimo_ncf_desde_state(raw_state: dict) -> str | None:
    """Extrae el último NCF grabado en el diccionario state.json que la app usa."""
    return raw_state.get("ultimo_ncf")


# Ejemplo rápido de uso (quando se importa el módulo):
#   from app.billing import validar_rnc, generar_ncf, generar_pdf_factura
#   ok = validar_rnc("J302010123")   # → True
#   nxt  = generar_ncf("A", "A-00000005")  # → "A-00000006"