"""Carga de los datos de demostración en la base de datos (P2, paso 7).

Traduce los identificadores de texto de ``app/seed_data.json`` (``cli-001``,
``bkg-101``…) a claves primarias enteras y reescribe las claves foráneas usando
un mapa por colección. El orden de inserción respeta las dependencias.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .extensions import db

SEED_PATH = Path(__file__).parent / "seed_data.json"


# ----------------------------------------------------------------------
# Conversión de tipos del JSON
# ----------------------------------------------------------------------
def _dec(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d/%m/%Y, %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def load_raw() -> dict:
    """Lee el JSON de semilla (UTF-8)."""
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def clear_database() -> None:
    """Elimina todas las filas respetando el orden de dependencias."""
    from . import models as m

    for model in (
        m.NotificationRead, m.Notification,
        m.PromotionRedemption, m.Promotion,
        m.Payment, m.BookingPassenger, m.Booking,
        m.TravelDocument, m.Itinerary,
        m.RoomType, m.Hotel, m.Package, m.Activity,
        m.Transport, m.Flight, m.Destination,
        m.User, m.Client,
        m.NcfSequence, m.Setting, m.AuditLog,
    ):
        db.session.query(model).delete()
    db.session.flush()


def seed_database(reset: bool = False) -> bool:
    """Carga la semilla de forma idempotente.

    Devuelve ``True`` si sembró datos. Con ``reset=True`` vacía primero todas las
    tablas. Sin ``reset``, si ya hay usuarios no hace nada.
    """
    from . import models as m

    if not reset and db.session.query(m.User).count() > 0:
        return False

    clear_database()
    raw = load_raw()
    maps: dict[str, dict] = {}

    def remember(collection: str, old_id, new_id) -> None:
        maps.setdefault(collection, {})[old_id] = new_id

    def fk(collection: str, old_id):
        return maps.get(collection, {}).get(old_id)

    def add(obj):
        db.session.add(obj)
        db.session.flush()
        return obj

    # --- Destinos ---
    for d in raw["initial_destinations"]:
        obj = add(m.Destination(
            name=d.get("name"), country=d.get("country"), region=d.get("region"),
            cover_image=d.get("cover_image"), description=d.get("description"),
            weather_type=d.get("weather_type"), best_season=d.get("best_season"),
            high_season_months=d.get("high_season_months") or [],
            popular_attractions=d.get("popular_attractions") or [],
            base_price_usd=_dec(d.get("base_price_usd")), status=d.get("status", "Activo"),
            rating=d.get("rating") or 0,
        ))
        remember("destinations", d.get("id"), obj.id)

    # --- Hoteles y tipos de habitación ---
    for h in raw["initial_hotels"]:
        hotel = add(m.Hotel(
            name=h.get("name"), destination_id=fk("destinations", h.get("destination_id")),
            destination_name=h.get("destination_name"), stars=_int(h.get("stars")),
            address=h.get("address"), rating=h.get("rating") or 0, image=h.get("image"),
            contact_phone=h.get("contact_phone"), amenities=h.get("amenities") or [],
        ))
        remember("hotels", h.get("id"), hotel.id)
        for rt in h.get("room_types") or []:
            add(m.RoomType(
                hotel_id=hotel.id, name=rt.get("type"), price_per_night=_dec(rt.get("price_per_night")),
                rooms_total=_int(rt.get("available") or rt.get("rooms_total")),
            ))

    # --- Paquetes ---
    for p in raw["initial_packages"]:
        obj = add(m.Package(
            title=p.get("title"), destination_id=fk("destinations", p.get("destination_id")),
            destination_name=p.get("destination_name"), duration_days=_int(p.get("duration_days")),
            duration_nights=_int(p.get("duration_nights")), price_usd=_dec(p.get("price_usd")),
            original_price_usd=_dec(p.get("original_price_usd")),
            available_slots=_int(p.get("available_slots")), total_slots=_int(p.get("total_slots")),
            max_capacity=_int(p.get("max_capacity")), image=p.get("image"), image_url=p.get("image_url"),
            gallery=p.get("gallery") or [], category=p.get("category"), featured=bool(p.get("featured")),
            inclusions=p.get("inclusions") or [], itinerary_summary=p.get("itinerary_summary"),
            description=p.get("description"), departure_dates=p.get("departure_dates") or [],
        ))
        remember("packages", p.get("id"), obj.id)

    # --- Vuelos ---
    for v in raw["initial_flights"]:
        obj = add(m.Flight(
            airline=v.get("airline"), flight_number=v.get("flight_number"), origin=v.get("origin"),
            destination=v.get("destination"), departure_time=v.get("departure_time"),
            arrival_time=v.get("arrival_time"), price_usd=_dec(v.get("price_usd")),
            seats_available=_int(v.get("seats_available")), total_seats=_int(v.get("total_seats")),
            flight_class=v.get("flight_class"), status=v.get("status", "Disponible"),
            baggage_allowance=v.get("baggage_allowance"), image=v.get("image"),
        ))
        remember("flights", v.get("id"), obj.id)

    # --- Transporte ---
    for t in raw["initial_transports"]:
        obj = add(m.Transport(
            type=t.get("type"), route=t.get("route"), vehicle_model=t.get("vehicle_model"),
            capacity=_int(t.get("capacity")), available_seats=_int(t.get("available_seats")),
            driver_name=t.get("driver_name"), price_usd=_dec(t.get("price_usd")),
            status=t.get("status", "Disponible"), amenities=t.get("amenities") or [],
            image=t.get("image"),
        ))
        remember("transports", t.get("id"), obj.id)

    # --- Actividades ---
    for a in raw["initial_activities"]:
        obj = add(m.Activity(
            title=a.get("title"), destination_id=fk("destinations", a.get("destination_id")),
            destination_name=a.get("destination_name"), duration_hours=_int(a.get("duration_hours")),
            price_usd=_dec(a.get("price_usd")), includes_guide=bool(a.get("includes_guide")),
            difficulty=a.get("difficulty"), image=a.get("image"), description=a.get("description"),
            category=a.get("category"), schedule=a.get("schedule"), includes=a.get("includes") or [],
        ))
        remember("activities", a.get("id"), obj.id)

    # --- Clientes ---
    for c in raw["initial_clients"]:
        obj = add(m.Client(
            name=c.get("name"), email=c.get("email"), phone=c.get("phone"),
            document_id=c.get("document_id"), category=c.get("category"),
            budget_preference=c.get("budget_preference"),
            preferred_destinations=c.get("preferred_destinations") or [],
            trips_count=_int(c.get("trips_count")), total_spent=_dec(c.get("total_spent")),
            registration_date=_date(c.get("registration_date")), status=c.get("status", "Activo"),
            notes=c.get("notes"), passport_expiry=_date(c.get("passport_expiry")),
            nationality=c.get("nationality"),
        ))
        remember("clients", c.get("id"), obj.id)

    # --- Usuarios ---
    for u in raw["initial_users"]:
        obj = add(m.User(
            name=u.get("name"), email=u.get("email"), password_hash=u.get("password_hash"),
            role=u.get("role", "client"), department=u.get("department"), avatar=u.get("avatar"),
        ))
        remember("users", u.get("id"), obj.id)

    # --- Promociones ---
    for p in raw["initial_promotions"]:
        obj = add(m.Promotion(
            code=p.get("code"), title=p.get("title"),
            discount_percentage=_int(p.get("discount_percentage")),
            valid_until=_date(p.get("valid_until")), max_uses=_int(p.get("max_uses")),
            current_uses=_int(p.get("current_uses")),
            applicable_categories=p.get("applicable_categories") or [],
            active=bool(p.get("active", True)), description=p.get("description"),
        ))
        remember("promotions", p.get("id"), obj.id)

    # --- Reservas y pasajeros ---
    for b in raw["initial_bookings"]:
        booking = add(m.Booking(
            booking_code=b.get("booking_code"), client_id=fk("clients", b.get("client_id")),
            package_id=fk("packages", b.get("package_id")), package_name=b.get("package_name"),
            destination_name=b.get("destination_name"), hotel_id=fk("hotels", b.get("hotel_id")),
            hotel_name=b.get("hotel_name"), flight_id=fk("flights", b.get("flight_id")),
            flight_number=b.get("flight_number"), departure_date=_date(b.get("departure_date")),
            return_date=_date(b.get("return_date")), travelers=_int(b.get("travelers"), 1),
            total_price=_dec(b.get("total_price")), amount_paid=_dec(b.get("amount_paid")),
            status=b.get("status", "Pendiente"), payment_status=b.get("payment_status", "Pendiente"),
            notes=b.get("notes"), created_at=_datetime(b.get("created_at")),
        ))
        remember("bookings", b.get("id"), booking.id)
        for p in b.get("passengers") or []:
            add(m.BookingPassenger(
                booking_id=booking.id, full_name=p.get("full_name"), document=p.get("document"),
                age=_int(p.get("age")) if p.get("age") is not None else None, phone=p.get("phone"),
            ))

    # --- Pagos ---
    for p in raw["initial_payments"]:
        add(m.Payment(
            booking_id=fk("bookings", p.get("booking_id")), kind="pago",
            receipt_number=p.get("receipt_number"), amount=_dec(p.get("amount")),
            method=p.get("payment_method"), status=p.get("status", "Completado"),
            reference=p.get("transaction_ref"), invoice_number=p.get("invoice_number"),
            card_last4=p.get("card_last4"), created_at=_datetime(p.get("date")),
        ))

    # --- Notificaciones ---
    for n in raw["initial_notifications"]:
        add(m.Notification(
            title=n.get("title"), message=n.get("message"), type=n.get("type", "info"),
            date=n.get("date"), read=bool(n.get("read")), link_tab=n.get("link_tab"),
            visible_roles=n.get("visible_roles"),
        ))

    # --- Documentos ---
    for d in raw["initial_documents"]:
        add(m.TravelDocument(
            client_id=fk("clients", d.get("client_id")), doc_type=d.get("doc_type"),
            file_name=d.get("file_name"), status=d.get("status", "Válido"),
            upload_date=_date(d.get("upload_date")), expiry_date=_date(d.get("expiry_date")),
        ))

    # --- Auditoría ---
    for a in raw["initial_audit_logs"]:
        add(m.AuditLog(
            timestamp=_datetime(a.get("timestamp")), user_id=fk("users", a.get("user_id")),
            user_name=a.get("user_name"), user_role=a.get("user_role"), action=a.get("action"),
            module=a.get("module"), details=a.get("details"), ip_address=a.get("ip_address"),
        ))

    db.session.commit()
    return True
