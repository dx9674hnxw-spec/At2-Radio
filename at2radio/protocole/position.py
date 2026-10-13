"""Positions et SOS dans un message texte, au format de l'application officielle.

Le protocole n'a pas de type « position » : c'est une convention sur le texte.
Format de l'application AT2 HT (``LocationShareController.kt``) :

* position : ``<lat>*-#-*-#-*-#-*<lon>``
* SOS      : ``<message>#-*-#-*-#-*-#<lat>*-#-*-#-*-#-*<lon>``

Coordonnées décimales avec 6 décimales au plus, zéros finaux supprimés.
L'ancien format de at2-bridge (``📍 lat,lon``) est encore **lu** pour rester
compatible, mais n'est plus émis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

COORD_SEPARATOR = "*-#-*-#-*-#-*"
HELP_SEPARATOR = "#-*-#-*-#-*-#"
MAX_HELP_MESSAGE_UTF8_BYTES = 800

DEFAULT_HELP_PRESETS = (
    "Lost, need directions",
    "Injured, urgently need medicine",
    "Trapped in heavy rain, need rescue",
    "Hypothermia, urgently need warm supplies",
    "No signal, need location information",
    "It’s dark, can’t find the campsite",
    "Lack of water, where is the nearest water source?",
    "Car stuck, need help getting out",
)

_LEGACY = re.compile(r"📍\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class ParsedPosition:
    kind: str                 # "position" ou "sos"
    lat: float
    lon: float
    message: str = ""         # texte du SOS (vide pour une simple position)


def format_coordinate(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def encode_position(lat: float, lon: float) -> str:
    _check(lat, lon)
    return format_coordinate(lat) + COORD_SEPARATOR + format_coordinate(lon)


def encode_sos(message: str, lat: float, lon: float) -> str:
    _check(lat, lon)
    message = message.strip()
    if len(message.encode("utf-8")) > MAX_HELP_MESSAGE_UTF8_BYTES:
        raise ValueError(f"message de SOS trop long (maximum {MAX_HELP_MESSAGE_UTF8_BYTES} octets UTF-8)")
    return message + HELP_SEPARATOR + encode_position(lat, lon)


def _check(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"coordonnées hors plage : {lat}, {lon}")


def _coords(text: str) -> tuple[float, float] | None:
    parts = text.split(COORD_SEPARATOR, 1)
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def parse_position(text: str) -> ParsedPosition | None:
    """Reconnaît une position ou un SOS dans un texte reçu, sinon ``None``."""
    text = text.strip()
    if not text:
        return None
    help_parts = text.split(HELP_SEPARATOR, 1)
    if len(help_parts) == 2:
        c = _coords(help_parts[1])
        return ParsedPosition("sos", c[0], c[1], help_parts[0].strip()) if c else None
    c = _coords(text)
    if c:
        return ParsedPosition("position", c[0], c[1])
    m = _LEGACY.search(text)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            sos = "🆘" in text
            return ParsedPosition("sos" if sos else "position", lat, lon, text[:m.start()].replace("🆘", "").strip())
    return None
