"""Utilidades y clase base comunes a los modelos ORM (fase P2)."""
from __future__ import annotations

import datetime
from decimal import Decimal

from ..extensions import db


def utcnow() -> datetime.datetime:
    """Devuelve el instante actual en UTC (con zona horaria)."""
    return datetime.datetime.now(datetime.timezone.utc)


def _jsonable(value):
    """Convierte valores de columna a tipos seguros para JSON y plantillas."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


class BaseEntity:
    """Comportamiento común de las entidades: ``to_dict()``, ``describe()`` y ``repr``."""

    def to_dict(self) -> dict:
        """Devuelve las columnas como diccionario serializable a JSON."""
        return {col.name: _jsonable(getattr(self, col.name)) for col in self.__table__.columns}

    def describe(self) -> str:
        """Descripción corta de la entidad (cada subclase la puede sobreescribir)."""
        return f"{self.__class__.__name__} #{getattr(self, 'id', None)}"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={getattr(self, 'id', None)!r}>"
