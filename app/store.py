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
import random

from sqlalchemy import desc

from .extensions import db
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
    def log_action(self, user_id, user_name, action, module, details) -> None:
        user = self.get_user(user_id)
        db.session.add(m.AuditLog(
            timestamp=datetime.datetime.utcnow(),
            user_id=coerce_id(user_id),
            user_name=user_name,
            user_role=user.role if user else "system",
            action=action,
            module=module,
            details=details,
            ip_address=f"190.166.42.{random.randint(10, 90)}",
        ))
        self._commit()

    def add_notification(self, title, message, ntype="info", link_tab=None,
                         roles=None, visible_roles=None) -> None:
        if visible_roles is not None:
            roles = visible_roles
        if roles is None:
            roles = ["admin", "employee"] if link_tab in INTERNAL_NOTIFICATION_TABS else None
        notifications_repo.create_notification(
            title, message, ntype=ntype, link_tab=link_tab, visible_roles=roles)
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
        self.log_action(current_user.id, current_user.name, "CREAR_CLIENTE", "Clientes",
                        f"Registrado nuevo cliente: {client.name} ({client.category})")
        self.add_notification("Nuevo Cliente Registrado",
                              f"{client.name} fue añadido a la base de datos.", "info", "clients")
        return client

    def update_client(self, current_user, client_id, **changes) -> None:
        client = people.get_client(client_id)
        if client:
            people.update_client(client, changes)
            self._commit()
            self.log_action(current_user.id, current_user.name, "MODIFICAR_CLIENTE", "Clientes",
                            f"Actualizada información del cliente ID: {client.id}")

    def delete_client(self, current_user, client_id) -> bool:
        client = people.get_client(client_id)
        if client is None:
            return False
        db.session.delete(client)
        self._commit()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_CLIENTE", "Clientes",
                        f"Eliminado cliente ID: {client_id}")
        return True

    # ------------------------------------------------------------------
    # Catálogo (destinos, hoteles, vuelos, transportes, actividades, paquetes)
    # ------------------------------------------------------------------
    def add_destination(self, current_user, **data) -> m.Destination:
        dest = catalog.create_destination(data)
        self._commit()
        self.log_action(current_user.id, current_user.name, "CREAR_DESTINO", "Destinos",
                        f"Registrado nuevo destino: {dest.name}")
        return dest

    def edit_destination(self, current_user, dest_id, **data):
        dest = catalog.get_destination(dest_id)
        if not dest:
            return None
        catalog.update_destination(dest, data)
        self._commit()
        self.log_action(current_user.id, current_user.name, "EDITAR_DESTINO", "Destinos",
                        f"Actualizado destino ID: {dest_id} - {dest.name}")
        return dest

    def add_hotel(self, current_user, **data) -> m.Hotel:
        room_types = data.pop("room_types", None)
        hotel = catalog.create_hotel(data, room_types=room_types)
        self._commit()
        self.log_action(current_user.id, current_user.name, "CREAR_HOTEL", "Hoteles",
                        f"Registrado nuevo hotel: {hotel.name}")
        return hotel

    def delete_hotel(self, current_user, hotel_id) -> bool:
        hotel = catalog.get_hotel(hotel_id)
        if hotel is None:
            return False
        db.session.delete(hotel)
        self._commit()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_HOTEL", "Hoteles",
                        f"Eliminado hotel ID: {hotel_id}")
        return True

    def add_flight(self, current_user, **data) -> m.Flight:
        flight = catalog.create_flight(data)
        self._commit()
        self.log_action(current_user.id, current_user.name, "CREAR_VUELO", "Vuelos",
                        f"Registrado nuevo vuelo: {flight.airline} {flight.flight_number}")
        return flight

    def delete_flight(self, current_user, flight_id) -> bool:
        flight = catalog.get_flight(flight_id)
        if flight is None:
            return False
        db.session.delete(flight)
        self._commit()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_VUELO", "Vuelos",
                        f"Eliminado vuelo ID: {flight_id}")
        return True

    def add_transport(self, current_user, **data) -> m.Transport:
        transport = catalog.create_transport(data)
        self._commit()
        self.log_action(current_user.id, current_user.name, "CREAR_TRANSPORTE", "Transporte",
                        f"Registrada unidad de transporte: {transport.vehicle_model}")
        return transport

    def delete_transport(self, current_user, transport_id) -> bool:
        transport = catalog.get_transport(transport_id)
        if transport is None:
            return False
        db.session.delete(transport)
        self._commit()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_TRANSPORTE", "Transporte",
                        f"Eliminada unidad de transporte ID: {transport_id}")
        return True

    def add_activity(self, current_user, **data) -> m.Activity:
        activity = catalog.create_activity(data)
        self._commit()
        self.log_action(current_user.id, current_user.name, "CREAR_ACTIVIDAD", "Actividades",
                        f"Registrada actividad turística: {activity.title}")
        return activity

    def delete_activity(self, current_user, activity_id) -> bool:
        if current_user.role != "admin":
            return False
        activity = catalog.get_activity(activity_id)
        if activity is None:
            return False
        db.session.delete(activity)
        self._commit()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_ACTIVIDAD", "Actividades",
                        f"Eliminada actividad ID: {activity_id}")
        return True

    def add_package(self, current_user, **data) -> m.Package:
        package = catalog.create_package(data)
        self._commit()
        self.log_action(current_user.id, current_user.name, "CREAR_PAQUETE", "Paquetes",
                        f"Registrado nuevo paquete: {package.title}")
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

        self._commit()
        self.log_action(current_user.id, current_user.name, "NUEVA_RESERVA", "Reservas",
                        f"Reserva {booking.booking_code} creada para {client_name} ({destination_name}) "
                        f"por un total de ${total_price} USD.")
        self.add_notification("Nueva Reserva Confirmada",
                              f"Reserva {booking.booking_code} generada para {client_name}. "
                              f"Total: ${total_price} USD.", "success", "bookings")
        return {"success": True, "message": f"¡Reserva {booking.booking_code} registrada con éxito!",
                "booking": booking}

    def update_booking_status(self, current_user, booking_id, status) -> None:
        booking = self.get_booking(booking_id)
        if booking:
            bookings_repo.set_status(booking, status)
            self._commit()
            self.log_action(current_user.id, current_user.name, "ACTUALIZAR_ESTADO_RESERVA", "Reservas",
                            f"Reserva ID: {booking_id} actualizada a estado: {status}")

    def cancel_booking(self, current_user, booking_id, reason="") -> bool:
        booking = self.get_booking(booking_id)
        if not booking:
            return False
        if booking.status == "Cancelada":
            return True  # idempotente: no vuelve a liberar cupos
        if booking.package_id:
            catalog.release_slots(booking.package_id, booking.travelers)
        bookings_repo.cancel(booking, reason)
        self._commit()
        self.log_action(current_user.id, current_user.name, "CANCELAR_RESERVA", "Reservas",
                        f"Reserva {booking.booking_code} cancelada. Motivo: {reason or 'N/A'}")
        self.add_notification("Reserva Cancelada",
                              f"La reserva {booking.booking_code} fue cancelada. Se han restaurado los cupos.",
                              "warning", "bookings")
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

        bookings_repo.apply_payment(booking, amount)
        payment = payments_repo.create_payment(booking.id, amount, method, reference=ref_number)

        if booking.is_fully_paid():
            documents_repo.create_document({
                "client_id": booking.client_id, "doc_type": "Voucher de Reserva",
                "file_name": f"Voucher_Oficial_{booking.booking_code}.pdf", "status": "Válido",
                "upload_date": _today(),
            })

        self._commit()
        self.log_action(current_user.id, current_user.name, "PAGO_REGISTRADO", "Pagos & Facturación",
                        f"Registrado pago de ${amount} USD para reserva {booking.booking_code} "
                        f"mediante {method}. Factura: {payment.invoice_number}")
        self.add_notification("Pago Recibido",
                              f"Se registró pago de ${amount} USD para la reserva {booking.booking_code}.",
                              "success", "payments")
        return {"success": True,
                "message": f"Pago de ${amount} USD registrado exitosamente. Recibo: {payment.receipt_number}",
                "payment": payment}

    # ------------------------------------------------------------------
    # Promociones (RF-12)
    # ------------------------------------------------------------------
    def add_promotion(self, current_user, **data) -> m.Promotion:
        promo = promotions_repo.create_promotion(data)
        self._commit()
        self.log_action(current_user.id, current_user.name, "CREAR_PROMOCION", "Promociones",
                        f"Creado cupón {promo.code} con {promo.discount_percentage}% de descuento.")
        return promo

    def toggle_promotion_status(self, promo_id) -> None:
        promo = promotions_repo.get_promotion(promo_id)
        if promo is not None:
            promotions_repo.toggle(promo)
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
        self._commit()
        self.log_action(current_user.id, current_user.name, "SUBIR_DOCUMENTO", "Documentos",
                        f"Cargado documento {doc.file_name} ({doc.doc_type}) para cliente {doc.client_id}")
        return doc

    def delete_document(self, current_user, doc_id) -> bool:
        if current_user.role not in ("admin", "employee"):
            return False
        doc = documents_repo.get_document(doc_id)
        if doc is None:
            return False
        documents_repo.delete_document(doc)
        self._commit()
        self.log_action(current_user.id, current_user.name, "ELIMINAR_DOCUMENTO", "Documentos",
                        f"Documento ID: {doc_id} eliminado.")
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
