"""
DataStore: estado central de la aplicación DDN Travel.

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


def auto_save(method):
    """Persiste el estado en disco después de cada operación que muta datos."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        result = method(self, *args, **kwargs)
        self.persist()
        return result
    return wrapper

PAYMENT_METHODS = ["Tarjeta de Crédito", "Transferencia Bancaria", "Efectivo", "Cripto", "PayPal"]


def _now_str() -> str:
    return datetime.datetime.now().strftime("%d/%m/%Y, %H:%M")


def _today() -> str:
    return datetime.date.today().isoformat()


class DataStore:
    """Contenedor único (singleton a nivel de módulo) de todo el estado de la app."""

    def __init__(self):
        self._raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        self.reset_all_data(log=False)
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

    # ------------------------------------------------------------------
    # Auditoría y notificaciones (RN-05)
    # ------------------------------------------------------------------
    def log_action(self, user_id: str, user_name: str, action: str, module: str, details: str) -> None:
        user = self.get_user(user_id)
        log = AuditLog(
            id=new_id("log"),
            timestamp=_now_str(),
            user_id=user_id,
            user_name=user_name,
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
            client.update(**changes)
            self.log_action(current_user.id, current_user.name, "MODIFICAR_CLIENTE", "Clientes",
                             f"Actualizada información del cliente ID: {client_id}")

    def delete_client(self, current_user, client_id: str) -> bool:
        self.clients = [c for c in self.clients if c.id != client_id]
        self.log_action(current_user.id, current_user.name, "ELIMINAR_CLIENTE", "Clientes",
                         f"Eliminado cliente ID: {client_id}")
        return True

    # ------------------------------------------------------------------
    # Catálogo genérico (destinos, hoteles, vuelos, transportes, actividades)
    # ------------------------------------------------------------------
    def add_destination(self, current_user, **data) -> Destination:
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
        for key, value in data.items():
            if hasattr(dest, key):
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
        self.hotels = [h for h in self.hotels if h.id != hotel_id]
        self.log_action(current_user.id, current_user.name, "ELIMINAR_HOTEL", "Hoteles",
                         f"Eliminado hotel ID: {hotel_id}")
        return True

    def add_flight(self, current_user, **data) -> Flight:
        flight = Flight(id=new_id("flt"), **data)
        self.flights.insert(0, flight)
        self.log_action(current_user.id, current_user.name, "CREAR_VUELO", "Vuelos",
                         f"Registrado nuevo vuelo: {flight.airline} {flight.flight_number}")
        return flight

    def delete_flight(self, current_user, flight_id: str) -> bool:
        self.flights = [f for f in self.flights if f.id != flight_id]
        self.log_action(current_user.id, current_user.name, "ELIMINAR_VUELO", "Vuelos",
                         f"Eliminado vuelo ID: {flight_id}")
        return True

    def add_transport(self, current_user, **data) -> TouristTransport:
        transport = TouristTransport(id=new_id("trn"), **data)
        self.transports.insert(0, transport)
        self.log_action(current_user.id, current_user.name, "CREAR_TRANSPORTE", "Transporte",
                         f"Registrada unidad de transporte: {transport.vehicle_model}")
        return transport

    def delete_transport(self, current_user, transport_id: str) -> bool:
        self.transports = [t for t in self.transports if t.id != transport_id]
        self.log_action(current_user.id, current_user.name, "ELIMINAR_TRANSPORTE", "Transporte",
                         f"Eliminada unidad de transporte ID: {transport_id}")
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
        self.activities = [a for a in self.activities if a.id != activity_id]
        self.log_action(current_user.id, current_user.name, "ELIMINAR_ACTIVIDAD", "Actividades",
                         f"Eliminada actividad ID: {activity_id}")
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

    # ------------------------------------------------------------------
    # Reservas — RN-01 (disponibilidad), RN-02 (cliente obligatorio),
    # RN-03 (pago antes de confirmar)
    # ------------------------------------------------------------------
    def create_booking(self, current_user, *, client_id, client_name, client_email,
                        package_id=None, package_name="", destination_name="",
                        departure_date="", return_date="", travelers=1, passengers=None,
                        hotel_id=None, hotel_name=None, flight_id=None, flight_number=None,
                        total_price=0.0, notes="", initial_payment=0.0,
                        payment_method="Tarjeta de Crédito"):
        # RN-02: toda reserva debe estar asociada a un cliente válido
        if not client_id or not client_name:
            return {"success": False,
                    "message": "Regla de Negocio (RN-02): Toda reserva debe estar asociada a un cliente registrado válido."}

        # RN-01: no se puede reservar sin disponibilidad
        selected_pkg = self.get_package(package_id) if package_id else None
        if selected_pkg and selected_pkg.available_slots < travelers:
            return {"success": False,
                    "message": (f'Regla de Negocio (RN-01): No hay disponibilidad suficiente. El paquete '
                                f'"{selected_pkg.title}" solo cuenta con {selected_pkg.available_slots} cupos '
                                f'disponibles para {travelers} viajeros solicitados.')}

        booking_year = datetime.date.today().year
        booking_code = f"DDN-{booking_year}-{random.randint(100, 999)}"
        booking_id = new_id("bkg")

        is_full_paid = initial_payment >= total_price and total_price > 0
        is_partial_paid = 0 < initial_payment < total_price

        payment_status = "Pagado" if is_full_paid else ("Parcial" if is_partial_paid else "Pendiente")
        status = "Confirmada" if is_full_paid else "Pendiente"

        booking = Booking(
            id=booking_id, booking_code=booking_code, client_id=client_id, client_name=client_name,
            client_email=client_email, package_id=package_id, package_name=package_name,
            destination_name=destination_name, departure_date=departure_date, return_date=return_date,
            travelers=travelers, passengers=passengers or [], hotel_id=hotel_id, hotel_name=hotel_name,
            flight_id=flight_id, flight_number=flight_number, total_price=total_price,
            amount_paid=initial_payment, payment_status=payment_status, status=status,
            created_at=_today(), notes=notes,
        )

        if selected_pkg:
            selected_pkg.reserve_slots(travelers)

        client = self.get_client(client_id)
        if client:
            client.register_trip(total_price)

        self.bookings.insert(0, booking)

        if initial_payment > 0:
            payment = PaymentTransaction(
                id=new_id("pay"), receipt_number=f"REC-{booking_year}-{random.randint(1000, 9999)}",
                booking_id=booking_id, booking_code=booking_code, client_name=client_name,
                amount=initial_payment, payment_method=payment_method,
                transaction_ref=f"TX_{random.randint(100000, 999999)}", status="Completado",
                date=_now_str(), invoice_number=f"FAC-DDN-{random.randint(10000, 99999)}",
            )
            self.payments.insert(0, payment)

        self.log_action(current_user.id, current_user.name, "NUEVA_RESERVA", "Reservas",
                         f"Reserva {booking_code} creada para {client_name} ({destination_name}) "
                         f"por un total de ${total_price} USD.")
        self.add_notification("Nueva Reserva Confirmada",
                               f"Reserva {booking_code} generada para {client_name}. Total: ${total_price} USD.",
                               "success", "bookings")

        return {"success": True, "message": f"¡Reserva {booking_code} registrada con éxito!", "booking": booking}

    def update_booking_status(self, current_user, booking_id: str, status: str) -> None:
        booking = self.get_booking(booking_id)
        if booking:
            booking.status = status
            self.log_action(current_user.id, current_user.name, "ACTUALIZAR_ESTADO_RESERVA", "Reservas",
                             f"Reserva ID: {booking_id} actualizada a estado: {status}")

    def cancel_booking(self, current_user, booking_id: str, reason: str = "") -> bool:
        booking = self.get_booking(booking_id)
        if not booking:
            return False
        pkg = self.get_package(booking.package_id) if getattr(booking, "package_id", None) else None
        if pkg:
            pkg.release_slots(booking.travelers)
        booking.status = "Cancelada"
        booking.notes = f"{getattr(booking, 'notes', '') or ''} [Cancelada: {reason or 'Por solicitud'}]"
        self.log_action(current_user.id, current_user.name, "CANCELAR_RESERVA", "Reservas",
                         f"Reserva {booking.booking_code} cancelada. Motivo: {reason or 'N/A'}")
        self.add_notification("Reserva Cancelada",
                               f"La reserva {booking.booking_code} fue cancelada. Se han restaurado los cupos.",
                               "warning", "bookings")
        return True

    # ------------------------------------------------------------------
    # Pagos & facturación (RF-11, RN-03)
    # ------------------------------------------------------------------
    def register_payment(self, current_user, booking_id: str, amount: float, method: str, ref_number: str = ""):
        booking = self.get_booking(booking_id)
        if not booking:
            return {"success": False, "message": "Reserva no encontrada."}
        if amount <= 0:
            return {"success": False, "message": "El monto del pago debe ser mayor a 0."}

        booking.apply_payment(amount)

        receipt_number = f"REC-{datetime.date.today().year}-{random.randint(1000, 9999)}"
        invoice_number = f"FAC-DDN-{random.randint(10000, 99999)}"

        payment = PaymentTransaction(
            id=new_id("pay"), receipt_number=receipt_number, booking_id=booking.id,
            booking_code=booking.booking_code, client_name=booking.client_name, amount=amount,
            payment_method=method, transaction_ref=ref_number or f"TX_{random.randint(100000, 999999)}",
            status="Completado", date=_now_str(), invoice_number=invoice_number,
        )
        self.payments.insert(0, payment)

        if booking.is_fully_paid():
            voucher = TravelDocument(
                id=new_id("doc"), client_id=booking.client_id, client_name=booking.client_name,
                doc_type="Voucher de Reserva", file_name=f"Voucher_Oficial_{booking.booking_code}.pdf",
                file_size="1.4 MB", upload_date=_today(), status="Válido",
            )
            self.documents.insert(0, voucher)

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

    def apply_promo_code(self, code: str, total_price: float) -> dict:
        clean_code = (code or "").strip().upper()
        promo = next((p for p in self.promotions if p.code.upper() == clean_code and p.active), None)
        if not promo:
            return {"valid": False, "discount_percentage": 0, "final_price": total_price,
                     "message": "Código de promoción no válido o expirado."}
        if promo.current_uses >= promo.max_uses:
            return {"valid": False, "discount_percentage": 0, "final_price": total_price,
                     "message": "Este código ha alcanzado el límite máximo de usos."}
        final_price, discount = promo.apply_to(total_price)
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
        self.documents = [d for d in self.documents if d.id != doc_id]
        self.log_action(current_user.id, current_user.name, "ELIMINAR_DOCUMENTO", "Documentos",
                         f"Documento ID: {doc_id} eliminado.")
        return True


# Aplica persistencia automática a todas las operaciones que mutan datos.
for _method_name in [
    "add_client", "update_client", "delete_client",
    "add_destination", "add_hotel", "delete_hotel", "add_flight", "delete_flight",
    "add_transport", "delete_transport", "add_activity", "delete_activity",
    "add_package", "create_booking", "update_booking_status", "cancel_booking",
    "register_payment", "add_promotion", "toggle_promotion_status",
    "add_document", "delete_document",
    "log_action", "add_notification",
    "mark_notification_as_read", "mark_all_notifications_as_read",
]:
    if hasattr(DataStore, _method_name):
        setattr(DataStore, _method_name, auto_save(getattr(DataStore, _method_name)))

# Instancia única compartida por toda la aplicación (equivalente al Provider de React)
store = DataStore()
