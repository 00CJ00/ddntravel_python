"""Documentos de viaje (RF-17)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


def _human_size(num_bytes) -> str:
    """Convierte un tamaño en bytes a un texto legible (p. ej. '2.4 MB')."""
    if not num_bytes:
        return ""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class TravelDocument(BaseEntity, db.Model):
    """Documento (pasaporte, visa, voucher, etc.) de un cliente."""

    __tablename__ = "travel_documents"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"))
    doc_type = db.Column(db.String(80))
    file_name = db.Column(db.String(255))
    stored_name = db.Column(db.String(255))
    mime = db.Column(db.String(120))
    size_bytes = db.Column(db.Integer)
    status = db.Column(db.String(30), default="Válido", index=True)
    expiry_date = db.Column(db.Date)
    upload_date = db.Column(db.Date)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    @property
    def file_size(self):
        """Alias de compatibilidad con el antiguo campo de texto."""
        return _human_size(self.size_bytes)

    def describe(self) -> str:
        return self.file_name or self.doc_type or "Documento"
