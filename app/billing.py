"""
Módulo de facturación para DDN Travel (República Dominicana).
Proveevalidación de RNC, generación secuencial de NCF y creación de PDFs
de factura electrónica con diseño profesional.
"""

import re
import datetime
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
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
# NCF (Comprobante Fiscal) – secuencia atómica y persistente (RF-11, P4)
# ----------------------------------------------------------------------
# Formato: prefijo + 8 dígitos (p. ej. B02 → "B0200000001"). B01 si el cliente
# tiene RNC válido; B04 para notas de crédito. Simulación académica (no DGII).

def next_ncf(prefix: str, db_session=None) -> str:
    """Reserva y devuelve el siguiente NCF para ``prefix`` de forma atómica.

    El número devuelto es exactamente el reservado por esta transacción: el
    incremento se hace con una sentencia condicional y se comprueba el
    ``rowcount`` (SQLite) o con bloqueo de fila ``FOR UPDATE`` (PostgreSQL).
    No confirma: participa de la transacción del llamador, de modo que si el
    pago falla y revierte, el contador tampoco avanza de forma persistente.

    Lanza ``ValueError`` si la secuencia no existe y no puede crearse, está
    inactiva, está vencida o está agotada. Nunca devuelve un NCF inválido.
    """
    from sqlalchemy import update

    from .extensions import db
    from .models import NcfSequence

    session = db_session or db.session
    seq = session.get(NcfSequence, prefix)
    if seq is None:
        # Secuencia no inicializada: crearla con el rango por defecto.
        seq = NcfSequence(prefix=prefix, current=0, max_number=99999999,
                          expires_on=None, active=True)
        session.add(seq)
        session.flush()
    if not seq.active:
        raise ValueError(f"La secuencia NCF '{prefix}' está inactiva.")
    if seq.expires_on is not None and seq.expires_on < date.today():
        raise ValueError(f"La secuencia NCF '{prefix}' está vencida ({seq.expires_on}).")

    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        # Bloqueo de fila: los concurrentes esperan a que esta transacción
        # confirme o revierta antes de leer el contador.
        locked = (session.query(NcfSequence)
                  .filter(NcfSequence.prefix == prefix)
                  .with_for_update()
                  .one())
        if locked.max_number and (locked.current or 0) >= locked.max_number:
            raise ValueError(f"La secuencia NCF '{prefix}' está agotada.")
        locked.current = (locked.current or 0) + 1
        session.flush()
        return f"{prefix}{locked.current:08d}"

    # SQLite y otros: incremento condicional atómico en una sola sentencia.
    # Un max_number sin valor (0/None) conserva la semántica previa: sin tope.
    condition = [NcfSequence.prefix == prefix]
    if seq.max_number:
        condition.append(NcfSequence.current < seq.max_number)
    reserved = session.execute(
        update(NcfSequence).where(*condition).values(current=NcfSequence.current + 1))
    if reserved.rowcount != 1:
        raise ValueError(f"La secuencia NCF '{prefix}' está agotada.")
    session.refresh(seq)
    return f"{prefix}{seq.current:08d}"


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
    direccion_emitter: str = "",
    telefono_emitter: str = "",
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
    # Cabecera: marca + título (sin fila vacía [None, None]).
    logo_cell = Paragraph("<b>DDN TRAVEL</b>", styles["Title"])
    title_cell = Paragraph("FACTURA ELECTRÓNICA", styles["h1"])

    header_table = Table(
        [[logo_cell, title_cell]], colWidths=[5 * inch, 2.5 * inch]
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
        ["", "TOTAL", "", "", f"${total_amount:,.2f}"]
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

    # ------------ PIE DE PÁGINA (datos del emisor desde configuración) -------------
    pie_texts = [
        "---  Copia del cliente ---",
        f"{nombre_emitter} · {direccion_emitter or 'República Dominicana'}",
        f"Tel: {telefono_emitter or ''}  |  info@ddntravel.com".strip(),
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


def generar_pdf_voucher(booking, client) -> bytes:
    """Genera el voucher PDF de una reserva confirmada."""
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
    client_name = getattr(client, "name", None) or "Cliente"
    details = [
        ("Código de reserva", booking.booking_code),
        ("Cliente", client_name),
        ("Destino", booking.destination_name or "Por definir"),
        ("Paquete", booking.package_name or "No especificado"),
        ("Hotel", booking.hotel_name or "No especificado"),
        ("Salida", booking.departure_date or "Por definir"),
        ("Regreso", booking.return_date or "Por definir"),
        ("Viajeros", booking.travelers or 1),
        ("Total", f"${float(booking.total_price or 0):,.2f} USD"),
    ]
    table_data = [
        [Paragraph(f"<b>{escape(str(label))}</b>", styles["BodyText"]),
         Paragraph(escape(str(value)), styles["BodyText"])]
        for label, value in details
    ]
    elements = [
        Paragraph("VOUCHER DE RESERVA", styles["Title"]),
        Spacer(1, 12),
        Table(
            table_data,
            colWidths=[2 * inch, 4.5 * inch],
            style=TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]),
        ),
        Spacer(1, 12),
        Paragraph("Conserve este voucher y preséntelo durante su viaje.",
                  styles["BodyText"]),
    ]
    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


# Ejemplo rápido de uso:
#   from app.billing import validar_rnc, next_ncf, generar_pdf_factura
#   ok = validar_rnc("J302010123")   # → True