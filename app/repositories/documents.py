"""Repositorio de documentos de viaje (RF-17)."""
from __future__ import annotations

from sqlalchemy import desc

from .. import models as m
from .base import all_of, assign_by_type, delete, get, save


def list_documents():
    return all_of(m.TravelDocument, desc(m.TravelDocument.created_at))


def get_document(ident):
    return get(m.TravelDocument, ident)


def create_document(data):
    doc = m.TravelDocument()
    assign_by_type(doc, data, skip=("id",))
    return save(doc)


def delete_document(obj) -> None:
    delete(obj)
