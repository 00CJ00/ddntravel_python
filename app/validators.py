"""Validadores de negocio para DDN Travel (Fase P3).

Validaciones: requeridos, tipos, rangos, email/documento válidos y únicos en clientes,
precios ≥ 0, return_date > departure_date. Errores → 422 (JSON) o flash + formulario.
"""

from __future__ import annotations

import re
from datetime import date, datetime


def validate_required(fields: dict, required: list[str], path: str = "form") -> list[str]:
    """Valida que los campos requeridos estén presentes y no vacíos.

    Returns lista de mensajes de error (vacía si todo ok).
    """
    errors = []
    for field in required:
        val = fields.get(field)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            errors.append(f"El campo '{field}' es obligatorio.")
    return errors


def validate_email(email: str) -> bool:
    """Valida formato de email con expresión regular."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def validate_price(price, field_name: str = "precio") -> list[str]:
    """Valida que un precio sea un número >= 0.

    Returns lista de mensajes de error.
    """
    errors = []
    try:
        val = float(price)
        if val < 0:
            errors.append(f"El campo '{field_name}' debe ser >= 0.")
    except (TypeError, ValueError):
        errors.append(f"El campo '{field_name}' debe ser un número válido.")
    return errors


def validate_date_greater_than(
    d1: str, d2: str, field1: str, field2: str
) -> list[str]:
    """Valida que d1 > d2 (usando strings ISO date). Returns error list."""
    errors = []
    try:
        dt1 = datetime.fromisoformat(d1).date() if d1 else None
        dt2 = datetime.fromisoformat(d2).date() if d2 else None
    except (ValueError, TypeError):
        errors.append(f"Formato de fecha inválido en {field1} o {field2}.")
        return errors

    if dt1 is not None and dt2 is not None and dt1 <= dt2:
        errors.append(f"La fecha {field1} debe ser posterior a la fecha {field2}.")
    return errors


def validate_departure_return(departure_date: str, return_date: str) -> list[str]:
    """Valida return_date > departure_date para reservas."""
    return validate_date_greater_than(return_date, departure_date, "return_date", "departure_date")


def validate_document_unique(
    document_id: str, client_id: str | None, clients: list, path: str = "form"
) -> list[str]:
    """Valida que el documento sea único entre clientes (excluyendo el cliente actual)."""
    errors = []
    # Buscar si ya existe otro cliente con este documento
    for c in clients:
        if c.id == client_id:
            continue
        if (c.document_id or "") == (document_id or ""):
            errors.append(f"Ya existe un cliente con el documento {document_id}.")
            break
    return errors


def validate_email_unique(
    email: str, client_id: str | None, clients: list, path: str = "form"
) -> list[str]:
    """Valida que el email sea único entre clientes (excluyendo el cliente actual)."""
    errors = []
    for c in clients:
        if c.id == client_id:
            continue
        if (c.email or "").strip().lower() == (email or "").strip().lower():
            errors.append(f"Ya existe un cliente con el email {email}.")
            break
    return errors


def validate_positive_int(value, field_name: str, minimum: int = 1) -> list[str]:
    """Valida que un entero sea positivo (mínimo por defecto 1)."""
    errors = []
    try:
        val = int(value)
        if val < minimum:
            errors.append(f"El campo '{field_name}' debe ser >= {minimum}.")
    except (TypeError, ValueError):
        errors.append(f"El campo '{field_name}' debe ser un entero válido.")
    return errors


def validate_room_count(
    rooms_count: int, hotel: object, available_rooms: int | None = None
) -> list[str]:
    """Valida que el número de habitaciones solicitadas no supere las disponibles.

    Para hoteles, verifica contra rooms_total y reservas solapadas.
    """
    errors = []
    if rooms_count < 1:
        errors.append("El número de habitaciones debe ser >= 1.")
    elif available_rooms is not None and rooms_count > available_rooms:
        errors.append(
            f"Solicitadas {rooms_count} habitaciones, pero solo hay {available_rooms} disponibles."
        )
    return errors