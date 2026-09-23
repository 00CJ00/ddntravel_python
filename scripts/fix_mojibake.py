"""
Corrige mojibake en app/seed_data.json.

Patrones detectados:

1. Latin-1 / Windows-1252 (2 bytes): strings que contienen 'Ã' o 'Â' seguidos de
   un carácter en el rango U+0080–U+00BF (resultado de haber codificado UTF-8
   pero decodificado como Latin-1, p. ej. "DirecciÃ³n" en vez de "Dirección").

2. Windows-1252 (3 bytes): strings con 'â' (lead UTF-8 0xE2) seguido de dos
   caracteres cuyos valores cp1252 son bytes de continuación 0x80–0xBF y forman
   un carácter UTF-8 válido, p. ej. "â‡„" (→ U+21C4 "⇄"), "â˜…" (→ U+2605 "★")
   y "â™¦" (→ U+2666 "♦").

Ambos se corrigen reconstruyendo la secuencia UTF-8 original byte a byte; si la
conversión falla se deja el original y se reporta. Reescribe el JSON con
``ensure_ascii=False``, ``indent=2`` y UTF-8 sin BOM.
"""
import json
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parent.parent / "app" / "seed_data.json"


def mojibake_second_byte(ch: str):
    """Devuelve el byte original del 2º carácter de un par de mojibake, o None.

    Cubre Latin-1 (U+0080–U+00FF) y las extensiones de Windows-1252 que la
    app hereda (p. ej. 0x93 → «) sin tocar caracteres Unicode correctos.
    """
    code = ord(ch)
    if 0x80 <= code <= 0xFF:
        return bytes([code])
    try:
        encoded = ch.encode("cp1252")
    except UnicodeEncodeError:
        return None
    return encoded if len(encoded) == 1 else None


def triple_bytes(text: str, i: int):
    """Devuelve los 3 bytes originales de un triple de mojibake cp1252, o None.

    Detecta 'â' (0xE2, lead de caracteres U+0800–U+FFFF) seguido de dos
    caracteres cuyos valores cp1252 son bytes de continuación 0x80–0xBF y cuya
    concatenación forma un carácter UTF-8 válido. P. ej. "â‡„" → U+21C4 "⇄",
    "â˜…" → U+2605 "★" y "â™¦" → U+2666 "♦".
    """
    if text[i] != "â" or i + 2 >= len(text):
        return None
    b1 = mojibake_second_byte(text[i + 1])
    b2 = mojibake_second_byte(text[i + 2])
    if b1 is None or b2 is None:
        return None
    if not (0x80 <= b1[0] <= 0xBF and 0x80 <= b2[0] <= 0xBF):
        return None
    raw = bytes([0xE2, b1[0], b2[0]])
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return raw


def looks_like_mojibake(text: str) -> bool:
    """True si el string contiene un par o un triple de mojibake (Latin-1/CP1252)."""
    for i, ch in enumerate(text):
        if ch in ("Ã", "Â") and i + 1 < len(text) and mojibake_second_byte(text[i + 1]) is not None:
            return True
        if triple_bytes(text, i) is not None:
            return True
    return False


def fix_string(text: str) -> str:
    """Corrige el mojibake respetando caracteres Unicode ya correctos.

    Los pares "Ã/Â + byte original" y los triples cp1252 "â + 2 bytes" vuelven a
    su secuencia UTF-8 correcta; el resto del string se conserva codificando en
    UTF-8, y finalmente todo se decodifica como UTF-8. Así se corrigen strings
    mixtos (p. ej. con "★" o "⇄" ya correctos) que un ``encode('latin-1')``
    global no permitiría.
    """
    try:
        out = bytearray()
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "â":
                raw = triple_bytes(text, i)
                if raw is not None:
                    out += raw
                    i += 3
                    continue
            if ch in ("Ã", "Â") and i + 1 < len(text):
                byte2 = mojibake_second_byte(text[i + 1])
                if byte2 is not None:
                    out += ch.encode("latin-1")
                    out += byte2
                    i += 2
                    continue
            out += ch.encode("utf-8")
            i += 1
        return out.decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError) as exc:
        print(f"[AVISO] No se pudo corregir el string {text!r}: {exc}")
        return text


def fix_value(value):
    """Recorre estructuras anidadas corrigiendo todo string que parezca mojibake."""
    if isinstance(value, str):
        return fix_string(value) if looks_like_mojibake(value) else value
    if isinstance(value, list):
        return [fix_value(item) for item in value]
    if isinstance(value, dict):
        return {key: fix_value(item) for key, item in value.items()}
    return value


def count_mojibake(value) -> int:
    if isinstance(value, str):
        return 1 if looks_like_mojibake(value) else 0
    if isinstance(value, list):
        return sum(count_mojibake(item) for item in value)
    if isinstance(value, dict):
        return sum(count_mojibake(item) for item in value.values())
    return 0


def main() -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    total = count_mojibake(data)
    fixed_data = fix_value(data)
    SEED_PATH.write_text(
        json.dumps(fixed_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    remaining = count_mojibake(fixed_data)
    print(f"Strings con mojibake: {total} corregidos, {remaining} restantes.")


if __name__ == "__main__":
    main()