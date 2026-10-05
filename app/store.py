"""DataStore: estado central de la aplicación DDN Travel.

Es el equivalente en Python de `AppContext.tsx`: mantiene todas las listas
de datos en memoria y expone los métodos de negocio (crear reserva, registrar
pago, aplicar cupón, etc.) respetando las mismas reglas de negocio (RN-01 a
RN-05) que la versión original en React/TypeScript.
"""
from __future__ import annotations
import json
import random
import functools
import datetime
from pathlib import Path

from .models import (
    UserSession, Client, Destination, TourPackage, Hotel, Flight,
    TouristTransport, TouristActivity, Booking, PaymentTransaction,
    Promotion, NotificationItem, AuditLog, TravelDocument,
    new_id, short_code,
)

SEED_PATH = Path(__file__).parent / "seed_data.json"
STATE_PATH = Path(__file__).parent / "state.json"

# Mapeo de colecciones del store -> clase de entidad (para rehidratar al cargar)
COLLECTION_CLASSES = {
    "available_users": UserSession,
    "clients": Client,
    "destinations": Destination,
    "packages": TourPackage,
    "hotels": Hotel,
    "flights": Flight,
    "transports": TouristTransport,
    "activities": TouristActivity,
    "bookings": Booking,
    "payments": PaymentTransaction,
    "promotions": Promotion,
    "notifications": NotificationItem,
    "audit_logs": AuditLog,
    "documents": TravelDocument,
}


# ------------------------------------------------------------------
# Utilidades de fecha y hora
# ------------------------------------------------------------------
def _now_str() -> str:
    return datetime.datetime.now().strftime("%d/%m/%Y, %H:%M")


def _today() -> str:
    return datetime.date.today().isoformat()


# Lista de métodos que deben aplicar persistencia automática
_AUTOSAVE_METHODS = frozenset([
    "add_client", "update_client", "delete_client",
    "add_destination", "edit_destination", "delete_destination",
    "add_hotel", "edit_hotel", "delete_hotel",
    "add_flight", "edit_flight", "delete_flight",
    "add_transport", "edit_transport", "delete_transport",
    "add_activity", "edit_activity", "delete_activity",
    "add_package", "edit_package", "delete_package",
    "create_booking", "update_booking_status", "cancel_booking", "update_booking",
    "register_payment", "verify_payment", "add_promotion", "toggle_promotion_status",
    "add_document", "delete_document",
    "log_action", "add_notification",
    "mark_notification_as_read", "mark_all_notifications_as_read",
    "create_user", "update_user", "reset_user_password", "deactivate_user",
])


def _apply_autosave(method):
    """Decorador que persiste el estado en disco después de cada operación que muta datos."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        result = method(self, *args, **kwargs)
        self.persist()
        return result
    return wrapper


PAYMENT_METHODS = ["Tarjeta de Crédito", "Transferencia Bancaria", "Efectivo", "Cripto", "PayPal"]

MIN_DEPOSIT_PCT = 100  # Configurable: porcentaje mínimo de depósito para confirmar


# ------------------------------------------------------------------
# Clase DataStore
# ------------------------------------------------------------------
class DataStore:
    """Contenedor único (singleton a nivel de módulo) de todo el estado de la app."""

    def __init__(self):
        self._raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        self.reset_all_data(log=False)
        self.promotion_redemptions = []
        if STATE_PATH.exists():
            self._load_state()

    # ------------------------------------------------------------------
    # Persistencia en disco (los datos sobreviven al reinicio del servidor)
    # ------------------------------------------------------------------
    def persist(self) -> None:
        """Guarda todas las colecciones en STATE_PATH como JSON."""
        data = {attr: [item.to_dict() for item in getattr(self, attr, [])]
                for attr in COLLECTION_CLASSES}
        data["predictive_data"] = self.predictive_data if self.predictive_data is not None else None
        data["promotion_redemptions"] = getattr(self, "promotion_redemptions", [])
        try:
            STATE_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load_state(self):
        """Rehidrata las entidades desde el último estado guardado en disco."""
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for attr, cls in COLLECTION_CLASSES.items():
            items = data.get(attr, [])
            setattr(self, attr, [cls(**item) for item in items])
        self.predictive_data = data.get("predictive_data")
        self.promotion_redemptions = data.get("promotion_redemptions", [])

    # ------------------------------------------------------------------
    # Carga / reinicio de datos de demostración
    # ------------------------------------------------------------------
    def reset_all_data(self, log: bool = True) -> None:
        raw = self._raw
        self.available_users = [UserSession(**u) for u in raw["initial_users"]]
        self.clients = [Client(**c) for c in raw["initial_clients"]]
        self.destinations = [Destination(**d) for d in raw["initial_destinations"]]
        self.packages = [TourPackage(**p) for p in raw["initial_packages"]]
        self.hotels = [Hotel(**h) for h in raw["initial_hotels"]]
        self.flights = [Flight(**f) for f in raw["initial_flights"]]
        self.transports = [TouristTransport(**t) for t in raw["initial_transports"]]
        self.activities = [TouristActivity(**a) for a in raw["initial_activities"]]
        self.bookings = [Booking(**b) for b in raw["initial_bookings"]]
        self.payments = [PaymentTransaction(**p) for p in raw["initial_payments"]]
        self.promotions = [Promotion(**p) for p in raw["initial_promotions"]]
        self.notifications = [NotificationItem(**n) for n in raw["initial_notifications"]]
        self.audit_logs = [AuditLog(**a) for a in raw["initial_audit_logs"]]
        self.documents = [TravelDocument(**d) for d in raw["initial_documents"]]
        self.predictive_data = None
        self.promotion_redemptions = []
        if log:
            self.log_action("system", "Sistema", "RESET_DATOS", "Sistema",
                             "Datos de demostración restablecidos correctamente.")

    # ------------------------------------------------------------------
    # Utilidades de búsqueda
    # ------------------------------------------------------------------
    def get_user(self, user_id: str) -> UserSession | None:
        return next((u for u in self.available_users if u.id == user_id), None)

    def get_client(self, client_id: str) -> Client | None:
        return next((c for c in self.clients if c.id == client_id), None)

    def get_package(self, package_id: str) -> TourPackage | None:
        return next((p for p in self.packages if p.id == package_id), None)

    def get_booking(self, booking_id: str) -> Booking | None:
        return next((b for b in self.bookings if b.id == booking_id), None)

    def get_hotel(self, hotel_id: str) -> Hotel | None:
        return next((h for h in self.hotels if h.id == hotel_id), None)

    def get_flight(self, flight_id: str) -> Flight | None:
        return next((f for f in self.flights if f.id == flight_id), None)

    def get_transport(self, transport_id: str) -> TouristTransport | None:
        return next((t for t in self.transports if t.id == transport_id), None)

    def get_payment(self, payment_id: str) -> PaymentTransaction | None:
        return next((p for p in self.payments if p.id == payment_id), None)

    def get_destination(self, dest_id: str) -> Destination | None:
        return next((d for d in self.destinations if d.id == dest_id), None)

    def get_activity(self, activity_id: str) -> TouristActivity | None:
        return next((a for a in self.activities if a.id == activity_id), None)

    # ------------------------------------------------------------------
    # Pago verificado (spec P3): solo Completado cuenta como pago.
    # ------------------------------------------------------------------
    def verify_payment(self, current_user, payment_id: str) -> dict:
        """Marca un pago como Completado (verificado manualmente) y retransita la reserva."""
        payment = self.get_payment(payment_id)
        if payment is None:
            return {"success": False, "message": "Pago no encontrado."}
        if payment.status == "Completado":
            return {"success": True, "message": "El pago ya estaba verificado.", "payment": payment}
        if payment.status == "Anulado":
            return {"success": False, "message": "No se puede verificar un pago anulado."}
        payment.status = "Completado"
        booking = self.get_booking(payment.booking_id)
        if booking is not None and booking.status != "Cancelada":
            booking.amount_paid += payment.amount
            booking.payment_status = "Pagado" if booking.amount_paid >= booking.total_price else "Parcial"
            if booking.amount_paid >= booking.total_price and booking.total_price > 0:
                BookingService.transition(self, booking, "Confirmada")
        self.log_action(current_user.id, current_user.name, "VERIFICAR_PAGO", "Pagos & Facturación",
                         f"Pago {payment.receipt_number} verificado (${payment.amount} USD).")
        return {"success": True, "message": "Pago verificado correctamente.", "payment": payment}

    # ------------------------------------------------------------------
    # Auditoría y notificaciones (RN-05)
    # ------------------------------------------------------------------
    def log_action(self, user_id: str, user_name: str, action: str, module: str, details: str) -> None:
        user = self.get_user(user_id)
        log = AuditLog(
            id=new_id("log"),
            timestamp=_now_str(),
            user_id=user_id,
            user_name=user_name if user else "system",
            user_role=user.role if user else "system",
            action=action,
            module=module,
            details=details,
            ip_address=f"190.166.42.{random.randint(10, 90)}",
        )
        self.audit_logs.insert(0, log)

    # Notificaciones de módulos internos: solo las ven admin y empleados.
    INTERNAL_NOTIFICATION_TABS = {
        "clients", "bookings", "payments", "promotions", "documents",
        "hotels", "flights", "transports", "activities", "audit", "dashboard",
    }

    def add_notification(self, title: str, message: str, ntype: str = "info",
                         link_tab: str | None = None, roles: list | None = None) -> None:
        if roles is None:
            roles = ["admin", "employee"] if link_tab in self.INTERNAL_NOTIFICATION_TABS else None
        notif = NotificationItem(
            id=new_id("notif"), title=title, message=message, type=ntype,
            date="Justo ahora", read=False, link_tab=link_tab, visible_roles=roles,
        )
        self.notifications.insert(0, notif)

    def mark_notification_as_read(self, notif_id: str) -> None:
        for n in self.notifications:
            if n.id == notif_id:
                n.read = True

    def mark_all_notifications_as_read(self) -> None:
        for n in self.notifications:
            n.read = True

    # ------------------------------------------------------------------
    # Clientes (RF-03)
    # ------------------------------------------------------------------
    def add_client(self, current_user, **data) -> Client:
        client = Client(
            id=new_id("cli"),
            registration_date=_today(),
            trips_count=0,
            total_spent=0,
            **data,
        )
        self.clients.insert(0, client)
        self.log_action(current_user.id, current_user.name, "CREAR_CLIENTE", "Clientes",
                         f"Registrado nuevo cliente: {client.name} ({client.category})")
        self.add_notification("Nuevo Cliente Registrado", f"{client.name} fue añadido a la base de datos.",
                               "info", "clients")
        return client

    def update_client(self, current_user, client_id: str, **changes) -> None:
        client = self.get_client(client_id)
        if client:
            # Guardar estado antes para auditoría
            before = client.to_dict()
            client.update(**changes)
            after = client.to_dict()
            self.log_action(current_user.id, current_user.name, "MODIFICAR_CLIENTE", "Clientes",
                             f"Actualizada información del cliente ID: {client_id}. Antes: {before}, Después: {after}")

    def delete_client(self, current_user, client_id: str) -> bool:
        client = self.get_client(client_id)
        if not client:
            return False
        # Soft delete: marcar como inactivo en lugar de eliminar físicamente
        client.is_active = False
        client.deleted_at = datetime.datetime.now().isoformat()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_CLIENTE", "Clientes",
                         f"Desactivado cliente ID: {client_id}")
        return True

    # ------------------------------------------------------------------
    # Catálogo genérico (destinos, hoteles, vuelos, transportes, actividades)
    # ------------------------------------------------------------------
    def add_destination(self, current_user, **data) -> Destination:
        # Validación de campos permitidos (white list)
        allowed = {"name", "country", "region", "cover_image", "description",
                   "weather_type", "best_season", "high_season_months",
                   "popular_attractions", "base_price_usd", "status", "rating"}
        data = {k: v for k, v in data.items() if k in allowed}
        dest = Destination(id=new_id("dst"), **data)
        self.destinations.insert(0, dest)
        self.log_action(current_user.id, current_user.name, "CREAR_DESTINO", "Destinos",
                         f"Registrado nuevo destino: {dest.name}")
        self.persist()
        return dest

    def edit_destination(self, current_user, dest_id: str, **data) -> Destination | None:
        dest = next((d for d in self.destinations if d.id == dest_id), None)
        if not dest:
            return None
        # White list de campos permitidos (para evitar sobrescribir 'id' u otros protegidos)
        allowed = {"name", "country", "region", "cover_image", "description",
                   "weather_type", "best_season", "high_season_months",
                   "popular_attractions", "base_price_usd", "status", "rating"}
        for key, value in data.items():
            if key in allowed:
                setattr(dest, key, value)
        self.log_action(current_user.id, current_user.name, "EDITAR_DESTINO", "Destinos",
                         f"Actualizado destino ID: {dest_id} - {dest.name}")
        self.persist()
        return dest

    def add_hotel(self, current_user, **data) -> Hotel:
        hotel = Hotel(id=new_id("htl"), **data)
        self.hotels.insert(0, hotel)
        self.log_action(current_user.id, current_user.name, "CREAR_HOTEL", "Hoteles",
                         f"Registrado nuevo hotel: {hotel.name}")
        return hotel

    def delete_hotel(self, current_user, hotel_id: str) -> bool:
        hotel = next((h for h in self.hotels if h.id == hotel_id), None)
        if not hotel:
            return False
        # Soft delete: solo si no hay reservas activas que lo referencien
        has_active_bookings = any(
            b.hotel_id == hotel_id and b.status != "Cancelada" for b in self.bookings
        )
        if has_active_bookings:
            return False  # 409 equivalent - cannot delete
        # Soft delete
        hotel.is_active = False
        hotel.deleted_at = datetime.datetime.now().isoformat()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_HOTEL", "Hoteles",
                         f"Desactivado hotel ID: {hotel_id}")
        return True

    def edit_hotel(self, current_user, hotel_id: str, **data) -> Hotel | None:
        hotel = self.get_hotel(hotel_id)
        if not hotel:
            return None
        allowed = {"name", "destination_id", "destination_name", "stars", "address", "rating",
                   "image", "contact_phone", "amenities", "room_types"}
        before = hotel.to_dict()
        for key, value in data.items():
            if key in allowed:
                setattr(hotel, key, value)
        self.log_action(current_user.id, current_user.name, "EDITAR_HOTEL", "Hoteles",
                         f"Antes: {before}, Después: {hotel.to_dict()}")
        return hotel

    def add_flight(self, current_user, **data) -> Flight:
        flight = Flight(id=new_id("flt"), **data)
        self.flights.insert(0, flight)
        self.log_action(current_user.id, current_user.name, "CREAR_VUELO", "Vuelos",
                         f"Registrado nuevo vuelo: {flight.airline} {flight.flight_number}")
        return flight

    def delete_flight(self, current_user, flight_id: str) -> bool:
        flight = next((f for f in self.flights if f.id == flight_id), None)
        if not flight:
            return False
        # Soft delete: solo si no hay reservas activas que lo referencien
        has_active_bookings = any(
            b.flight_id == flight_id and b.status != "Cancelada" for b in self.bookings
        )
        if has_active_bookings:
            return False  # 409 equivalent - cannot delete
        # Soft delete
        flight.is_active = False
        flight.deleted_at = datetime.datetime.now().isoformat()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_VUELO", "Vuelos",
                         f"Desactivado vuelo ID: {flight_id}")
        return True

    def add_transport(self, current_user, **data) -> TouristTransport:
        transport = TouristTransport(id=new_id("trn"), **data)
        self.transports.insert(0, transport)
        self.log_action(current_user.id, current_user.name, "CREAR_TRANSPORTE", "Transporte",
                         f"Registrada unidad de transporte: {transport.vehicle_model}")
        return transport

    def delete_transport(self, current_user, transport_id: str) -> bool:
        transport = next((t for t in self.transports if t.id == transport_id), None)
        if not transport:
            return False
        # Soft delete: solo si no hay reservas activas que lo referencien
        has_active_bookings = any(
            b.transport_id == transport_id and b.status != "Cancelada" for b in self.bookings
        )
        if has_active_bookings:
            return False  # 409 equivalent - cannot delete
        # Soft delete
        transport.is_active = False
        transport.deleted_at = datetime.datetime.now().isoformat()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_TRANSPORTE", "Transporte",
                         f"Desactivado transporte ID: {transport_id}")
        return True

    def add_activity(self, current_user, **data) -> TouristActivity:
        activity = TouristActivity(id=short_code("act"), **data)
        self.activities.append(activity)
        self.log_action(current_user.id, current_user.name, "CREAR_ACTIVIDAD", "Actividades",
                         f"Registrada actividad turística: {activity.title}")
        return activity

    def delete_activity(self, current_user, activity_id: str) -> bool:
        if current_user.role != "admin":
            return False
        activity = next((a for a in self.activities if a.id == activity_id), None)
        if not activity:
            return False
        activity.is_active = False
        activity.deleted_at = datetime.datetime.now().isoformat()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_ACTIVIDAD", "Actividades",
                         f"Desactivada actividad ID: {activity_id}")
        return True

    def edit_flight(self, current_user, flight_id: str, **data) -> Flight | None:
        flight = self.get_flight(flight_id)
        if not flight:
            return None
        allowed = {"airline", "flight_number", "origin", "destination", "departure_time", "arrival_time",
                   "price_usd", "seats_available", "total_seats", "flight_class", "status",
                   "baggage_allowance", "image"}
        before = flight.to_dict()
        for key, value in data.items():
            if key in allowed:
                setattr(flight, key, value)
        self.log_action(current_user.id, current_user.name, "EDITAR_VUELO", "Vuelos",
                         f"Antes: {before}, Después: {flight.to_dict()}")
        return flight

    def edit_transport(self, current_user, transport_id: str, **data) -> TouristTransport | None:
        transport = self.get_transport(transport_id)
        if not transport:
            return None
        allowed = {"type", "route", "vehicle_model", "capacity", "available_seats", "driver_name",
                   "price_usd", "status", "amenities", "image"}
        before = transport.to_dict()
        for key, value in data.items():
            if key in allowed:
                setattr(transport, key, value)
        self.log_action(current_user.id, current_user.name, "EDITAR_TRANSPORTE", "Transporte",
                         f"Antes: {before}, Después: {transport.to_dict()}")
        return transport

    def edit_activity(self, current_user, activity_id: str, **data) -> TouristActivity | None:
        activity = self.get_activity(activity_id)
        if not activity:
            return None
        allowed = {"title", "destination_id", "destination_name", "duration_hours", "price_usd",
                   "includes_guide", "difficulty", "image", "description", "category", "schedule"}
        before = activity.to_dict()
        for key, value in data.items():
            if key in allowed:
                setattr(activity, key, value)
        self.log_action(current_user.id, current_user.name, "EDITAR_ACTIVIDAD", "Actividades",
                         f"Antes: {before}, Después: {activity.to_dict()}")
        return activity

    def delete_destination(self, current_user, dest_id: str) -> bool:
        dest = self.get_destination(dest_id)
        if not dest:
            return False
        if any(b.destination_name == getattr(dest, "name", "") and b.status != "Cancelada"
               for b in self.bookings):
            return False
        dest.is_active = False
        dest.deleted_at = datetime.datetime.now().isoformat()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_DESTINO", "Destinos",
                         f"Desactivado destino ID: {dest_id}")
        return True

    # ------------------------------------------------------------------
    # Paquetes (RF-05)
    # ------------------------------------------------------------------
    def add_package(self, current_user, **data) -> TourPackage:
        pkg = TourPackage(id=new_id("pkg"), **data)
        self.packages.insert(0, pkg)
        self.log_action(current_user.id, current_user.name, "CREAR_PAQUETE", "Paquetes",
                         f"Registrado nuevo paquete: {pkg.title}")
        return pkg

    def edit_package(self, current_user, pkg_id: str, **data) -> TourPackage | None:
        pkg = self.get_package(pkg_id)
        if not pkg:
            return None
        allowed = {"title", "destination_id", "destination_name", "duration_days", "duration_nights",
                   "price_usd", "original_price_usd", "available_slots", "total_slots", "max_capacity",
                   "image", "image_url", "gallery", "category", "featured", "inclusions", "departure_dates"}
        before = pkg.to_dict()
        _ints = {"duration_days", "duration_nights", "available_slots", "total_slots", "max_capacity"}
        _floats = {"price_usd", "original_price_usd"}
        for key, value in data.items():
            if key in allowed:
                try:
                    if key in _ints:
                        value = int(float(value))
                    elif key in _floats:
                        value = float(value)
                except (TypeError, ValueError):
                    continue
                setattr(pkg, key, value)
        self.log_action(current_user.id, current_user.name, "EDITAR_PAQUETE", "Paquetes",
                         f"Antes: {before}, Después: {pkg.to_dict()}")
        return pkg

    def delete_package(self, current_user, pkg_id: str) -> bool:
        pkg = self.get_package(pkg_id)
        if not pkg:
            return False
        if any(b.package_id == pkg_id and b.status != "Cancelada" for b in self.bookings):
            return False
        pkg.is_active = False
        pkg.deleted_at = datetime.datetime.now().isoformat()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_PAQUETE", "Paquetes",
                         f"Desactivado paquete ID: {pkg_id}")
        return True

    # ------------------------------------------------------------------
    # Usuarios (RF-01)
    # ------------------------------------------------------------------
    def create_user(self, current_user, **data) -> UserSession | dict:
        from werkzeug.security import generate_password_hash
        email = (data.get("email") or "").strip().lower()
        if not email or any(u.email.lower() == email for u in self.available_users):
            return {"success": False, "message": "El email ya está registrado."}
        password = data.pop("password", "")
        if len(password) < 8:
            return {"success": False, "message": "La contraseña debe tener al menos 8 caracteres."}
        data.pop("email", None)
        user = UserSession(id=new_id("usr"), email=email,
                           password_hash=generate_password_hash(password),
                           role=data.pop("role", "client"), **data)
        self.available_users.append(user)
        self.log_action(current_user.id, current_user.name, "CREAR_USUARIO", "Usuarios",
                         f"Usuario {email} creado con rol {user.role}.")
        return user

    def update_user(self, current_user, user_id: str, **changes) -> UserSession | dict | None:
        user = self.get_user(user_id)
        if not user:
            return None
        allowed = {"name", "email", "role", "department", "avatar", "is_active", "client_id"}
        if user.role == "admin" and changes.get("role") and changes["role"] != "admin":
            admins = [u for u in self.available_users if u.role == "admin" and getattr(u, "is_active", True)]
            if len(admins) <= 1:
                return {"success": False, "message": "No se puede degradar al último administrador."}
        before = user.to_dict()
        for key, value in changes.items():
            if key in allowed:
                setattr(user, key, value)
        self.log_action(current_user.id, current_user.name, "EDITAR_USUARIO", "Usuarios",
                         f"Antes: {before}, Después: {user.to_dict()}")
        return user

    def reset_user_password(self, current_user, user_id: str, new_password: str) -> dict:
        from werkzeug.security import generate_password_hash
        user = self.get_user(user_id)
        if not user:
            return {"success": False, "message": "Usuario no encontrado."}
        if len(new_password or "") < 8:
            return {"success": False, "message": "La contraseña debe tener al menos 8 caracteres."}
        user.password_hash = generate_password_hash(new_password)
        self.log_action(current_user.id, current_user.name, "RESET_PASSWORD", "Usuarios",
                         f"Contraseña restablecida para {user.email}.")
        return {"success": True, "message": "Contraseña restablecida."}

    def deactivate_user(self, current_user, user_id: str) -> dict:
        user = self.get_user(user_id)
        if not user:
            return {"success": False, "message": "Usuario no encontrado."}
        if user.role == "admin":
            admins = [u for u in self.available_users if u.role == "admin" and getattr(u, "is_active", True)]
            if len(admins) <= 1:
                return {"success": False, "message": "No se puede desactivar al último administrador."}
        user.is_active = False
        self.log_action(current_user.id, current_user.name, "DESACTIVAR_USUARIO", "Usuarios",
                         f"Usuario {user.email} desactivado.")
        return {"success": True, "message": "Usuario desactivado."}

    # ------------------------------------------------------------------
    # Inventario atómico (RN-01 extendida)
    # ------------------------------------------------------------------
    def _stops_overlap(self, start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
        """Dos rangos [a, b) se solapan si a < b_other and b > a_other."""
        if not start_a or not end_a or not start_b or not end_b:
            return False
        try:
            a1 = datetime.datetime.fromisoformat(str(start_a)[:10]).date()
            a2 = datetime.datetime.fromisoformat(str(end_a)[:10]).date()
            b1 = datetime.datetime.fromisoformat(str(start_b)[:10]).date()
            b2 = datetime.datetime.fromisoformat(str(end_b)[:10]).date()
        except (ValueError, TypeError):
            return False
        return a1 < b2 and b1 < a2

    def _hotel_overlapping_rooms(self, hotel_id: str, check_in: str, check_out: str) -> int:
        """Suma de rooms_count de reservas activas que se solapan con [check_in, check_out)."""
        total = 0
        for b in self.bookings:
            if getattr(b, "hotel_id", None) != hotel_id or b.status == "Cancelada":
                continue
            b_in = getattr(b, "check_in", None) or b.departure_date
            b_out = getattr(b, "check_out", None) or b.return_date
            if self._stops_overlap(check_in, check_out, b_in, b_out):
                total += int(getattr(b, "rooms_count", 1) or 1)
        return total

    def _hotel_has_rooms(self, hotel_id: str, check_in: str, check_out: str, rooms: int) -> bool:
        hotel = self.get_hotel(hotel_id)
        if hotel is None:
            return False
        rooms_total = getattr(hotel, "rooms_total", None)
        if rooms_total is None:
            # Derivar desde los tipos de habitación si rooms_total no existe.
            rt = getattr(hotel, "room_types", None) or []
            rooms_total = sum(int(r.get("available", r.get("rooms_total", 0)) or 0) for r in rt) \
                if rt else 0
        occupied = self._hotel_overlapping_rooms(hotel_id, check_in, check_out)
        return (rooms_total - occupied) >= rooms

    def _check_package_availability(self, package_id: str, travelers: int) -> bool:
        """Verifica disponibilidad de slots en un paquete."""
        pkg = self.get_package(package_id)
        if not pkg:
            return False
        return pkg.available_slots >= travelers

    def _release_package_slots(self, package_id: str, travelers: int) -> None:
        """Libera slots en un paquete de forma idempotente."""
        pkg = self.get_package(package_id)
        if not pkg:
            return
        max_slots = getattr(pkg, "total_slots", None) or getattr(pkg, "max_capacity", None) or (
            pkg.available_slots + travelers
        )
        pkg.available_slots = min(max_slots, pkg.available_slots + travelers)

    # ------------------------------------------------------------------
    # Reservas — RN-01, RN-02, RN-03, RN-01 extendida
    # ------------------------------------------------------------------
    def create_booking(self, current_user, *, client_id, client_name, client_email,
                       package_id=None, package_name="", destination_name="",
                       departure_date="", return_date="", travelers=1, passengers=None,
                       hotel_id=None, hotel_name=None, flight_id=None, flight_number=None,
                       transport_id=None, check_in=None, check_out=None, rooms_count=1,
                       total_price=0.0, notes="", initial_payment=0.0,
                       payment_method="Tarjeta de Crédito", promo_code=""):

        # --- RN-02: toda reserva debe estar asociada a un cliente válido ---
        if not client_id or not client_name:
            return {"success": False,
                    "message": "Regla de Negocio (RN-02): Toda reserva debe estar asociada a un cliente registrado válido."}

        # --- RN-01: no se puede reservar sin disponibilidad (todo atómico) ---
        pkg = self.get_package(package_id) if package_id else None
        if pkg is not None and pkg.available_slots < travelers:
            return {"success": False,
                    "message": (f'Regla de Negocio (RN-01): No hay disponibilidad suficiente. El paquete '
                                f'"{pkg.title}" solo cuenta con {pkg.available_slots} cupos '
                                f'disponibles para {travelers} viajeros solicitados.')}

        if flight_id:
            flight = self.get_flight(flight_id)
            if flight is None or flight.seats_available < travelers:
                return {"success": False,
                        "message": "Regla de Negocio (RN-01): El vuelo no tiene asientos suficientes."}

        transport = None
        if transport_id:
            transport = next((t for t in self.transports if t.id == transport_id), None)
            if transport is None or transport.available_seats < travelers:
                return {"success": False,
                        "message": "Regla de Negocio (RN-01): El transporte no tiene asientos suficientes."}

        if hotel_id:
            if not self._hotel_has_rooms(hotel_id, check_in or departure_date,
                                         check_out or return_date, rooms_count):
                return {"success": False,
                        "message": ("Regla de Negocio (RN-01): El hotel no tiene habitaciones "
                                    "disponibles para esas fechas.")}

        booking_year = datetime.date.today().year
        sequence = 1 + sum(1 for b in self.bookings
                           if str(getattr(b, "booking_code", "")).startswith(f"DDN-{booking_year}-"))
        booking_code = f"DDN-{booking_year}-{sequence:05d}"
        booking_id = new_id("bkg")

        booking = Booking(
            id=booking_id, booking_code=booking_code, client_id=client_id, client_name=client_name,
            client_email=client_email, package_id=package_id, package_name=package_name,
            destination_name=destination_name, departure_date=departure_date, return_date=return_date,
            travelers=travelers, passengers=passengers or [], hotel_id=hotel_id, hotel_name=hotel_name,
            flight_id=flight_id, flight_number=flight_number, total_price=total_price,
            amount_paid=0, payment_status="Pendiente", status="Pendiente",
            created_at=_today(), notes=notes, transport_id=transport_id,
            check_in=check_in or departure_date, check_out=check_out or return_date,
            rooms_count=rooms_count,
        )

        # Hold atómico de inventario: si algo falla después, se revierte todo.
        try:
            if pkg is not None:
                pkg.available_slots -= travelers
            if flight_id:
                self.get_flight(flight_id).seats_available -= travelers
            if transport is not None:
                transport.available_seats -= travelers
        except Exception:  # rollback del hold parcial
            if pkg is not None:
                pkg.available_slots += travelers
            if flight_id and self.get_flight(flight_id) is not None:
                self.get_flight(flight_id).seats_available += travelers
            if transport is not None:
                transport.available_seats += travelers
            return {"success": False,
                    "message": "Regla de Negocio (RN-01): No se pudo reservar el inventario."}

        client = self.get_client(client_id)
        if client:
            client.register_trip(total_price)

        self.bookings.insert(0, booking)

        # Registrar pago inicial si hay (Tarjeta/PayPal nacen Completado;
        # Transferencia/Efectivo nacen Pendiente_verificacion).
        if initial_payment > 0:
            pay_status = "Completado" if payment_method in ("Tarjeta de Crédito", "PayPal") \
                else "Pendiente_verificacion"
            payment = PaymentTransaction(
                id=new_id("pay"),
                receipt_number=f"REC-{booking_year}-{random.randint(1000, 9999)}",
                booking_id=booking_id, booking_code=booking_code, client_name=client_name,
                amount=initial_payment, payment_method=payment_method,
                transaction_ref=f"TX_{random.randint(100000, 999999)}", status=pay_status,
                date=_now_str(), invoice_number=f"FAC-DDN-{random.randint(10000, 99999)}",
            )
            self.payments.insert(0, payment)
            if pay_status == "Completado":
                booking.amount_paid += initial_payment
                booking.payment_status = "Pagado" if booking.amount_paid >= total_price else "Parcial"
                if booking.amount_paid >= total_price and total_price > 0:
                    transition = BookingService.transition(self, booking, "Confirmada")
                    if not transition["success"]:
                        booking.payment_status = "Parcial"
            else:
                booking.payment_status = "Pendiente_verificacion"

        # RN-03 documentado: la confirmación siempre pasa por BookingService.transition.

        # Promociones (RF-12): registrar redención y validar vigencia/categoría.
        if promo_code:
            promo = next((p for p in self.promotions
                          if p.code.upper() == promo_code.strip().upper()), None)
            if promo and promo.active and promo.current_uses < promo.max_uses:
                valid_until = getattr(promo, "valid_until", "") or ""
                if valid_until and valid_until < _today():
                    return {"success": False, "message": "El cupón está vencido."}
                cats = getattr(promo, "applicable_categories", None) or []
                client_cat = getattr(client, "category", "") if client else ""
                if cats and "Todos" not in cats and client_cat not in cats:
                    return {"success": False, "message": "El cupón no aplica a la categoría del cliente."}
                promo.current_uses += 1
                self.promotion_redemptions.append({
                    "promotion_id": promo.id, "booking_id": booking_id,
                    "code": promo.code, "date": _today(),
                })

        self.log_action(current_user.id, current_user.name, "NUEVA_RESERVA", "Reservas",
                         f"Reserva {booking_code} creada para {client_name} ({destination_name}) "
                         f"por un total de ${total_price} USD.")
        self.add_notification("Nueva Reserva Confirmada",
                               f"Reserva {booking_code} generada para {client_name}. Total: ${total_price} USD.",
                               "success", "bookings")

        return {"success": True, "message": f"¡Reserva {booking_code} registrada con éxito!", "booking": booking}

    def update_booking(self, current_user, booking_id: str, **changes) -> dict:
        """Actualiza una reserva: fechas, viajeros, notas; recalcula total y revalida inventario."""
        booking = self.get_booking(booking_id)
        if not booking:
            return {"success": False, "message": "Reserva no encontrada."}

        # Lista blanca de campos editables por esta vía (RN-04/IDOR: no sobrescribir id ni ids ajenos).
        allowed = {"departure_date", "return_date", "travelers", "notes",
                   "hotel_id", "check_in", "check_out", "rooms_count",
                   "flight_id", "transport_id", "package_id"}
        changes = {k: v for k, v in changes.items() if k in allowed}

        # Validación de fechas: salida >= hoy y return > departure
        departure_date = changes.get("departure_date", booking.departure_date)
        return_date = changes.get("return_date", booking.return_date)

        try:
            from datetime import date as _date
            today = _date.today()
            if departure_date:
                dt_dep = datetime.datetime.fromisoformat(str(departure_date)[:10]).date()
                if dt_dep < today:
                    return {"success": False,
                            "message": "La fecha de salida no puede ser anterior a hoy."}
            if departure_date and return_date and str(return_date)[:10] <= str(departure_date)[:10]:
                return {"success": False,
                        "message": "La fecha de regreso debe ser posterior a la de salida."}
        except (ValueError, TypeError):
            return {"success": False, "message": "Formato de fecha inválido."}

        travelers = changes.get("travelers", booking.travelers)
        try:
            travelers = int(travelers)
        except (TypeError, ValueError):
            return {"success": False, "message": "El número de viajeros debe ser un entero."}
        if travelers < 1:
            return {"success": False, "message": "Debe haber al menos un viajero."}

        # Liberar el hold actual para revalidar con los nuevos valores.
        old_pkg_id = booking.package_id
        old_travelers = booking.travelers
        old_flight_id = getattr(booking, "flight_id", None)
        old_transport_id = getattr(booking, "transport_id", None)

        pkg = self.get_package(old_pkg_id) if old_pkg_id else None
        if pkg:
            pkg.available_slots = min(getattr(pkg, "total_slots", pkg.available_slots + old_travelers) or pkg.available_slots,
                                      pkg.available_slots + old_travelers)
        if old_flight_id and self.get_flight(old_flight_id):
            self.get_flight(old_flight_id).seats_available += old_travelers
        if old_transport_id:
            t = next((t for t in self.transports if t.id == old_transport_id), None)
            if t:
                t.available_seats += old_travelers

        new_pkg_id = changes.get("package_id", booking.package_id)
        new_pkg = self.get_package(new_pkg_id) if new_pkg_id else None
        new_flight_id = changes.get("flight_id", getattr(booking, "flight_id", None))
        new_flight = self.get_flight(new_flight_id) if new_flight_id else None
        new_transport_id = changes.get("transport_id", getattr(booking, "transport_id", None))
        new_transport = next((t for t in self.transports if t.id == new_transport_id), None) if new_transport_id else None
        new_hotel_id = changes.get("hotel_id", getattr(booking, "hotel_id", None))
        new_check_in = changes.get("check_in", getattr(booking, "check_in", None) or departure_date)
        new_check_out = changes.get("check_out", getattr(booking, "check_out", None) or return_date)
        new_rooms = changes.get("rooms_count", getattr(booking, "rooms_count", 1) or 1)

        # RN-01 extendida: revalidar inventario con los nuevos valores.
        if new_pkg and new_pkg.available_slots < travelers:
            self._restore_hold(booking, old_pkg_id, old_travelers, old_flight_id, old_transport_id)
            return {"success": False,
                    "message": f"No hay disponibilidad en el paquete '{new_pkg.title}'."}
        if new_flight and new_flight.seats_available < travelers:
            self._restore_hold(booking, old_pkg_id, old_travelers, old_flight_id, old_transport_id)
            return {"success": False, "message": "El vuelo no tiene asientos suficientes."}
        if new_transport and new_transport.available_seats < travelers:
            self._restore_hold(booking, old_pkg_id, old_travelers, old_flight_id, old_transport_id)
            return {"success": False, "message": "El transporte no tiene asientos suficientes."}
        if new_hotel_id:
            # Excluir la propia reserva del cálculo de solapamiento (ya liberamos su hold).
            occupied = sum(int(getattr(b, "rooms_count", 1) or 1) for b in self.bookings
                           if getattr(b, "hotel_id", None) == new_hotel_id and b.status != "Cancelada"
                           and b.id != booking.id
                           and self._stops_overlap(new_check_in or "", new_check_out or "",
                                                   getattr(b, "check_in", None) or b.departure_date,
                                                   getattr(b, "check_out", None) or b.return_date))
            hotel = self.get_hotel(new_hotel_id)
            rooms_total = getattr(hotel, "rooms_total", None) if hotel else None
            if rooms_total is None and hotel is not None:
                rt = getattr(hotel, "room_types", None) or []
                rooms_total = sum(int(r.get("available", r.get("rooms_total", 0)) or 0) for r in rt) if rt else 0
            if hotel and rooms_total is not None and (rooms_total - occupied) < new_rooms:
                self._restore_hold(booking, old_pkg_id, old_travelers, old_flight_id, old_transport_id)
                return {"success": False,
                        "message": "El hotel no tiene habitaciones disponibles para esas fechas."}

        # Todo válido: aplicar el nuevo hold.
        if new_pkg:
            new_pkg.available_slots -= travelers
        if new_flight:
            new_flight.seats_available -= travelers
        if new_transport:
            new_transport.available_seats -= travelers

        old_status, old_payment_status, old_total_price = booking.status, booking.payment_status, booking.total_price
        for key, value in changes.items():
            setattr(booking, key, value)
        booking.travelers = travelers

        # Recalcular total: paquete + vuelo + hotel (price_per_night × noches × habitaciones).
        pkg_total = (new_pkg.price_usd * travelers) if new_pkg else 0
        flight_total = (new_flight.price_usd * travelers) if new_flight else 0
        total_hotel = 0
        new_hotel = self.get_hotel(new_hotel_id) if new_hotel_id else None
        if new_hotel:
            rt = getattr(new_hotel, "room_types", None) or []
            price_per_night = rt[0].get("price_per_night", 0) if rt else 0
            try:
                nights = max(1, (datetime.datetime.fromisoformat(str(new_check_out)[:10]).date()
                                 - datetime.datetime.fromisoformat(str(new_check_in)[:10]).date()).days)
            except (ValueError, TypeError):
                nights = 1
            total_hotel = price_per_night * nights * int(new_rooms or 1)
        booking.total_price = pkg_total + flight_total + total_hotel

        # Reajustar payment_status / estado vía BookingService (nunca por asignación directa).
        if booking.amount_paid >= booking.total_price and booking.total_price > 0:
            booking.payment_status = "Pagado"
            BookingService.transition(self, booking, "Confirmada")
        elif booking.amount_paid > 0:
            booking.payment_status = "Parcial"
            if old_status == "Confirmada":
                BookingService.transition(self, booking, "Pendiente")

        self.log_action(current_user.id, current_user.name, "ACTUALIZAR_RESERVA", "Reservas",
                         f"Reserva ID: {booking.id} actualizada. Total anterior: ${old_total_price}, "
                         f"Total nuevo: ${booking.total_price}. Estado: {old_status} -> {booking.status}")

        self.persist()
        return {"success": True, "message": "Reserva actualizada correctamente.", "booking": booking}

    def _restore_hold(self, booking, old_pkg_id, old_travelers, old_flight_id, old_transport_id):
        """Devuelve el hold previo tras un intento fallido de actualización."""
        pkg = self.get_package(old_pkg_id) if old_pkg_id else None
        if pkg:
            pkg.available_slots -= old_travelers
        if old_flight_id and self.get_flight(old_flight_id):
            self.get_flight(old_flight_id).seats_available -= old_travelers
        if old_transport_id:
            t = next((t for t in self.transports if t.id == old_transport_id), None)
            if t:
                t.available_seats -= old_travelers

    def cancel_booking(self, current_user, booking_id: str, reason: str = "") -> bool:
        """Cancela una reserva idempotente (si ya está cancelada no vuelve a liberar cupos)."""
        booking = self.get_booking(booking_id)
        if not booking:
            return False

        # Idempotente: si ya está cancelada, no hacer nada
        if booking.status == "Cancelada":
            self.log_action(current_user.id, current_user.name, "CANCELAR_RESERVA", "Reservas",
                             f"Reserva {booking.booking_code} ya estaba cancelada. Sin liberar cupos.")
            return True

        # Liberar TODO el hold de inventario de forma idempotente (RN-01).
        pkg = self.get_package(booking.package_id) if getattr(booking, "package_id", None) else None
        if pkg:
            self._release_package_slots(booking.package_id, booking.travelers)
        if getattr(booking, "flight_id", None):
            flight = self.get_flight(booking.flight_id)
            if flight:
                flight.seats_available = min(getattr(flight, "total_seats", flight.seats_available + booking.travelers) or flight.seats_available,
                                            flight.seats_available + booking.travelers)
        if getattr(booking, "transport_id", None):
            t = next((t for t in self.transports if t.id == booking.transport_id), None)
            if t:
                t.available_seats += booking.travelers

        booking.status = "Cancelada"
        booking.notes = f"{getattr(booking, 'notes', '') or ''} [Cancelada: {reason or 'Por solicitud'}]"
        self.log_action(current_user.id, current_user.name, "CANCELAR_RESERVA", "Reservas",
                         f"Reserva {booking.booking_code} cancelada. Motivo: {reason or 'N/A'}")
        self.add_notification("Reserva Cancelada",
                               f"La reserva {booking.booking_code} fue cancelada. Se han restaurado los cupos.",
                               "warning", "bookings")
        return True

    # ------------------------------------------------------------------
    # RN-03: BookingService.transition - ÚNICO camino para cambiar estado
    # ------------------------------------------------------------------
    def update_booking_status(self, current_user, booking_id: str, nuevo_estado: str) -> dict:
        """Cambia el estado de una reserva pasando por BookingService.transition."""
        booking = self.get_booking(booking_id)
        if not booking:
            return {"success": False, "message": "Reserva no encontrada."}

        result = BookingService.transition(self, booking, nuevo_estado)
        if not result["success"]:
            return result

        self.log_action(current_user.id, current_user.name, "ACTUALIZAR_ESTADO_RESERVA", "Reservas",
                         f"Reserva ID: {booking.id} actualizada a estado: {nuevo_estado}")

        self.persist()
        return {"success": True, "message": f"Reserva actualizada a estado: {nuevo_estado}", "booking": booking}

    # ------------------------------------------------------------------
    # Pagos & facturación (RF-11, RN-03)
    # ------------------------------------------------------------------
    def register_payment(self, current_user, booking_id: str, amount: float, method: str, ref_number: str = ""):
        booking = self.get_booking(booking_id)
        if not booking:
            return {"success": False, "message": "Reserva no encontrada."}
        if amount <= 0:
            return {"success": False, "message": "El monto del pago debe ser mayor a 0."}

        # RN-03: no se paga una reserva cancelada
        if booking.status == "Cancelada":
            return {"success": False, "message": "No se puede registrar pago a una reserva cancelada."}

        # Verificar que el monto no exceda el saldo pendiente
        pending = booking.total_price - sum(
            p.amount for p in self.payments
            if p.booking_id == booking.id and p.status == "Completado")
        if amount > pending:
            return {"success": False, "message": f"El monto excede el saldo pendiente (${pending:.2f})."}  # 422

        # "Pago verificado": Tarjeta/PayPal nacen Completado; el resto Pendiente_verificacion.
        pay_status = "Completado" if method in ("Tarjeta de Crédito", "PayPal") \
            else "Pendiente_verificacion"
        receipt_number = f"REC-{datetime.date.today().year}-{random.randint(1000, 9999)}"
        invoice_number = f"FAC-DDN-{random.randint(10000, 99999)}"

        payment = PaymentTransaction(
            id=new_id("pay"),
            receipt_number=receipt_number, booking_id=booking.id,
            booking_code=booking.booking_code, client_name=booking.client_name, amount=amount,
            payment_method=method, transaction_ref=ref_number or f"TX_{random.randint(100000, 999999)}",
            status=pay_status, date=_now_str(), invoice_number=invoice_number,
        )
        self.payments.insert(0, payment)

        if pay_status == "Completado":
            booking.amount_paid += amount
            booking.payment_status = "Pagado" if booking.amount_paid >= booking.total_price else "Parcial"
            # RN-03: toda confirmación pasa por BookingService.transition.
            if booking.amount_paid >= booking.total_price and booking.total_price > 0:
                BookingService.transition(self, booking, "Confirmada")
        else:
            booking.payment_status = "Pendiente_verificacion" if booking.amount_paid == 0 else booking.payment_status

        # Registro de documento voucher solo si queda pagado totalmente
        if booking.is_fully_paid():
            voucher = TravelDocument(
                id=new_id("doc"), client_id=booking.client_id, client_name=booking.client_name,
                doc_type="Voucher de Reserva", file_name=f"Voucher_Oficial_{booking.booking_code}.pdf",
                file_size="1.4 MB", upload_date=_today(), status="Válido",
            )
            self.documents.insert(0, voucher)

        # RN-05: auditoría
        self.log_action(current_user.id, current_user.name, "PAGO_REGISTRADO", "Pagos & Facturación",
                         f"Registrado pago de ${amount} USD para reserva {booking.booking_code} "
                         f"mediante {method}. Factura: {invoice_number}")
        self.add_notification("Pago Recibido", f"Se registró pago de ${amount} USD para la reserva {booking.booking_code}.",
                               "success", "payments")

        return {"success": True, "message": f"Pago de ${amount} USD registrado exitosamente. Recibo: {receipt_number}",
                "payment": payment}

    # ------------------------------------------------------------------
    # Promociones (RF-12)
    # ------------------------------------------------------------------
    def add_promotion(self, current_user, **data) -> Promotion:
        promo = Promotion(id=short_code("prm"), current_uses=0, **data)
        self.promotions.insert(0, promo)
        self.log_action(current_user.id, current_user.name, "CREAR_PROMOCION", "Promociones",
                         f"Creado cupón {promo.code} con {promo.discount_percentage}% de descuento.")
        return promo

    def toggle_promotion_status(self, promo_id: str) -> None:
        for p in self.promotions:
            if p.id == promo_id:
                p.active = not p.active

    def apply_promo_code(self, code: str, total_price: float, client_category: str = "") -> dict:
        clean_code = (code or "").strip().upper()
        promo = next((p for p in self.promotions if p.code.upper() == clean_code and p.active), None)
        if not promo:
            return {"valid": False, "discount_percentage": 0, "final_price": total_price,
                     "message": "Código de promoción no válido o expirado."}
        if promo.current_uses >= promo.max_uses:
            return {"valid": False, "discount_percentage": 0, "final_price": total_price,
                     "message": "Este código ha alcanzado el límite máximo de usos."}
        valid_until = getattr(promo, "valid_until", "") or ""
        if valid_until and str(valid_until)[:10] < _today():
            return {"valid": False, "discount_percentage": 0, "final_price": total_price,
                     "message": "Este código está vencido."}

        # Validar applicable_categories contra la categoría del cliente
        if promo.applicable_categories and "Todos" not in promo.applicable_categories:
            client_cats = promo.applicable_categories
            if client_category not in client_cats:
                return {"valid": False, "discount_percentage": 0, "final_price": total_price,
                         "message": f"Este cupón no es applicable para la categoría '{client_category}'."}

        final_price, discount = promo.apply_to(total_price)
        # Nota: current_uses lo suma create_booking al registrar la redención
        # (este método también sirve para vistas previas y no debe contar).

        return {"valid": True, "discount_percentage": promo.discount_percentage, "final_price": final_price,
                 "message": f"¡Cupón {promo.code} aplicado! {promo.discount_percentage}% de descuento "
                            f"(-${discount:.2f} USD)."}

    # ------------------------------------------------------------------
    # Documentos (RF-17)
    # ------------------------------------------------------------------
    def add_document(self, current_user, **data) -> TravelDocument:
        doc = TravelDocument(id=new_id("doc"), upload_date=_today(), **data)
        self.documents.insert(0, doc)
        self.log_action(current_user.id, current_user.name, "SUBIR_DOCUMENTO", "Documentos",
                         f"Cargado documento {doc.file_name} ({getattr(doc, 'doc_type', '')}) para {doc.client_name}")
        return doc

    def delete_document(self, current_user, doc_id: str) -> bool:
        if current_user.role not in ("admin", "employee"):
            return False
        document = next((d for d in self.documents if d.id == doc_id), None)
        if not document:
            return False
        self.documents = [d for d in self.documents if d.id != doc_id]
        self.log_action(current_user.id, current_user.name, "ELIMINAR_DOCUMENTO", "Documentos",
                         f"Documento ID: {doc_id} eliminado.")
        return True


# Aplica persistencia automática a todas las operaciones que mutan datos.
for _method_name in _AUTOSAVE_METHODS:
    if hasattr(DataStore, _method_name):
        setattr(DataStore, _method_name, _apply_autosave(getattr(DataStore, _method_name)))

# ------------------------------------------------------------------
# BookingService: única vía para transiciones de estado de reserva (RN-03)
# ------------------------------------------------------------------
class BookingService:
    """Servicio centralizado para cambiar el estado de las reservas.

    Esta es la ÚNICA entrada para modificar booking.status (RN-03).
    Todas las rutas deben pasar por aquí: create_booking, update_booking_status,
    apply_payment. Esto garantiza que ningún código bypass las validaciones
    de depósito y pago.

    Regla "Confirmada":
      - ≥1 pago Completado
      - Suma de pagos Completados >= MIN_DEPOSIT_PCT × total_price
    """

    @staticmethod
    def transition(store, booking, nuevo_estado: str) -> dict:
        """Intenta transitar una reserva al nuevo estado.

        Returns dict con "success" y posible "message" de error.
        Si la transición es inválida, returns {"success": False, "message": ...}.
        """
        from .validators import validate_price  # evitar import circular en algunos casos

        # Guardar estado anterior para auditoría
        old_status = booking.status
        old_payment_status = booking.payment_status
        old_total = booking.total_price

        # --- Lógica de transición "Confirmada" ---
        if nuevo_estado == "Confirmada":
            # 1. Debe haber ≥1 pago Completado
            completed_payments = [p for p in store.payments
                                  if p.booking_id == booking.id and p.status == "Completado"]
            if not completed_payments:
                return {"success": False,
                        "message": "No se puede confirmar la reserva: debe haber al menos un pago Completado."}

            # 2. Suma de pagos Completados >= MIN_DEPOSIT_PCT × total
            total_completed = sum(p.amount for p in completed_payments)
            deposit_threshold = (MIN_DEPOSIT_PCT / 100) * booking.total_price
            if total_completed < deposit_threshold:
                return {"success": False,
                        "message": (f"El monto total de pagos Completados (${total_completed:.2f}) "
                                    f"es menor al depósito mínimo requerido ("
                                    f"{MIN_DEPOSIT_PCT}% de ${booking.total_price:.2f} = "
                                    f"${deposit_threshold:.2f}).")}

            booking.status = "Confirmada"
            booking.payment_status = "Pagado"

        # --- Lógica de transición "Pendiente" ---
        elif nuevo_estado == "Pendiente":
            booking.status = "Pendiente"
            # payment_status se mantiene o vuelve a Pendiente si no hay pago
            if booking.payment_status != "Pagado":
                booking.payment_status = "Pendiente"

        # --- Lógica de transición "Parcial" ---
        elif nuevo_estado == "Parcial":
            booking.status = "Pendiente"
            booking.payment_status = "Parcial"

        # --- Lógica de transición "Cancelada" ---
        elif nuevo_estado == "Cancelada":
            if booking.status == "Cancelada":
                # Idempotente: ya cancelada no vuelve a liberar cupos.
                return {"success": True, "message": "La reserva ya estaba cancelada."}
            system = UserSession(id="system", name="Sistema", role="admin", email="")
            # cancel_booking libera el inventario completo y deja la auditoría.
            store.cancel_booking(system, booking.id, "Transición por estado")
            booking.payment_status = "Anulado"

        else:
            # Estado desconocido - mantener actual
            return {"success": False, "message": f"Estado '{nuevo_estado}' no válido."}

        # Consistencia: si quedó totalmente pagada y NO está cancelada, queda Confirmada.
        if nuevo_estado != "Cancelada" and booking.is_fully_paid() and booking.status != "Confirmada":
            booking.status = "Confirmada"

        return {"success": True, "message": f"Transición '{old_status}' -> '{booking.status}' realizada con éxito."}


# Instancia única compartida por toda la aplicación (equivalente al Provider de React)
store = DataStore()