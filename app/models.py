"""
Modelos del sistema DDN Travel.

Se define una clase base `Entity` de la cual heredan todas las entidades
del negocio (Cliente, Reserva, Paquete, etc.). Esto permite reutilizar
comportamiento común (id, conversión a diccionario, actualización de
campos) y a la vez dejar que cada subclase agregue su propia lógica de
negocio particular (polimorfismo / method overriding), tal como se vio
en el curso de Programación Orientada a Objetos (herencia de vehículos,
animales, etc.).
"""
from __future__ import annotations
import time
import random
import string


def new_id(prefix: str) -> str:
    """Genera un identificador único simple, similar al Date.now() de JS."""
    return f"{prefix}-{int(time.time() * 1000)}"


def short_code(prefix: str, digits: int = 3) -> str:
    return f"{prefix}-{random.randint(10 ** (digits - 1), 10 ** digits - 1)}"


class Entity:
    """Clase base para todas las entidades del sistema."""

    def __init__(self, **data):
        self.id = data.pop("id", None)
        for key, value in data.items():
            setattr(self, key, value)

    def to_dict(self) -> dict:
        """Convierte la entidad a un diccionario plano (para JSON / plantillas)."""
        return dict(self.__dict__)

    def update(self, **changes) -> None:
        """Actualiza uno o más atributos de la entidad."""
        for key, value in changes.items():
            setattr(self, key, value)

    def describe(self) -> str:
        """Descripción corta de la entidad. Cada subclase la sobreescribe."""
        return f"{self.__class__.__name__} #{self.id}"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id!r}>"


class UserSession(Entity):
    def describe(self) -> str:
        return f"{self.name} ({self.role})"


class Client(Entity):
    """Cliente registrado en el CRM de DDN Travel (RF-03)."""

    def __init__(self, **data):
        data.setdefault("trips_count", 0)
        data.setdefault("total_spent", 0)
        data.setdefault("status", "Activo")
        data.setdefault("preferred_destinations", [])
        super().__init__(**data)

    def register_trip(self, amount: float) -> None:
        """Actualiza las estadísticas del cliente tras confirmar una reserva."""
        self.trips_count += 1
        self.total_spent += amount

    def describe(self) -> str:
        return f"{self.name} ({self.category})"


class Destination(Entity):
    def describe(self) -> str:
        return f"{self.name}, {self.country}"


class TourPackage(Entity):
    """Paquete turístico. Controla su propia disponibilidad (RN-01)."""

    def has_availability(self, travelers: int) -> bool:
        return self.available_slots >= travelers

    def reserve_slots(self, travelers: int) -> None:
        self.available_slots = max(0, self.available_slots - travelers)

    def release_slots(self, travelers: int) -> None:
        max_slots = getattr(self, "total_slots", None) or getattr(self, "max_capacity", None) or (
            self.available_slots + travelers
        )
        self.available_slots = min(max_slots, self.available_slots + travelers)

    def describe(self) -> str:
        return f"{self.title} — {self.destination_name}"


class Hotel(Entity):
    def describe(self) -> str:
        return f"{self.name} ({self.stars}★)"


class Flight(Entity):
    def describe(self) -> str:
        return f"{self.airline} {self.flight_number}"


class TouristTransport(Entity):
    def describe(self) -> str:
        return f"{self.type} — {self.route}"


class TouristActivity(Entity):
    def describe(self) -> str:
        return self.title


class Booking(Entity):
    """Reserva de viaje. Concentra las reglas de negocio RN-01 a RN-03."""

    def __init__(self, **data):
        data.setdefault("amount_paid", 0)
        data.setdefault("passengers", [])
        super().__init__(**data)

    def balance_due(self) -> float:
        return max(0, self.total_price - self.amount_paid)

    def is_fully_paid(self) -> bool:
        return self.amount_paid >= self.total_price

    def apply_payment(self, amount: float) -> None:
        self.amount_paid += amount
        self.payment_status = "Pagado" if self.is_fully_paid() else "Parcial"
        if self.is_fully_paid():
            self.status = "Confirmada"

    def describe(self) -> str:
        return f"{self.booking_code} — {self.client_name}"


class PaymentTransaction(Entity):
    def __init__(self, **data):
        data.setdefault("receipt_number", "")
        data.setdefault("booking_id", "")
        data.setdefault("booking_code", "")
        data.setdefault("client_name", "")
        data.setdefault("amount_paid", 0)
        data.setdefault("payment_method", "Tarjeta de Crédito")
        data.setdefault("status", "Completado")
        data.setdefault("ncf", "")  # Nuevo campo: Número de Factura
        data.setdefault("invoice_number", "")
        super().__init__(**data)

    def describe(self) -> str:
        return f"{self.receipt_number} (${self.amount})"

    def is_ncf_generated(self) -> bool:
        """Devuelve True si el pago ya tiene NCF asignado."""
        return bool(self.ncf and self.ncf.strip())


class Promotion(Entity):
    def __init__(self, **data):
        data.setdefault("current_uses", 0)
        super().__init__(**data)

    def is_valid(self) -> bool:
        return bool(self.active) and self.current_uses < self.max_uses

    def apply_to(self, total_price: float):
        if not self.is_valid():
            return total_price, 0
        discount = total_price * self.discount_percentage / 100
        return max(0, total_price - discount), discount

    def describe(self) -> str:
        return f"{self.code} (-{self.discount_percentage}%)"


class NotificationItem(Entity):
    def __init__(self, **data):
        data.setdefault("read", False)
        # visible_roles: lista de roles que pueden ver la notificación
        # (None = visible para todos los roles)
        data.setdefault("visible_roles", None)
        super().__init__(**data)


class AuditLog(Entity):
    def describe(self) -> str:
        return f"[{self.timestamp}] {self.action}"


class TravelDocument(Entity):
    def describe(self) -> str:
        return self.file_name or self.document_type or "Documento"
