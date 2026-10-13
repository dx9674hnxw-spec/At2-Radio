"""Trames AT2 : ``AA 55 <long> 00 <type> <groupe> <sous-cmd> <corps> <crc16 LE> 77 EE``.

Il n'y a qu'**un seul format de trame**. Le « dialecte CPS » décrit par les
anciennes versions n'en est pas un : une trame CPS (longueur sur 2 octets
petit-boutiste, sans ``00`` initial) est octet pour octet une trame classique
dont le type vaut ``0x11`` (lecture), ``0x12`` (écriture) ou ``0x91`` (réponse
de lecture), tant que la charge fait moins de 256 octets (voir
``tests/test_trame_unique.py``).

Le CRC est un CRC-16/CCITT non réfléchi (polynôme 0x1021, valeur initiale
0x1234), calculé sur la charge **sans** le ``00`` initial, écrit en
petit-boutiste. Format issu de ``At2FrameCodec.kt`` (application officielle
AT2 HT, Apache-2.0) ; voir NOTICE.
"""
from __future__ import annotations

from dataclasses import dataclass

HEAD = b"\xaa\x55"
TAIL = b"\x77\xee"

CRC16_POLY = 0x1021
CRC16_INIT = 0x1234


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT non réfléchi, polynôme 0x1021, valeur initiale 0x1234."""
    crc = CRC16_INIT
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ CRC16_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


class FrameError(ValueError):
    """Une trame ne peut pas être construite."""


def encode_frame(payload: bytes) -> bytes:
    """Enveloppe une charge (qui doit commencer par ``00``) dans une trame complète."""
    if not payload:
        raise FrameError("la charge ne peut pas être vide")
    if payload[0] != 0x00:
        raise FrameError("la charge d'une trame AT2 doit commencer par 0x00")
    body_len = len(payload) - 1
    if body_len > 0xFF:
        raise FrameError(f"charge trop longue : {len(payload)} octets")
    crc = crc16_ccitt(payload[1:])
    return HEAD + bytes([body_len]) + payload + crc.to_bytes(2, "little") + TAIL


def try_decode_frame(buf: bytes) -> tuple[bytes | None, int]:
    """Cherche et décode une trame complète dans ``buf``.

    Retourne ``(charge ou None, octets consommés)``. Si une trame est trouvée,
    les octets consommés s'arrêtent juste après sa fin. Si rien d'exploitable
    n'est encore arrivé, retourne ``(None, 0)`` : attendre plus de données.
    Un début de trame invalide est écarté pour se resynchroniser sur le prochain
    ``AA 55``.

    Deux variantes sont acceptées en réception (comme dans l'application
    officielle) : la longueur compte le ``00`` initial en plus (variante A,
    la forme émise) ou non (variante B, sans ``00`` stocké).
    """
    start = buf.find(HEAD)
    if start == -1:
        return None, 0
    if start + 7 > len(buf):
        return None, 0
    length = buf[start + 2]

    end_a = start + 3 + (length + 1) + 2 + 2
    if end_a <= len(buf) and buf[end_a - 2:end_a] == TAIL:
        payload_start = start + 3
        payload_end = payload_start + length + 1
        payload = buf[payload_start:payload_end]
        if payload and payload[0] == 0x00:
            got_crc = buf[payload_end] | (buf[payload_end + 1] << 8)
            if crc16_ccitt(payload[1:]) == got_crc:
                return payload, end_a

    end_b = start + 3 + length + 2 + 2
    if end_b <= len(buf) and buf[end_b - 2:end_b] == TAIL:
        payload_start = start + 3
        payload_end = payload_start + length
        body = buf[payload_start:payload_end]
        got_crc = buf[payload_end] | (buf[payload_end + 1] << 8)
        if crc16_ccitt(body) == got_crc:
            return b"\x00" + body, end_b

    return None, start + 2


@dataclass(frozen=True)
class At2Packet:
    """Un paquet décodé. ``type`` : 0x01 requête, 0x02 écriture, 0x81/0x82
    réponses, 0x11/0x12/0x91 lecture et écriture de canal. ``group`` : 0x01
    audio, 0x02 radio, 0x03 appareil, 0x04 hors réseau et extensions.
    ``body`` commence par la sous-commande."""

    type: int
    group: int
    body: bytes

    @property
    def hex_preview(self) -> str:
        return self.body[:24].hex()


def decode_packet(payload: bytes) -> At2Packet | None:
    """Transforme une charge décodée (``00`` + type + groupe + corps) en paquet."""
    if len(payload) < 4 or payload[0] != 0x00:
        return None
    return At2Packet(type=payload[1], group=payload[2], body=payload[3:])


def build_payload(type_: int, group: int, body: bytes = b"") -> bytes:
    return bytes([0x00, type_ & 0xFF, group & 0xFF]) + body
