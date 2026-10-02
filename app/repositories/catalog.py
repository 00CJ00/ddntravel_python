"""Repositorio del catálogo: destinos, paquetes, hoteles, vuelos, transporte y actividades."""
from __future__ import annotations

from .. import models as m
from .base import all_of, assign_by_type, delete, get, save, to_int


# --- Destinos ---------------------------------------------------------
def list_destinations():
    return all_of(m.Destination, m.Destination.id)


def get_destination(ident):
    return get(m.Destination, ident)


def create_destination(data):
    return save(assign_by_type(m.Destination(), data, skip=("id",)))


def update_destination(obj, data):
    assign_by_type(obj, data, skip=("id",))
    return obj


# --- Paquetes ---------------------------------------------------------
def list_packages():
    return all_of(m.Package, m.Package.id)


def get_package(ident):
    return get(m.Package, ident)


def create_package(data):
    obj = m.Package()
    assign_by_type(obj, data, skip=("id",))
    return save(obj)


def reserve_slots_atomic(package_id, travelers) -> bool:
    """Descuenta cupos con un UPDATE condicional atómico (RN-01)."""
    updated = (
        m.Package.query
        .filter(m.Package.id == package_id, m.Package.available_slots >= travelers)
        .update({m.Package.available_slots: m.Package.available_slots - travelers},
                synchronize_session="fetch")
    )
    return updated == 1


def release_slots(package_id, travelers) -> None:
    package = get(m.Package, package_id)
    if package is not None:
        package.release_slots(travelers)


# --- Hoteles y tipos de habitación -----------------------------------
def list_hotels():
    return all_of(m.Hotel, m.Hotel.id)


def get_hotel(ident):
    return get(m.Hotel, ident)


def create_hotel(data, room_types=None):
    hotel = m.Hotel()
    assign_by_type(hotel, data, skip=("id", "room_types"))
    save(hotel)
    for rt in room_types or []:
        room = m.RoomType(hotel_id=hotel.id, name=rt.get("type") or rt.get("name"),
                          price_per_night=rt.get("price_per_night"),
                          rooms_total=to_int(rt.get("available") or rt.get("rooms_total")))
        save(room)
    return hotel


def get_room_type(ident):
    return get(m.RoomType, ident)


# --- Vuelos -----------------------------------------------------------
def list_flights():
    return all_of(m.Flight, m.Flight.id)


def get_flight(ident):
    return get(m.Flight, ident)


def create_flight(data):
    return save(assign_by_type(m.Flight(), data, skip=("id",)))


# --- Transporte -------------------------------------------------------
def list_transports():
    return all_of(m.Transport, m.Transport.id)


def get_transport(ident):
    return get(m.Transport, ident)


def create_transport(data):
    return save(assign_by_type(m.Transport(), data, skip=("id",)))


# --- Actividades ------------------------------------------------------
def list_activities():
    return all_of(m.Activity, m.Activity.id)


def get_activity(ident):
    return get(m.Activity, ident)


def create_activity(data):
    return save(assign_by_type(m.Activity(), data, skip=("id",)))
