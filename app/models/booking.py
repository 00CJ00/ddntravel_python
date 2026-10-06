"""Reservas y pasajeros (RF-06, RN-01, RN-02, RN-03)."""
from __future__ import annotations

from sqlalchemy.orm import synonym

from ..extensions import db
from .base import BaseEntity, utcnow


class Booking(BaseEntity, db.Model):
    """Reserva de viaje. Concentra RN-01 a RN-03."""

    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    booking_code = db.Column(db.String(30), nullable=False, unique=True, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    package_id = db.Column(db.Integer, db.ForeignKey("packages.id"))
    package_name = db.Column(db.String(200))
    destination_name = db.Column(db.String(160), index=True)
    hotel_id = db.Column(db.Integer, db.ForeignKey("hotels.id"))
    hotel_name = db.Column(db.String(200))
    room_type_id = db.Column(db.Integer, db.ForeignKey("room_types.id"))
    rooms_count = db.Column(db.Integer, default=0)
    check_in = db.Column(db.Date)
    check_out = db.Column(db.Date)
    flight_id = db.Column(db.Integer, db.ForeignKey("flights.id"))
    flight_number = db.Column(db.String(30))
    transport_id = db.Column(db.Integer, db.ForeignKey("transports.id"))
    departure_date = db.Column(db.Date)
    return_date = db.Column(db.Date)
    travelers = db.Column(db.Integer, default=1)
    total_price = db.Column(db.Numeric(12, 2), default=0)
    amount_paid = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(20), default="Pendiente", index=True)
    payment_status = db.Column(db.String(20), default="Pendiente")
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True))

    # Alias de compatibilidad con el nombre corto del spec.
    code = synonym("booking_code")

    client = db.relationship("Client")
    # lazy="selectin": los pasajeros se cargan en una sola consulta por lote
    # (WHERE booking_id IN (...)) en vez de una consulta por cada reserva. Sin
    # esto /bookings dispara N+1: 22 consultas con 3 reservas y 79 con 60.
    passengers = db.relationship(
        "BookingPassenger", back_populates="booking", cascade="all, delete-orphan",
        lazy="selectin")

    # -- compatibilidad con las plantillas (valores derivados de la relación) --
    @property
    def client_name(self):
        return self.client.name if self.client else None

    @property
    def client_email(self):
        return self.client.email if self.client else None

    def balance_due(self):
        return max(0, (self.total_price or 0) - (self.amount_paid or 0))

    def is_fully_paid(self) -> bool:
        return (self.amount_paid or 0) >= (self.total_price or 0)

    def apply_payment(self, amount) -> None:
        self.amount_paid = (self.amount_paid or 0) + amount
        self.payment_status = "Pagado" if self.is_fully_paid() else "Parcial"
        if self.is_fully_paid():
            self.status = "Confirmada"

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["client_name"] = self.client_name
        data["client_email"] = self.client_email
        data["passengers"] = [p.to_dict() for p in self.passengers]
        return data

    def describe(self) -> str:
        return f"{self.booking_code} — {self.client_name}"


class BookingPassenger(BaseEntity, db.Model):
    """Pasajero incluido en una reserva."""

    __tablename__ = "booking_passengers"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, index=True)
    full_name = db.Column(db.String(160), nullable=False)
    document = db.Column(db.String(60))
    age = db.Column(db.Integer)
    phone = db.Column(db.String(40))

    booking = db.relationship("Booking", back_populates="passengers")
