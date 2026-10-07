"""Repositorio de personas: usuarios y clientes."""
from __future__ import annotations

from sqlalchemy import func

from .. import models as m
from .base import all_of, assign_by_type, get, save, to_decimal, to_int


# --- Usuarios ---------------------------------------------------------
def list_users():
    return all_of(m.User, m.User.id)


def get_user(ident):
    return get(m.User, ident)


def get_user_by_email(email):
    if not email:
        return None
    return (m.User.query
            .filter(func.lower(m.User.email) == str(email).strip().lower())
            .first())


def create_user(data):
    return save(assign_by_type(m.User(), data, skip=("id",)))


# --- Clientes ---------------------------------------------------------
def list_clients():
    return all_of(m.Client, m.Client.id)


def get_client(ident):
    return get(m.Client, ident)


def get_client_by_email(email):
    if not email:
        return None
    return (m.Client.query
            .filter(func.lower(m.Client.email) == str(email).strip().lower())
            .first())


def create_client(data):
    client = m.Client()
    assign_by_type(client, data, skip=("id",))
    return save(client)


def update_client(obj, data):
    assign_by_type(obj, data, skip=("id",))
    return obj


def register_trip(client, amount) -> None:
    if client is not None:
        client.trips_count = to_int(client.trips_count) + 1
        client.total_spent = to_decimal(client.total_spent) + to_decimal(amount)
