"""Capa de repositorio (P2). Utilidades comunes y acceso genérico a la BD.

Los repositorios son la única capa que consulta y muta las tablas; la fachada
``app.store.DataStore`` los orquesta, añade auditoría y mantiene las firmas que
usan las rutas.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, JSON, Numeric

from ..extensions import db


def coerce_id(value):
    """Convierte un identificador de formulario/URL a entero; ``None`` si no lo es."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get(model, ident):
    """Devuelve la entidad con esa PK o ``None`` (sin lanzar por IDs inválidos)."""
    if ident is None or ident == "":
        return None
    pk_columns = list(model.__table__.primary_key.columns)
    if len(pk_columns) == 1 and isinstance(pk_columns[0].type, Integer):
        ident = coerce_id(ident)
        if ident is None:
            return None
    return db.session.get(model, ident)


def all_of(model, order=None):
    """Devuelve todas las filas del modelo, opcionalmente ordenadas."""
    query = db.session.query(model)
    if order is not None:
        query = query.order_by(order)
    return query.all()


def decrement_if_available(model, ident, column, amount) -> bool:
    """Descuenta inventario con un ``UPDATE`` condicional atómico (RN-01).

    Patrón único y reutilizable para cualquier existencia: ejecuta
    ``SET column = column - amount WHERE pk = ident AND column >= amount`` en
    una sola sentencia y comprueba el ``rowcount``. Evita el "leer y luego
    restar" (condición de carrera que permitiría sobreventa con peticiones
    concurrentes). Devuelve ``True`` solo si actualizó exactamente una fila.

    No confirma: participa de la transacción del llamador, que centraliza el
    ``commit`` en ``DataStore._commit``.
    """
    amount = to_int(amount)
    if amount < 0:
        return False
    if amount == 0:
        return True
    pk = list(model.__table__.primary_key.columns)[0]
    updated = (
        db.session.query(model)
        .filter(pk == ident, column >= amount)
        .update({column: column - amount}, synchronize_session="fetch")
    )
    return updated == 1


def to_decimal(value) -> Decimal:
    """Convierte a ``Decimal`` de forma tolerante."""
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def to_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def apply_fields(obj, data: dict, allowed) -> None:
    """Copia solo los campos de la lista blanca presentes en ``data``."""
    for key, value in data.items():
        if key in allowed and value is not None:
            setattr(obj, key, value)


def parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d/%m/%Y, %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _coerce_value(coltype, value):
    if value is None or value == "":
        return None
    if isinstance(coltype, DateTime):
        return parse_datetime(value)
    if isinstance(coltype, Date):
        return parse_date(value)
    if isinstance(coltype, Boolean):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "on", "yes", "sí", "si")
    if isinstance(coltype, Integer):
        return to_int(value)
    if isinstance(coltype, Float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(coltype, Numeric):
        return to_decimal(value)
    if isinstance(coltype, JSON):
        if isinstance(value, (list, dict)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return [item.strip() for item in str(value).split(",") if item.strip()]
    return value


def assign_by_type(obj, data, allowed=None, skip=()) -> None:
    """Asigna a ``obj`` los campos de ``data`` según el tipo de cada columna.

    Traduce los valores de formulario (siempre cadenas) al tipo real de la
    columna (fecha, decimal, booleano, JSON…) y respeta la lista blanca.
    """
    columns = {c.name: c for c in obj.__table__.columns}
    for key, value in data.items():
        if key in skip or key not in columns:
            continue
        if columns[key].primary_key:
            continue
        if allowed is not None and key not in allowed:
            continue
        setattr(obj, key, _coerce_value(columns[key].type, value))


def save(obj):
    """Añade una entidad nueva y hace ``flush`` para obtener su PK.

    No confirma: la confirmación es única y central (``DataStore._commit``).
    """
    db.session.add(obj)
    db.session.flush()
    return obj


def delete(obj) -> None:
    """Marca una entidad para borrado y hace ``flush`` (sin confirmar)."""
    db.session.delete(obj)
    db.session.flush()
