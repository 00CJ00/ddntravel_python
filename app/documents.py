"""Gestión de archivos de documentos (RF-17, fase P6).

Infraestructura de almacenamiento: validación de extensiones y firmas
(magic bytes), guardado con nombre UUID bajo ``UPLOAD_DIR`` (fuera de
``static/``) y estado de vencimiento calculado. La orquestación con la base
de datos vive en ``DataStore``; este módulo no confirma transacciones.
"""
from __future__ import annotations

import datetime
import os
import uuid

ALLOWED_EXTENSIONS = frozenset({"pdf", "jpg", "jpeg", "png"})

# Firma inicial exigible por extensión (no basta el MIME declarado).
MAGIC_SIGNATURES = {
    "pdf": (b"%PDF",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
}

MIME_BY_EXTENSION = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}


class DocumentError(ValueError):
    """El archivo subido no es aceptable (extensión, firma, tamaño o disco)."""


def extension_of(filename: str) -> str:
    """Extensión en minúsculas sin el punto ("" si no tiene)."""
    name = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def check_signature(stream, extension: str) -> None:
    """Verifica los magic bytes del inicio del flujo.

    Lanza ``DocumentError`` si no coinciden con la extensión declarada.
    Deja el cursor al inicio para la lectura posterior.
    """
    signatures = MAGIC_SIGNATURES.get(extension)
    if not signatures:
        raise DocumentError(f"Extensión no permitida: .{extension}")
    head = stream.read(max(len(s) for s in signatures))
    stream.seek(0)
    if not any(head.startswith(s) for s in signatures):
        raise DocumentError(
            f"El contenido no corresponde a un archivo .{extension} válido.")


def stream_size(stream) -> int:
    """Tamaño en bytes del flujo sin consumirlo."""
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


def save_uploaded_file(file_storage, upload_dir: str, max_bytes: int) -> dict:
    """Valida y guarda un archivo subido. Devuelve sus datos de registro.

    ``file_storage`` es un ``werkzeug.FileStorage``. El archivo se guarda con
    un nombre UUID + extensión verificada; nunca con el nombre del usuario.
    Lanza ``DocumentError`` ante extensión, firma, vacío, exceso de tamaño o
    fallo de escritura (sin dejar registros a medias: quien llama no debe
    crear la fila si esto falla).
    """
    original = getattr(file_storage, "filename", "") or ""
    extension = extension_of(original)
    if extension not in ALLOWED_EXTENSIONS:
        raise DocumentError(
            "Solo se aceptan archivos .pdf, .jpg y .png.")
    stream = file_storage.stream
    check_signature(stream, extension)
    size = stream_size(stream)
    if size <= 0:
        raise DocumentError("El archivo está vacío.")
    if size > max_bytes:
        raise DocumentError(
            f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB.")
    os.makedirs(upload_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{extension}"
    path = os.path.join(upload_dir, stored_name)
    try:
        file_storage.save(path)
    except OSError as exc:
        raise DocumentError(f"No se pudo guardar el archivo: {exc}") from exc
    if not os.path.isfile(path) or os.path.getsize(path) != size:
        try:
            os.remove(path)
        except OSError:
            pass
        raise DocumentError("El archivo quedó incompleto al guardarse.")
    return {
        "file_name": original.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:255],
        "stored_name": stored_name,
        "mime": MIME_BY_EXTENSION[extension],
        "size_bytes": size,
    }


def delete_stored_file(upload_dir: str, stored_name: str | None) -> bool:
    """Borra el archivo físico (mejor esfuerzo). Devuelve si lo eliminó."""
    if not stored_name:
        return False
    base = os.path.basename(stored_name)
    if base != stored_name or base in ("", ".", ".."):
        return False
    try:
        os.remove(os.path.join(upload_dir, base))
        return True
    except OSError:
        return False


def add_months(day: datetime.date, months: int) -> datetime.date:
    """Suma meses naturales con tope a fin de mes."""
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    import calendar
    last = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, min(day.day, last))


def expiry_status(expiry_date, today: datetime.date | None = None) -> str:
    """Estado calculado del vencimiento: `vigente`, `por vencer` o `vencido`.

    `por vencer` = vence en menos de seis meses naturales (estrictamente
    menor; exactamente a 6 meses sigue `vigente`). Sin fecha → `vigente`.
    No se persiste: se calcula al leer.
    """
    if expiry_date is None:
        return "vigente"
    if isinstance(expiry_date, datetime.datetime):
        expiry_date = expiry_date.date()
    today = today or datetime.date.today()
    if expiry_date < today:
        return "vencido"
    if expiry_date < add_months(today, 6):
        return "por vencer"
    return "vigente"


def store_bytes(content: bytes, extension: str, upload_dir: str,
                original_name: str) -> dict:
    """Guarda bytes ya generados (p. ej. un voucher PDF) con nombre UUID.

    Devuelve el mismo dict de registro que ``save_uploaded_file``. Lanza
    ``DocumentError`` si el contenido está vacío o falla la escritura.
    """
    if not content:
        raise DocumentError("El contenido a guardar está vacío.")
    extension = (extension or "").lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise DocumentError(f"Extensión no permitida: .{extension}")
    os.makedirs(upload_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{extension}"
    path = os.path.join(upload_dir, stored_name)
    try:
        with open(path, "wb") as fh:
            fh.write(content)
    except OSError as exc:
        raise DocumentError(f"No se pudo guardar el archivo: {exc}") from exc
    if not os.path.isfile(path) or os.path.getsize(path) != len(content):
        try:
            os.remove(path)
        except OSError:
            pass
        raise DocumentError("El archivo quedó incompleto al guardarse.")
    safe_original = (original_name or f"documento.{extension}")
    safe_original = safe_original.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:255]
    return {
        "file_name": safe_original,
        "stored_name": stored_name,
        "mime": MIME_BY_EXTENSION[extension],
        "size_bytes": len(content),
    }


def generar_pdf_voucher(booking, client_name: str) -> bytes:
    """Genera el voucher PDF real de una reserva confirmada (ReportLab).

    Solo usa datos del modelo (sin inventar): código, cliente, destino,
    fechas, viajeros, hotel/vuelo/transporte y total.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from io import BytesIO

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            right=20 * mm, left=20 * mm, top=20 * mm, bottom=20 * mm)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("<b>DDN TRAVEL — VOUCHER DE RESERVA</b>", styles["Title"]),
        Spacer(1, 12),
    ]
    filas = [
        ["Reserva:", getattr(booking, "booking_code", "") or ""],
        ["Cliente:", client_name or ""],
        ["Destino:", getattr(booking, "destination_name", "") or ""],
        ["Salida:", str(getattr(booking, "departure_date", "") or "")],
        ["Regreso:", str(getattr(booking, "return_date", "") or "")],
        ["Viajeros:", str(getattr(booking, "travelers", "") or "")],
        ["Hotel:", getattr(booking, "hotel_name", "") or "—"],
        ["Vuelo:", getattr(booking, "flight_number", "") or "—"],
        ["Total:", f"${float(getattr(booking, 'total_price', 0) or 0):,.2f} USD"],
        ["Estado:", getattr(booking, "status", "") or ""],
    ]
    tabla = Table(filas, colWidths=[90, 380])
    tabla.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(tabla)
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(
        "Presente este voucher al momento del viaje. DDN Travel.",
        styles["Normal"]))
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf
