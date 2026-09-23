"""Test de saneamiento de codificación del seed (mojibake)."""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pathlib import Path

SEED_PATH = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))) / "app" / "seed_data.json"

MOJIBAKE_CHARS = ("Ã", "Â", "\ufffd")
MOJIBAKE_SEQUENCES = (
    "â‡„",  # cp1252 3 bytes de U+21C4 "⇄"
    "â˜…",  # cp1252 3 bytes de U+2605 "★"
    "â™¦",  # cp1252 3 bytes de U+2666 "♦"
)


def _walk_strings(value):
    """Itera sobre todos los strings de una estructura JSON anidada."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)


def test_seed_no_contiene_mojibake():
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    bad = [
        s for s in _walk_strings(data)
        if any(ch in s for ch in MOJIBAKE_CHARS)
    ]
    assert not bad, f"Strings con mojibake en seed_data.json: {bad[:10]}"


def test_seed_no_contiene_triples_cp1252():
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    bad = [
        s for s in _walk_strings(data)
        if any(seq in s for seq in MOJIBAKE_SEQUENCES)
    ]
    assert not bad, f"Triples cp1252 corruptos en seed_data.json: {bad[:10]}"


def test_seed_es_utf8_sin_bom():
    raw = SEED_PATH.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "El seed debe estar en UTF-8 sin BOM"


def test_seed_json_valido():
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for key in ("initial_users", "initial_clients", "initial_packages",
                "initial_bookings", "initial_payments"):
        assert isinstance(data.get(key), list), f"Falta la colección {key}"