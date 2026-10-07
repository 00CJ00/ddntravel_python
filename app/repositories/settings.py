"""Repositorio de configuración clave/valor (predictive_data y contadores)."""
from __future__ import annotations

from .. import models as m
from .base import get, save

PREDICTIVE_KEY = "predictive_data"


def get_setting(key):
    return get(m.Setting, key)


def set_setting(key, value):
    setting = get(m.Setting, key)
    if setting is None:
        setting = m.Setting(key=key, value=value)
    else:
        setting.value = value
    return save(setting)


def get_predictive_data():
    setting = get(m.Setting, PREDICTIVE_KEY)
    return setting.value if setting is not None else None


def set_predictive_data(value) -> None:
    set_setting(PREDICTIVE_KEY, value)
