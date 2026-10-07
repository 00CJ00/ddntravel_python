"""
``DataStore``: fachada de datos de DDN Travel sobre SQLAlchemy (fase P2).

Conserva los nombres y las firmas que usaban las rutas antes del cambio a base
de datos (``create_booking``, ``register_payment``, ``add_client``…) y expone las
colecciones como propiedades. Toda la lógica de acceso vive en
``app/repositories``; aquí se orquesta y se registra la auditoría (RN-05).

Ya no hay estado en memoria ni archivo JSON: cada propiedad consulta la base de
datos y cada mutación se confirma contra la sesión de SQLAlchemy.
"""
from __future__ import annotations

import datetime

from sqlalchemy import desc

from . import audit
from . import models as m
from . import seed as seed_module
from .extensions import db
from .repositories import bookings as bookings_repo
from .repositories import catalog, people
from .repositories import documents as documents_repo
from .repositories import notifications as notifications_repo
from .repositories import payments as payments_repo
from .repositories import promotions as promotions_repo
from .repositories import settings as settings_repo
from .repositories.base import coerce_id, to_decimal

PAYMENT_METHODS = ["Tarjeta de Crédito", "Transferencia Bancaria", "Efectivo", "Cripto", "PayPal"]

MIN_DEPOSIT_PCT = 100  # Porcentaje mínimo de pagos verificados para confirmar

# Notificaciones de módulos internos: solo las ven admin y empleados.
INTERNAL_NOTIFICATION_TABS = {
    "clients", "bookings", "payments", "promotions", "documents",
    "hotels", "flights", "transports", "activities", "audit", "dashboard",
}


def _now_str() -> str:
    return datetime.datetime.now().strftime("%d/%m/%Y, %H:%M")


def _today() -> str:
    return datetime.date.today().isoformat()


def _as_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.datetime.fromisoformat(str(value)[:10]).date()
    except (ValueError, TypeError):
        raise ValueError(f"Fecha inválida: {value!r}")


def _dates_overlap(a_in, a_out, b_in, b_out) -> bool:
    """Rangos [a_in, a_out) y [b_in, b_out) se solapan."""
    a_in, a_out, b_in, b_out = _as_date(a_in), _as_date(a_out), _as_date(b_in), _as_date(b_out)
    if None in (a_in, a_out, b_in, b_out):
        return False
    return a_in < b_out and b_in < a_out


class DataStore:
    """Fachada única de acceso a datos (singleton a nivel de módulo)."""

    # ------------------------------------------------------------------
    # Colecciones (consulta directa a la BD; sin estado en memoria)
    # ------------------------------------------------------------------
    @property
    def available_users(self):
        return people.list_users()

    @property
    def clients(self):
        return people.list_clients()

    @property
    def destinations(self):
        return catalog.list_destinations()

    @property
    def packages(self):
        return catalog.list_packages()

    @property
    def hotels(self):
        return catalog.list_hotels()

    @property
    def flights(self):
        return catalog.list_flights()

    @property
    def transports(self):
        return catalog.list_transports()

    @property
    def activities(self):
        return catalog.list_activities()

    @property
    def bookings(self):
        return bookings_repo.list_bookings()

    @property
    def payments(self):
        return payments_repo.list_payments()

    @property
    def promotions(self):
        return promotions_repo.list_promotions()

    @property
    def documents(self):
        return documents_repo.list_documents()

    @property
    def notifications(self):
        return notifications_repo.list_notifications()

    @property
    def audit_logs(self):
        return (m.AuditLog.query
                .order_by(desc(m.AuditLog.timestamp), desc(m.AuditLog.id)).all())

    @property
    def predictive_data(self):
        return settings_repo.get_predictive_data()

    @predictive_data.setter
    def predictive_data(self, value):
        settings_repo.set_predictive_data(value)
        self._commit()

    def record_prediction(self, current_user, timeframe, result) -> None:
        """Guarda el resultado predictivo y su auditoría en una transacción."""
        settings_repo.set_predictive_data(result)
        audit.record("EJECUCIÓN_PREDICCIÓN_IA", "Motor IA Predictivo", user=current_user,
                     entity_type="Setting", entity_id=settings_repo.PREDICTIVE_KEY,
                     details=f"Análisis de comportamiento de compra generado para periodo: {timeframe}")
        self._notify("Estadísticas Predictivas Actualizadas",
                     "El motor de Inteligencia Artificial completó la predicción de demanda "
                     "y propensión de compra.", "success", "ai-predictive")
        self._commit()

    def _commit(self) -> None:
        """Único punto de confirmación de la aplicación.

        Todas las mutaciones de dominio pasan por aquí (``app/repositories``
        solo hace ``flush``); así una mutación y su auditoría se confirman o se
        revierten juntas. La sesión es una por petición (Flask-SQLAlchemy la
        cierra en el ``teardown`` del contexto de aplicación).
        """
        db.session.commit()

    # ------------------------------------------------------------------
    # Respaldo y reinicio de datos de demostración
    # ------------------------------------------------------------------
    def reset_all_data(self, log: bool = True) -> None:
        """Vacía la BD y recarga ``app/seed_data.json`` (fase P2)."""
        seed_module.seed_database(reset=True)
        if log:
            self.log_action("system", "Sistema", "RESET_DATOS", "Sistema",
                            "Datos de demostración restablecidos correctamente.")

    # ------------------------------------------------------------------
    # Utilidades de búsqueda
    # ------------------------------------------------------------------
    def get_user(self, user_id):
        return people.get_user(user_id)

    def get_client(self, client_id):
        return people.get_client(client_id)

    def get_package(self, package_id):
        return catalog.get_package(package_id)

    def get_booking(self, booking_id):
        return bookings_repo.get_booking(booking_id)

    def get_hotel(self, hotel_id):
        return catalog.get_hotel(hotel_id)

    def get_flight(self, flight_id):
        return catalog.get_flight(flight_id)

    def get_payment(self, payment_id):
        return payments_repo.get_payment(payment_id)

    # ------------------------------------------------------------------
    # Auditoría y notificaciones (RN-05)
    # ------------------------------------------------------------------
    def record_event(self, action, module, user=None, *, user_id=None,
                     user_name=None, details=None) -> None:
        """Registra un evento de auditoría sin mutación de dominio y lo confirma."""
        audit.record(action, module, user=user, user_id=user_id,
                     user_name=user_name, details=details)
        self._commit()

    def log_action(self, user_id, user_name, action, module, details) -> None:
        """Compatibilidad con llamadas previas: delega en ``record_event``."""
        self.record_event(action, module, user_id=user_id, user_name=user_name,
                          details=details)

    def _notify(self, title, message, ntype="info", link_tab=None,
                roles=None, visible_roles=None) -> None:
        """Encola una notificación en la transacción actual (no confirma)."""
        if visible_roles is not None:
            roles = visible_roles
        if roles is None:
            roles = ["admin", "employee"] if link_tab in INTERNAL_NOTIFICATION_TABS else None
        notifications_repo.create_notification(
            title, message, ntype=ntype, link_tab=link_tab, visible_roles=roles)

    def add_notification(self, title, message, ntype="info", link_tab=None,
                         roles=None, visible_roles=None) -> None:
        self._notify(title, message, ntype, link_tab, roles, visible_roles)
        self._commit()

    def mark_notification_as_read(self, notif_id) -> None:
        notification = notifications_repo.get_notification(notif_id)
        if notification is not None:
            notifications_repo.mark_read(notification)
            self._commit()

    def mark_all_notifications_as_read(self) -> None:
        notifications_repo.mark_all_read()
        self._commit()

    # ------------------------------------------------------------------
    # Clientes (RF-03)
    # ------------------------------------------------------------------
    def add_client(self, current_user, **data) -> m.Client:
        data.setdefault("registration_date", _today())
        data.setdefault("trips_count", 0)
        data.setdefault("total_spent", 0)
        client = people.create_client(data)
        audit.record("CREAR_CLIENTE", "Clientes", client, user=current_user,
                     details=f"Registrado nuevo cliente: {client.name} ({client.category})")
        self._notify("Nuevo Cliente Registrado",
                     f"{client.name} fue añadido a la base de datos.", "info", "clients")
        self._commit()
        return client

    def update_client(self, current_user, client_id, **changes) -> None:
        client = people.get_client(client_id)
        if client:
            before = audit.snapshot(client)
            people.update_client(client, changes)
            audit.record("MODIFICAR_CLIENTE", "Clientes", client, before=before,
                         user=current_user,
                         details=f"Actualizada información del cliente ID: {client.id}")
            self._commit()

    def delete_client(self, current_user, client_id) -> bool:
        client = people.get_client(client_id)
        if client is None:
            return False
        before = audit.snapshot(client)
        db.session.delete(client)
        audit.record("ELIMINAR_CLIENTE", "Clientes", entity_type="Client",
                     entity_id=client_id, before=before, user=current_user,
                     details=f"Eliminado cliente ID: {client_id}")
        self._commit()
        return True

    # ------------------------------------------------------------------
    # Catálogo (destinos, hoteles, vuelos, transportes, actividades, paquetes)
    # ------------------------------------------------------------------
    def add_destination(self, current_user, **data) -> m.Destination:
        dest = catalog.create_destination(data)
        audit.record("CREAR_DESTINO", "Destinos", dest, user=current_user,
                     details=f"Registrado nuevo destino: {dest.name}")
        self._commit()
        return dest

    def edit_destination(self, current_user, dest_id, **data):
        dest = catalog.get_destination(dest_id)
        if not dest:
            return None
        before = audit.snapshot(dest)
        catalog.update_destination(dest, data)
        audit.record("EDITAR_DESTINO", "Destinos", dest, before=before, user=current_user,
                     details=f"Actualizado destino ID: {dest_id} - {dest.name}")
        self._commit()
        return dest

    def edit_package(self, current_user, pkg_id, **data):
        pkg = catalog.get_package(pkg_id)
        if pkg is None:
            return None
        before = audit.snapshot(pkg)
        for k, v in data.items():
            if k in {"title", "destination_id", "destination_name", "duration_days", "duration_nights",
                     "price_usd", "original_price_usd", "available_slots", "total_slots", "max_capacity",
                     "image", "image_url", "gallery", "category", "featured", "inclusions", "departure_dates"}:
                try:
                    if k in {"duration_days", "duration_nights", "available_slots", "total_slots", "max_capacity"}:
                        v = int(float(v))
                    elif k in {"price_usd", "original_price_usd"}:
                        v = float(v)
                except (TypeError, ValueError):
                    continue
                setattr(pkg, k, v)
        audit.record("EDITAR_PAQUETE", "Paquetes", pkg, before=before, user=current_user,
                     details=f"Actualizado paquete ID: {pkg_id}")
        self._commit()
        return pkg

    def edit_hotel(self, current_user, hotel_id, **data):
        hotel = catalog.get_hotel(hotel_id)
        if hotel is None:
            return None
        before = audit.snapshot(hotel)
        room_types = data.pop("room_types", None)
        for k, v in data.items():
            if k in {"name", "destination_id", "destination_name", "stars", "address",
                     "rating", "image", "contact_phone", "amenities"}:
                setattr(hotel, k, v)
        if room_types is not None:
            hotel.room_types.clear()
            for rt in room_types:
                hotel.room_types.append(m.RoomType(
                    name=rt.get("type") or rt.get("name") or "Habitación",
                    price_per_night=rt.get("price_per_night") or 0,
                    rooms_total=int(rt.get("available") or rt.get("rooms_total") or 0)))
        audit.record("EDITAR_HOTEL", "Hoteles", hotel, before=before, user=current_user,
                     details=f"Actualizado hotel ID: {hotel_id}")
        self._commit()
        return hotel

    def edit_flight(self, current_user, flight_id, **data):
        flight = self.get_flight(flight_id)
        if flight is None:
            return None
        before = audit.snapshot(flight)
        for k, v in data.items():
            if k in {"airline", "flight_number", "origin", "destination", "departure_time", "arrival_time",
                     "price_usd", "seats_available", "total_seats", "flight_class", "status",
                     "baggage_allowance", "image"}:
                try:
                    if k in {"seats_available", "total_seats"}:
                        v = int(float(v))
                    elif k == "price_usd":
                        v = float(v)
                except (TypeError, ValueError):
                    continue
                setattr(flight, k, v)
        audit.record("EDITAR_VUELO", "Vuelos", flight, before=before, user=current_user,
                     details=f"Actualizado vuelo ID: {flight_id}")
        self._commit()
        return flight

    def edit_transport(self, current_user, transport_id, **data):
        transport = next((t for t in self.transports if t.id == coerce_id(transport_id)), None)
        if transport is None:
            return None
        before = audit.snapshot(transport)
        for k, v in data.items():
            if k in {"type", "route", "vehicle_model", "capacity", "available_seats", "driver_name",
                     "price_usd", "status", "amenities", "image"}:
                try:
                    if k in {"capacity", "available_seats"}:
                        v = int(float(v))
                    elif k == "price_usd":
                        v = float(v)
                except (TypeError, ValueError):
                    continue
                setattr(transport, k, v)
        audit.record("EDITAR_TRANSPORTE", "Transporte", transport, before=before, user=current_user,
                     details=f"Actualizado transporte ID: {transport_id}")
        self._commit()
        return transport

    def edit_activity(self, current_user, activity_id, **data):
        activity = catalog.get_activity(activity_id)
        if activity is None:
            return None
        before = audit.snapshot(activity)
        for k, v in data.items():
            if k in {"title", "destination_id", "destination_name", "duration_hours", "price_usd",
                     "includes_guide", "difficulty", "image", "description", "category", "schedule"}:
                try:
                    if k == "duration_hours":
                        v = int(float(v))
                    elif k == "price_usd":
                        v = float(v)
                    elif k == "includes_guide":
                        v = str(v).lower() in ("1", "true", "sí", "si", "on")
                except (TypeError, ValueError):
                    continue
                setattr(activity, k, v)
        audit.record("EDITAR_ACTIVIDAD", "Actividades", activity, before=before, user=current_user,
                     details=f"Actualizada actividad ID: {activity_id}")
        self._commit()
        return activity

    def has_active_bookings_for(self, field, ident) -> bool:
        return any(
            getattr(b, field) == coerce_id(ident) and b.status != "Cancelada"
            for b in self.bookings
        )

    def delete_package(self, current_user, pkg_id) -> str:
        pkg = catalog.get_package(pkg_id)
        if pkg is None:
            return "not_found"
        if self.has_active_bookings_for("package_id", pkg_id):
            return "has_active_bookings"
        before = audit.snapshot(pkg)
        db.session.delete(pkg)
        audit.record("ELIMINAR_PAQUETE", "Paquetes", entity_type="Package",
                     entity_id=pkg_id, before=before, user=current_user,
                     details=f"Eliminado paquete ID: {pkg_id}")
        self._commit()
        return "ok"

    def delete_hotel_guarded(self, current_user, hotel_id) -> str:
        if self.has_active_bookings_for("hotel_id", hotel_id):
            return "has_active_bookings"
        return "ok" if self.delete_hotel(current_user, hotel_id) else "not_found"

    def delete_flight_guarded(self, current_user, flight_id) -> str:
        if self.has_active_bookings_for("flight_id", flight_id):
            return "has_active_bookings"
        return "ok" if self.delete_flight(current_user, flight_id) else "not_found"

    def delete_transport_guarded(self, current_user, transport_id) -> str:
        if self.has_active_bookings_for("transport_id", transport_id):
            return "has_active_bookings"
        return "ok" if self.delete_transport(current_user, transport_id) else "not_found"

    def add_hotel(self, current_user, **data) -> m.Hotel:
        room_types = data.pop("room_types", None)
        hotel = catalog.create_hotel(data, room_types=room_types)
        audit.record("CREAR_HOTEL", "Hoteles", hotel, user=current_user,
                     details=f"Registrado nuevo hotel: {hotel.name}")
        self._commit()
        return hotel

    def delete_hotel(self, current_user, hotel_id) -> bool:
        hotel = catalog.get_hotel(hotel_id)
        if hotel is None:
            return False
        before = audit.snapshot(hotel)
        db.session.delete(hotel)
        audit.record("ELIMINAR_HOTEL", "Hoteles", entity_type="Hotel",
                     entity_id=hotel_id, before=before, user=current_user,
                     details=f"Eliminado hotel ID: {hotel_id}")
        self._commit()
        return True

    def add_flight(self, current_user, **data) -> m.Flight:
        flight = catalog.create_flight(data)
        audit.record("CREAR_VUELO", "Vuelos", flight, user=current_user,
                     details=f"Registrado nuevo vuelo: {flight.airline} {flight.flight_number}")
        self._commit()
        return flight

    def delete_flight(self, current_user, flight_id) -> bool:
        flight = catalog.get_flight(flight_id)
        if flight is None:
            return False
        before = audit.snapshot(flight)
        db.session.delete(flight)
        audit.record("ELIMINAR_VUELO", "Vuelos", entity_type="Flight",
                     entity_id=flight_id, before=before, user=current_user,
                     details=f"Eliminado vuelo ID: {flight_id}")
        self._commit()
        return True

    def add_transport(self, current_user, **data) -> m.Transport:
        transport = catalog.create_transport(data)
        audit.record("CREAR_TRANSPORTE", "Transporte", transport, user=current_user,
                     details=f"Registrada unidad de transporte: {transport.vehicle_model}")
        self._commit()
        return transport

    def delete_transport(self, current_user, transport_id) -> bool:
        transport = catalog.get_transport(transport_id)
        if transport is None:
            return False
        before = audit.snapshot(transport)
        db.session.delete(transport)
        audit.record("ELIMINAR_TRANSPORTE", "Transporte", entity_type="Transport",
                     entity_id=transport_id, before=before, user=current_user,
                     details=f"Eliminada unidad de transporte ID: {transport_id}")
        self._commit()
        return True

    def add_activity(self, current_user, **data) -> m.Activity:
        activity = catalog.create_activity(data)
        audit.record("CREAR_ACTIVIDAD", "Actividades", activity, user=current_user,
                     details=f"Registrada actividad turística: {activity.title}")
        self._commit()
        return activity

    def delete_activity(self, current_user, activity_id) -> bool:
        if current_user.role != "admin":
            return False
        activity = catalog.get_activity(activity_id)
        if activity is None:
            return False
        before = audit.snapshot(activity)
        db.session.delete(activity)
        audit.record("ELIMINAR_ACTIVIDAD", "Actividades", entity_type="Activity",
                     entity_id=activity_id, before=before, user=current_user,
                     details=f"Eliminada actividad ID: {activity_id}")
        self._commit()
        return True

    def add_package(self, current_user, **data) -> m.Package:
        package = catalog.create_package(data)
        audit.record("CREAR_PAQUETE", "Paquetes", package, user=current_user,
                     details=f"Registrado nuevo paquete: {package.title}")
        self._commit()
        return package

    # ------------------------------------------------------------------
    # Reservas — RN-01 (disponibilidad), RN-02 (cliente), RN-03 (pago)
    # ------------------------------------------------------------------
    def create_booking(self, current_user, *, client_id, client_name, client_email,
                       package_id=None, package_name="", destination_name="",
                       departure_date="", return_date="", travelers=1, passengers=None,
                       hotel_id=None, hotel_name=None, flight_id=None, flight_number=None,
                       transport_id=None, check_in=None, check_out=None, rooms_count=1,
                       total_price=0.0, notes="", initial_payment=0.0,
                       payment_method="Tarjeta de Crédito", promo_code=""):
        if not client_id or not client_name:
            return {"success": False,
                    "message": "Regla de Negocio (RN-02): Toda reserva debe estar asociada a un cliente registrado válido."}

        selected_pkg = self.get_package(package_id) if package_id else None
        if selected_pkg and selected_pkg.available_slots < travelers:
            return {"success": False,
                    "message": (f'Regla de Negocio (RN-01): No hay disponibilidad suficiente. El paquete '
                                f'"{selected_pkg.title}" solo cuenta con {selected_pkg.available_slots} cupos '
                                f'disponibles para {travelers} viajeros solicitados.')}

        # RN-01 extendida: vuelo y transporte deben tener asientos suficientes.
        flight = self.get_flight(flight_id) if flight_id else None
        if flight_id and (flight is None or (flight.seats_available or 0) < travelers):
            return {"success": False,
                    "message": "Regla de Negocio (RN-01): El vuelo no tiene asientos suficientes."}
        transport = None
        if transport_id:
            transport = next((t for t in self.transports if t.id == coerce_id(transport_id)), None)
            if transport is None or (transport.available_seats or 0) < travelers:
                return {"success": False,
                        "message": "Regla de Negocio (RN-01): El transporte no tiene asientos suficientes."}
        if hotel_id and not self._hotel_has_rooms(hotel_id,
                                                 _as_date(check_in or departure_date),
                                                 _as_date(check_out or return_date),
                                                 int(rooms_count or 1)):
            return {"success": False,
                    "message": "Regla de Negocio (RN-01): El hotel no tiene habitaciones para esas fechas."}

        # Promociones (RF-12): validar cupón antes de crear la reserva.
        promo = None
        if promo_code:
            _client = people.get_client(client_id)
            promo = self._find_valid_promo(promo_code, getattr(_client, "category", None))
            if promo is None:
                return {"success": False, "message": "Cupón inválido, vencido o no aplicable."}

        initial_payment = to_decimal(initial_payment)
        total_price = to_decimal(total_price)
        status = "Pendiente"
        payment_status = "Pendiente"

        # RN-01: descuento atómico de cupos (ningún otro cobro al confirmar).
        if selected_pkg:
            if not catalog.reserve_slots_atomic(selected_pkg.id, travelers):
                self._rollback()
                return {"success": False,
                        "message": (f'Regla de Negocio (RN-01): No hay disponibilidad suficiente. El paquete '
                                    f'"{selected_pkg.title}" ya no cuenta con cupos para {travelers} viajeros.')}
        if flight is not None:
            flight.seats_available = (flight.seats_available or 0) - travelers
        if transport is not None:
            transport.available_seats = (transport.available_seats or 0) - travelers

        try:
            booking = bookings_repo.create_booking_record(
                client_id=client_id, package_id=package_id or None, package_name=package_name,
                destination_name=destination_name, hotel_id=hotel_id or None, hotel_name=hotel_name,
                flight_id=flight_id or None, flight_number=flight_number,
                departure_date=departure_date, return_date=return_date, travelers=travelers,
                total_price=total_price, amount_paid=0, status=status,
                payment_status=payment_status, notes=notes, created_by=coerce_id(current_user.id),
                transport_id=transport_id or None, check_in=_as_date(check_in or departure_date),
                check_out=_as_date(check_out or return_date), rooms_count=int(rooms_count or 1),
            )
            bookings_repo.add_passengers(booking, passengers)

            client = people.get_client(client_id)
            if client is not None:
                people.register_trip(client, total_price)

            if initial_payment > 0:
                pay_status = "Completado" if payment_method in ("Tarjeta de Crédito", "PayPal") \
                    else "Pendiente_verificacion"
                payment = payments_repo.create_payment(
                    booking.id, initial_payment, payment_method, status=pay_status)
                if pay_status == "Completado":
                    booking.amount_paid = to_decimal(booking.amount_paid) + initial_payment
                    if total_price > 0 and booking.amount_paid >= total_price:
                        BookingService.transition(self, booking, "Confirmada")
                    else:
                        booking.payment_status = "Parcial"
                else:
                    booking.payment_status = "Pendiente_verificacion"

            if promo is not None:
                promo.current_uses = (promo.current_uses or 0) + 1
                db.session.add(m.PromotionRedemption(
                    promotion_id=promo.id, booking_id=booking.id))
        except Exception:
            self._rollback()
            if selected_pkg:
                catalog.release_slots(selected_pkg.id, travelers)
            if flight is not None:
                flight.seats_available = (flight.seats_available or 0) + travelers
            if transport is not None:
                transport.available_seats = (transport.available_seats or 0) + travelers
            raise

        audit.record("NUEVA_RESERVA", "Reservas", booking, user=current_user,
                     details=f"Reserva {booking.booking_code} creada para {client_name} "
                             f"({destination_name}) por un total de ${booking.total_price} USD.")
        self._notify("Nueva Reserva Confirmada",
                     f"Reserva {booking.booking_code} generada para {client_name}. "
                     f"Total: ${booking.total_price} USD.", "success", "bookings")
        self._commit()
        return {"success": True, "message": f"¡Reserva {booking.booking_code} registrada con éxito!",
                "booking": booking}

    def cancel_booking(self, current_user, booking_id, reason="") -> bool:
        booking = self.get_booking(booking_id)
        if not booking:
            return False
        if booking.status == "Cancelada":
            return True  # idempotente: no vuelve a liberar cupos
        before = audit.snapshot(booking)
        if booking.package_id:
            catalog.release_slots(booking.package_id, booking.travelers)
        if booking.flight_id:
            flight = self.get_flight(booking.flight_id)
            if flight is not None:
                flight.seats_available = (flight.seats_available or 0) + (booking.travelers or 0)
        if booking.transport_id:
            transport = next((t for t in self.transports if t.id == booking.transport_id), None)
            if transport is not None:
                transport.available_seats = (transport.available_seats or 0) + (booking.travelers or 0)
        bookings_repo.cancel(booking, reason)
        audit.record("CANCELAR_RESERVA", "Reservas", booking, before=before, user=current_user,
                     details=f"Reserva {booking.booking_code} cancelada. Motivo: {reason or 'N/A'}")
        self._notify("Reserva Cancelada",
                     f"La reserva {booking.booking_code} fue cancelada. Se han restaurado los cupos.",
                     "warning", "bookings")
        self._commit()
        return True

    # ------------------------------------------------------------------
    # Pagos & facturación (RF-11, RN-03)
    # ------------------------------------------------------------------
    def register_payment(self, current_user, booking_id, amount, method, ref_number=""):
        booking = self.get_booking(booking_id)
        if not booking:
            return {"success": False, "message": "Reserva no encontrada."}
        amount = to_decimal(amount)
        if amount <= 0:
            return {"success": False, "message": "El monto del pago debe ser mayor a 0."}

        booking_before = audit.snapshot(booking)
        # "Pago verificado": Tarjeta/PayPal nacen Completado; el resto Pendiente_verificacion.
        pay_status = "Completado" if method in ("Tarjeta de Crédito", "PayPal") \
            else "Pendiente_verificacion"
        if pay_status == "Completado":
            bookings_repo.apply_payment(booking, amount)
        payment = payments_repo.create_payment(booking.id, amount, method,
                                               reference=ref_number, status=pay_status)
        if pay_status == "Completado" and booking.is_fully_paid() and booking.status != "Cancelada":
            BookingService.transition(self, booking, "Confirmada")
        elif pay_status != "Completado" and booking.amount_paid == 0:
            booking.payment_status = "Pendiente_verificacion"

        if pay_status == "Completado" and booking.is_fully_paid():
            documents_repo.create_document({
                "client_id": booking.client_id, "doc_type": "Voucher de Reserva",
                "file_name": f"Voucher_Oficial_{booking.booking_code}.pdf", "status": "Válido",
                "upload_date": _today(),
            })

        audit.record("PAGO_REGISTRADO", "Pagos & Facturación", payment, user=current_user,
                     details=f"Registrado pago de ${amount} USD para reserva {booking.booking_code} "
                             f"mediante {method}. Factura: {payment.invoice_number}")
        audit.record("ACTUALIZAR_PAGO_RESERVA", "Reservas", booking, before=booking_before,
                     user=current_user,
                     details=f"Saldo de la reserva {booking.booking_code} actualizado a "
                             f"${booking.amount_paid} USD ({booking.payment_status}).")
        self._notify("Pago Recibido",
                     f"Se registró pago de ${amount} USD para la reserva {booking.booking_code}.",
                     "success", "payments")
        self._commit()
        return {"success": True,
                "message": f"Pago de ${amount} USD registrado exitosamente. Recibo: {payment.receipt_number}",
                "payment": payment}

    def verify_payment(self, current_user, payment_id) -> dict:
        """Verifica un pago Pendiente_verificacion (lo deja Completado y retransita la reserva)."""
        payment = payments_repo.get_payment(coerce_id(payment_id))
        if payment is None:
            return {"success": False, "message": "Pago no encontrado."}
        if payment.status == "Completado":
            return {"success": True, "message": "El pago ya estaba verificado.", "payment": payment}
        if payment.status == "Anulado":
            return {"success": False, "message": "No se puede verificar un pago anulado."}
        before = audit.snapshot(payment)
        payment.status = "Completado"
        booking = self.get_booking(payment.booking_id)
        if booking is not None and booking.status != "Cancelada":
            bookings_repo.apply_payment(booking, payment.amount)
            if booking.is_fully_paid():
                BookingService.transition(self, booking, "Confirmada")
        audit.record("VERIFICAR_PAGO", "Pagos & Facturación", payment, before=before,
                     user=current_user,
                     details=f"Pago {payment.receipt_number} verificado (${payment.amount} USD).")
        self._commit()
        return {"success": True, "message": "Pago verificado correctamente.", "payment": payment}

    def update_booking_status(self, current_user, booking_id, status) -> dict:
        """Cambia el estado de una reserva pasando por BookingService.transition (RN-03)."""
        booking = self.get_booking(booking_id)
        if not booking:
            return {"success": False, "message": "Reserva no encontrada."}
        result = BookingService.transition(self, booking, status)
        if result["success"]:
            audit.record("ACTUALIZAR_ESTADO_RESERVA", "Reservas", booking, user=current_user,
                         details=f"Reserva ID: {booking_id} actualizada a estado: {status}")
            self._commit()
        return result

    # ------------------------------------------------------------------
    # Promociones (RF-12)
    # ------------------------------------------------------------------
    def add_promotion(self, current_user, **data) -> m.Promotion:
        promo = promotions_repo.create_promotion(data)
        audit.record("CREAR_PROMOCION", "Promociones", promo, user=current_user,
                     details=f"Creado cupón {promo.code} con {promo.discount_percentage}% de descuento.")
        self._commit()
        return promo

    def toggle_promotion_status(self, current_user, promo_id) -> None:
        promo = promotions_repo.get_promotion(promo_id)
        if promo is not None:
            before = audit.snapshot(promo)
            promotions_repo.toggle(promo)
            audit.record("CAMBIAR_ESTADO_PROMOCION", "Promociones", promo, before=before,
                         user=current_user,
                         details=f"Cupón {promo.code} {'activado' if promo.active else 'desactivado'}.")
            self._commit()

    def apply_promo_code(self, code, total_price) -> dict:
        total_price = to_decimal(total_price)
        promo = promotions_repo.find_active_by_code(code)
        if not promo:
            return {"valid": False, "discount_percentage": 0, "final_price": float(total_price),
                    "message": "Código de promoción no válido o expirado."}
        if (promo.current_uses or 0) >= (promo.max_uses or 0):
            return {"valid": False, "discount_percentage": 0, "final_price": float(total_price),
                    "message": "Este código ha alcanzado el límite máximo de usos."}
        final_price, discount = promo.apply_to(total_price)
        return {"valid": True, "discount_percentage": promo.discount_percentage,
                "final_price": float(final_price),
                "message": f"¡Cupón {promo.code} aplicado! {promo.discount_percentage}% de descuento "
                           f"(-${float(discount):.2f} USD)."}

    # ------------------------------------------------------------------
    # Documentos (RF-17)
    # ------------------------------------------------------------------
    def add_document(self, current_user, **data) -> m.TravelDocument:
        doc = documents_repo.create_document(data)
        audit.record("SUBIR_DOCUMENTO", "Documentos", doc, user=current_user,
                     details=f"Cargado documento {doc.file_name} ({doc.doc_type}) "
                             f"para cliente {doc.client_id}")
        self._commit()
        return doc

    def delete_document(self, current_user, doc_id) -> bool:
        if current_user.role not in ("admin", "employee"):
            return False
        doc = documents_repo.get_document(doc_id)
        if doc is None:
            return False
        before = audit.snapshot(doc)
        documents_repo.delete_document(doc)
        audit.record("ELIMINAR_DOCUMENTO", "Documentos", entity_type="TravelDocument",
                     entity_id=doc_id, before=before, user=current_user,
                     details=f"Documento ID: {doc_id} eliminado.")
        self._commit()
        return True

    # ------------------------------------------------------------------
    # Usuarios / sesión de Google
    # ------------------------------------------------------------------
    def add_user(self, user: m.User) -> m.User:
        db.session.add(user)
        self._commit()
        return user

    def find_or_create_google_user(self, email, name, avatar="") -> m.User:
        """Reutiliza o crea el usuario cliente de Google y su ficha de cliente."""
        user = people.get_user_by_email(email)
        if user is None:
            user = people.create_user({
                "name": f"{name} (Cliente Viajero)", "email": email, "role": "client",
                "department": "Cliente Registrado", "avatar": avatar or "", "google_id": email,
            })
        elif avatar:
            user.avatar = avatar
        client = people.get_client_by_email(email)
        if client is None:
            client = people.create_client({
                "name": name, "email": email, "phone": "+1 (000) 000-0000",
                "document_id": f"GGL-{email}", "category": "Estándar", "status": "Activo",
                "trips_count": 0, "total_spent": 0, "registration_date": _today(),
                "preferred_destinations": [],
            })
        if not user.client_id:
            user.client_id = client.id
        self._commit()
        return user

    # ------------------------------------------------------------------
    # RN-01 extendida: utilidades de disponibilidad
    # ------------------------------------------------------------------
    def _hotel_overlapping_rooms(self, hotel_id, check_in, check_out) -> int:
        total = 0
        for b in self.bookings:
            if b.hotel_id != coerce_id(hotel_id) or b.status == "Cancelada":
                continue
            b_in = b.check_in or b.departure_date
            b_out = b.check_out or b.return_date
            if _dates_overlap(check_in, check_out, b_in, b_out):
                total += int(b.rooms_count or 1)
        return total

    def _hotel_has_rooms(self, hotel_id, check_in, check_out, rooms: int) -> bool:
        hotel = self.get_hotel(hotel_id)
        if hotel is None:
            return False
        if check_in is None or check_out is None:
            return True  # sin fechas concretas no se puede validar solapamiento
        rooms_total = sum(int(rt.rooms_total or 0) for rt in (hotel.room_types or []))
        occupied = self._hotel_overlapping_rooms(hotel.id, check_in, check_out)
        return (rooms_total - occupied) >= rooms

    def _find_valid_promo(self, code, client_category):
        code = (code or "").strip().upper()
        if not code:
            return None
        promo = next((p for p in self.promotions if (p.code or "").upper() == code), None)
        if promo is None or not promo.active:
            return None
        if promo.max_uses and (promo.current_uses or 0) >= promo.max_uses:
            return None
        if promo.valid_until:
            valid_until = promo.valid_until.date() if hasattr(promo.valid_until, "date") else promo.valid_until
            if str(valid_until)[:10] < _today():
                return None
        cats = promo.applicable_categories or []
        if cats and "Todos" not in cats and client_category and client_category not in cats:
            return None
        return promo

    # ------------------------------------------------------------------
    # Reservas: edición (RN-01 revalidado) y transiciones RN-03
    # ------------------------------------------------------------------
    def update_booking(self, current_user, booking_id, **changes) -> dict:
        booking = self.get_booking(booking_id)
        if not booking:
            return {"success": False, "message": "Reserva no encontrada."}

        allowed = {"departure_date", "return_date", "travelers", "notes",
                   "check_in", "check_out", "rooms_count"}
        changes = {k: v for k, v in changes.items() if k in allowed}

        departure = changes.get("departure_date", booking.departure_date)
        ret = changes.get("return_date", booking.return_date)
        try:
            dep_d = _as_date(departure)
            ret_d = _as_date(ret)
        except (ValueError, TypeError):
            return {"success": False, "message": "Formato de fecha inválido."}
        if dep_d is not None and dep_d < datetime.date.today():
            return {"success": False, "message": "La fecha de salida no puede ser anterior a hoy."}
        if dep_d is not None and ret_d is not None and ret_d <= dep_d:
            return {"success": False, "message": "La fecha de regreso debe ser posterior a la de salida."}

        try:
            travelers = int(changes.get("travelers", booking.travelers) or 1)
        except (TypeError, ValueError):
            return {"success": False, "message": "Número de viajeros inválido."}
        if travelers < 1:
            return {"success": False, "message": "Debe haber al menos un viajero."}

        before = audit.snapshot(booking)

        # Validar solapamiento de hotel con el nuevo número de habitaciones si cambia.
        if booking.hotel_id and ("check_in" in changes or "check_out" in changes or "rooms_count" in changes):
            hotel = self.get_hotel(booking.hotel_id)
            if hotel is not None:
                new_in = _as_date(changes.get("check_in", booking.check_in))
                new_out = _as_date(changes.get("check_out", booking.check_out))
                occupied = sum(
                    int(b.rooms_count or 1) for b in self.bookings
                    if b.hotel_id == hotel.id and b.status != "Cancelada" and b.id != booking.id
                    and _dates_overlap(new_in, new_out, b.check_in or b.departure_date, b.check_out or b.return_date)
                )
                rooms_total = sum(int(rt.rooms_total or 0) for rt in (hotel.room_types or []))
                if (rooms_total - occupied) < int(changes.get("rooms_count", booking.rooms_count or 1) or 1):
                    return {"success": False,
                            "message": "Regla de Negocio (RN-01): El hotel no tiene habitaciones para esas fechas."}

        for key, value in changes.items():
            if key in ("check_in", "check_out", "departure_date", "return_date"):
                value = _as_date(value)
            setattr(booking, key, value)
        booking.travelers = travelers

        # Recalcular total con hotel: price_per_night × noches × habitaciones.
        total = 0
        if booking.package_id:
            pkg = self.get_package(booking.package_id)
            if pkg is not None:
                total += to_decimal(pkg.price_usd) * travelers
        if booking.flight_id:
            flight = self.get_flight(booking.flight_id)
            if flight is not None:
                total += to_decimal(flight.price_usd) * travelers
        if booking.hotel_id:
            hotel = self.get_hotel(booking.hotel_id)
            if hotel is not None and hotel.room_types:
                price = to_decimal(hotel.room_types[0].price_per_night or 0)
                try:
                    nights = max(1, (_as_date(booking.check_out) - _as_date(booking.check_in)).days)
                except (ValueError, TypeError, AttributeError):
                    nights = 1
                total += price * nights * int(booking.rooms_count or 1)
        booking.total_price = total

        if booking.amount_paid >= booking.total_price > 0:
            BookingService.transition(self, booking, "Confirmada")
        elif booking.amount_paid > 0:
            booking.payment_status = "Parcial"
            if booking.status == "Confirmada":
                BookingService.transition(self, booking, "Pendiente")

        audit.record("ACTUALIZAR_RESERVA", "Reservas", booking, before=before, user=current_user,
                     details=f"Reserva {booking.booking_code} actualizada; total ${booking.total_price}.")
        self._commit()
        return {"success": True, "message": "Reserva actualizada correctamente.", "booking": booking}

    # ------------------------------------------------------------------
    # Usuarios (RF-01): solo admin
    # ------------------------------------------------------------------
    def create_user(self, current_user, *, name, email, password, role="client",
                    department="", client_id=None):
        from werkzeug.security import generate_password_hash
        email = (email or "").strip().lower()
        if not email or people.get_user_by_email(email):
            return {"success": False, "message": "El email ya está registrado."}
        if len(password or "") < 8:
            return {"success": False, "message": "La contraseña debe tener al menos 8 caracteres."}
        user = m.User(name=name, email=email, role=role, department=department,
                      is_active=True, client_id=client_id or None,
                      password_hash=generate_password_hash(password))
        db.session.add(user)
        audit.record("CREAR_USUARIO", "Usuarios", user, user=current_user,
                     details=f"Usuario {email} creado con rol {role}.")
        self._commit()
        return {"success": True, "message": "Usuario creado.", "user": user}

    def update_user(self, current_user, user_id, **changes) -> dict:
        user = people.get_user(coerce_id(user_id))
        if user is None:
            return {"success": False, "message": "Usuario no encontrado."}
        allowed = {"name", "email", "role", "department", "avatar", "is_active", "client_id"}
        if user.role == "admin" and changes.get("role") and changes["role"] != "admin":
            admins = [u for u in people.list_users() if u.role == "admin" and u.is_active]
            if len(admins) <= 1:
                return {"success": False, "message": "No se puede degradar al último administrador."}
        before = None
        try:
            before = audit.snapshot(user)
        except Exception:
            pass
        for key, value in changes.items():
            if key in allowed:
                setattr(user, key, value)
        audit.record("EDITAR_USUARIO", "Usuarios", user, before=before, user=current_user,
                     details=f"Usuario {user.email} actualizado.")
        self._commit()
        return {"success": True, "message": "Usuario actualizado.", "user": user}

    def reset_user_password(self, current_user, user_id, new_password) -> dict:
        from werkzeug.security import generate_password_hash
        user = people.get_user(coerce_id(user_id))
        if user is None:
            return {"success": False, "message": "Usuario no encontrado."}
        if len(new_password or "") < 8:
            return {"success": False, "message": "La contraseña debe tener al menos 8 caracteres."}
        user.password_hash = generate_password_hash(new_password)
        audit.record("RESET_PASSWORD", "Usuarios", user, user=current_user,
                     details=f"Contraseña restablecida para {user.email}.")
        self._commit()
        return {"success": True, "message": "Contraseña restablecida."}

    def deactivate_user(self, current_user, user_id) -> dict:
        user = people.get_user(coerce_id(user_id))
        if user is None:
            return {"success": False, "message": "Usuario no encontrado."}
        if user.role == "admin":
            admins = [u for u in people.list_users() if u.role == "admin" and u.is_active]
            if len(admins) <= 1:
                return {"success": False, "message": "No se puede desactivar al último administrador."}
        user.is_active = False
        audit.record("DESACTIVAR_USUARIO", "Usuarios", user, user=current_user,
                     details=f"Usuario {user.email} desactivado.")
        self._commit()
        return {"success": True, "message": "Usuario desactivado."}

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------
    def _rollback(self) -> None:
        """Único punto de reversión explícita de la aplicación.

        Descarta la transacción en curso (p. ej. cuando falla un ``UPDATE``
        condicional de inventario). Ante una excepción no controlada,
        Flask-SQLAlchemy cierra la sesión en el teardown y revierte igualmente.
        """
        db.session.rollback()


# ------------------------------------------------------------------
# BookingService: ÚNICO camino para cambiar booking.status (RN-03)
# ------------------------------------------------------------------
class BookingService:
    """Centraliza toda transición de estado de una reserva."""

    @staticmethod
    def transition(store: DataStore, booking, nuevo_estado: str) -> dict:
        old_status = booking.status

        if nuevo_estado == "Confirmada":
            completed = [p for p in store.payments
                         if p.booking_id == booking.id and p.status == "Completado"]
            if not completed:
                return {"success": False,
                        "message": "No se puede confirmar la reserva: debe haber al menos un pago Completado."}
            total_completed = sum(to_decimal(p.amount) for p in completed)
            threshold = to_decimal(MIN_DEPOSIT_PCT) / 100 * (to_decimal(booking.total_price) or 0)
            if total_completed < threshold:
                return {"success": False,
                        "message": (f"El monto total de pagos Completados (${total_completed:.2f}) es menor "
                                    f"al depósito mínimo requerido ({MIN_DEPOSIT_PCT}% de "
                                    f"${to_decimal(booking.total_price) or 0:.2f} = ${threshold:.2f}).")}
            booking.status = "Confirmada"
            booking.payment_status = "Pagado"

        elif nuevo_estado == "Pendiente":
            booking.status = "Pendiente"
            if booking.payment_status != "Pagado":
                booking.payment_status = "Pendiente"

        elif nuevo_estado == "Cancelada":
            if booking.status == "Cancelada":
                return {"success": True, "message": "La reserva ya estaba cancelada."}
            system = SystemUser()
            store.cancel_booking(system, booking.id, "Transición por estado")
            booking.payment_status = "Anulado"

        elif nuevo_estado in ("En Progreso", "Completada", "Parcial"):
            if nuevo_estado == "Parcial":
                booking.status = "Pendiente"
                booking.payment_status = "Parcial"
            else:
                booking.status = nuevo_estado

        else:
            return {"success": False, "message": f"Estado '{nuevo_estado}' no válido."}

        # Consistencia: totalmente pagada y no cancelada ⇒ Confirmada.
        if nuevo_estado != "Cancelada" and booking.is_fully_paid() and booking.status != "Confirmada":
            booking.status = "Confirmada"

        return {"success": True,
                "message": f"Transición '{old_status}' -> '{booking.status}' realizada con éxito."}


class SystemUser:
    """Usuario técnico para transiciones automáticas (sin sesión)."""
    id = None
    name = "Sistema"
    role = "system"
    email = ""


# Instancia única compartida por toda la aplicación (equivalente al Provider de React)
store = DataStore()
