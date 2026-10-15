"""Repositorio de documentos de viaje (RF-17)."""
from __future__ import annotations

import os
import uuid

from flask import current_app
from sqlalchemy import desc
from werkzeug.utils import secure_filename

from .. import models as m
from .base import all_of, assign_by_type, delete, get, save


ALLOWED_EXTENSIONS = {"pdf", "jpg", "png"}
MAGIC_BYTES = {
    "pdf": (b"%PDF",),
    "jpg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
}


def list_documents():
    return all_of(m.TravelDocument, desc(m.TravelDocument.created_at))


def get_document(ident):
    return get(m.TravelDocument, ident)


def get_booking_voucher(booking_id):
    return (m.TravelDocument.query
            .filter_by(booking_id=booking_id, doc_type="Voucher de Reserva")
            .order_by(m.TravelDocument.id.asc())
            .first())


def create_document(data):
    doc = m.TravelDocument()
    assign_by_type(doc, data, skip=("id",))
    return save(doc)


def delete_document(obj) -> None:
    delete(obj)


def validate_file(file_storage) -> tuple[bool, str]:
    """Valida extensión y firma (magic bytes) de un archivo subido.

    Devuelve (es_valido, mensaje_error).
    """
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        return False, "El archivo no tiene nombre."
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Extensión no permitida: .{ext}. Usa pdf, jpg o png."
    magic = MAGIC_BYTES.get(ext, ())
    head = file_storage.read(8)
    file_storage.seek(0)
    if not any(head.startswith(sig) for sig in magic):
        return False, f"El contenido del archivo no coincide con la extensión .{ext}."
    return True, ""


def save_file(file_storage, stored_name: str) -> str:
    """Guarda el archivo físico en UPLOAD_DIR con nombre UUID. Devuelve la ruta."""
    upload_dir = current_app.config.get("UPLOAD_DIR", "instance/uploads")
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, stored_name)
    file_storage.save(path)
    return path


def save_pdf_bytes(pdf_bytes: bytes) -> str:
    """Guarda bytes PDF en UPLOAD_DIR y devuelve el nombre UUID del archivo."""
    upload_dir = current_app.config.get("UPLOAD_DIR", "instance/uploads")
    os.makedirs(upload_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.pdf"
    path = os.path.join(upload_dir, stored_name)
    with open(path, "xb") as pdf_file:
        pdf_file.write(pdf_bytes)
    return stored_name


def upload_document_file(file_storage) -> tuple[str, str, str, int]:
    """Sube un archivo validado. Devuelve (stored_name, original_name, mime, size)."""
    ok, msg = validate_file(file_storage)
    if not ok:
        raise ValueError(msg)
    original = secure_filename(file_storage.filename or "documento")
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    stored = f"{uuid.uuid4().hex}.{ext}"
    path = save_file(file_storage, stored)
    mime = file_storage.mimetype or "application/octet-stream"
    size = os.path.getsize(path)
    return stored, original, mime, size
