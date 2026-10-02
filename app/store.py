"""
``DataStore``: fachada de datos de DDN Travel sobre SQLAlchemy (fase P2).

Conserva los nombres y las firmas que usaban las rutas antes del cambio a base
de datos (``create_booking``, ``register_payment``, ``add_client``…) y expone las
colecciones como propiedades. Toda la lógica de acceso vive en
``app/repositories``; aquí se orquesta y se registra la auditoría (RN-05).

Ya no hay estado en memoria ni ``state.json``: cada propiedad consulta la BD y
cada mutación se confirma contra la sesión de SQLAlchemy.
"""
from __future__ import annotations

import datetime

from sqlalchemy import desc

from .extensions import db
from . import audit
from . import models as m
from . import seed as seed_module
from .repositories import catalog, documents as documents_repo, notifications as notifications_repo
from .repositories import payments as payments_repo, people, promotions as promotions_repo
from .repositories import settings as settings_repo
from .repositories import bookings as bookings_repo
from .repositories.base import coerce_id, to_decimal, to_int

PAYMENT_METHODS = ["Tarjeta de Crédito", "Transferencia Bancaria", "Efectivo", "Cripto", "PayPal"]

# Notificaciones de módulos internos: solo las ven admin y empleados.
INTERNAL_NOTIFICATION_TABS = {
    "clients", "bookings", "payments", "promotions", "documents",
    "hotels", "flights", "transports", "activities", "audit", "dashboard",
}


def _now_str() -> str:
    return datetime.datetime.now().strftime("%d/%m/%Y, %H:%M")


def _today() -> str:
    return datetime.date.today().isoformat()


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
                       total_price=0.0, notes="", initial_payment=0.0,
                       payment_method="Tarjeta de Crédito"):
        if not client_id or not client_name:
            return {"success": False,
                    "message": "Regla de Negocio (RN-02): Toda reserva debe estar asociada a un cliente registrado válido."}

        selected_pkg = self.get_package(package_id) if package_id else None
        if selected_pkg and selected_pkg.available_slots < travelers:
            return {"success": False,
                    "message": (f'Regla de Negocio (RN-01): No hay disponibilidad suficiente. El paquete '
                                f'"{selected_pkg.title}" solo cuenta con {selected_pkg.available_slots} cupos '
                                f'disponibles para {travelers} viajeros solicitados.')}

        initial_payment = to_decimal(initial_payment)
        total_price = to_decimal(total_price)
        is_full_paid = initial_payment >= total_price and total_price > 0
        is_partial_paid = 0 < initial_payment < total_price
        payment_status = "Pagado" if is_full_paid else ("Parcial" if is_partial_paid else "Pendiente")
        status = "Confirmada" if is_full_paid else "Pendiente"

        # RN-01: descuento atómico de cupos (ningún otro cobro al confirmar).
        if selected_pkg:
            if not catalog.reserve_slots_atomic(selected_pkg.id, travelers):
                self._rollback()
                return {"success": False,
                        "message": (f'Regla de Negocio (RN-01): No hay disponibilidad suficiente. El paquete '
                                    f'"{selected_pkg.title}" ya no cuenta con cupos para {travelers} viajeros.')}

        booking = bookings_repo.create_booking_record(
            client_id=client_id, package_id=package_id or None, package_name=package_name,
            destination_name=destination_name, hotel_id=hotel_id or None, hotel_name=hotel_name,
            flight_id=flight_id or None, flight_number=flight_number,
            departure_date=departure_date, return_date=return_date, travelers=travelers,
            total_price=total_price, amount_paid=initial_payment, status=status,
            payment_status=payment_status, notes=notes, created_by=coerce_id(current_user.id),
        )
        bookings_repo.add_passengers(booking, passengers)

        client = people.get_client(client_id)
        people.register_trip(client, total_price)

        if initial_payment > 0:
            payments_repo.create_payment(
                booking.id, initial_payment, payment_method, status="Completado")

        audit.record("NUEVA_RESERVA", "Reservas", booking, user=current_user,
                     details=f"Reserva {booking.booking_code} creada para {client_name} "
                             f"({destination_name}) por un total de ${total_price} USD.")
        self._notify("Nueva Reserva Confirmada",
                     f"Reserva {booking.booking_code} generada para {client_name}. "
                     f"Total: ${total_price} USD.", "success", "bookings")
        self._commit()
        return {"success": True, "message": f"¡Reserva {booking.booking_code} registrada con éxito!",
                "booking": booking}

    def update_booking_status(self, current_user, booking_id, status) -> None:
        booking = self.get_booking(booking_id)
        if booking:
            before = audit.snapshot(booking)
            bookings_repo.set_status(booking, status)
            audit.record("ACTUALIZAR_ESTADO_RESERVA", "Reservas", booking, before=before,
                         user=current_user,
                         details=f"Reserva ID: {booking_id} actualizada a estado: {status}")
            self._commit()

    def cancel_booking(self, current_user, booking_id, reason="") -> bool:
        booking = self.get_booking(booking_id)
        if not booking:
            return False
        if booking.status == "Cancelada":
            return True  # idempotente: no vuelve a liberar cupos
        before = audit.snapshot(booking)
        if booking.package_id:
            catalog.release_slots(booking.package_id, booking.travelers)
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
        bookings_repo.apply_payment(booking, amount)
        payment = payments_repo.create_payment(booking.id, amount, method, reference=ref_number)

        if booking.is_fully_paid():
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
    # Interno
    # ------------------------------------------------------------------
    def _rollback(self) -> None:
        db.session.rollback()


# Instancia única compartida por toda la aplicación (equivalente al Provider de React)
store = DataStore()
