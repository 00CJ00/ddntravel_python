"""Modelos ORM de DDN Travel (fase P2).

Un módulo por agregado. Todos heredan de ``BaseEntity`` (utilidades comunes) y de
``db.Model`` (SQLAlchemy). Las antiguas entidades en memoria
(``app.models.legacy``) se eliminaron al completar el paso 5: la única fuente de
verdad son estos modelos.
"""
from .base import BaseEntity, utcnow
from .user import User
from .client import Client
from .destination import Destination
from .package import Package
from .hotel import Hotel, RoomType
from .flight import Flight
from .transport import Transport
from .activity import Activity
from .itinerary import Itinerary
from .booking import Booking, BookingPassenger
from .payment import Payment
from .ncf import NcfSequence
from .promotion import Promotion, PromotionRedemption
from .document import TravelDocument
from .notification import Notification, NotificationRead
from .setting import Setting
from .audit import AuditLog

__all__ = [
    "BaseEntity", "utcnow",
    "User", "Client", "Destination", "Package", "Hotel", "RoomType",
    "Flight", "Transport", "Activity", "Itinerary", "Booking", "BookingPassenger",
    "Payment", "NcfSequence", "Promotion", "PromotionRedemption", "TravelDocument",
    "Notification", "NotificationRead", "Setting", "AuditLog",
]
