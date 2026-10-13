"""Commandes de réglage et de requête, d'après ``At2Commands.kt`` (application
officielle AT2 HT, Apache-2.0), vérifiées contre ``vecteurs/commandes.json``.

Forme : écriture ``00 02 <groupe> <sous-cmd> <valeur>``, requête
``00 01 <groupe> <sous-cmd>``, réponse ``81 <groupe> <sous-cmd> <valeur>``.
Un accusé de réception de trame ne prouve pas que la radio a appliqué une
commande : le statut de chaque réglage est dans ``Setting.status``.
"""
from __future__ import annotations

from dataclasses import dataclass

from .frame import build_payload

TYPE_QUERY = 0x01
TYPE_WRITE = 0x02
TYPE_RESPONSE = 0x81

GROUP_AUDIO = 0x01
GROUP_RADIO = 0x02
GROUP_DEVICE = 0x03
GROUP_OFFLINE = 0x04   # hors réseau, extensions

SIDE = {"A": 0x01, "B": 0x02}

# Statuts de maturité, voir docs/PROTOCOLE.md §9.
ACK_ONLY = "acquitté seulement"
READ_BACK = "relu sur matériel"
PORTED = "porté de l'officiel, jamais relu"
NO_ANSWER = "requête sans réponse"


@dataclass(frozen=True)
class Setting:
    """Un réglage simple (un entier ou un booléen) de la radio."""

    name: str
    group: int
    sub: int
    width: int = 1              # octets de la valeur (petit-boutiste)
    low: int = 0
    high: int = 1
    is_bool: bool = False
    true_value: int = 1
    status: str = ACK_ONLY
    queryable: bool = True

    def encode_write(self, value: int | bool) -> bytes:
        if self.is_bool:
            v = self.true_value if value else 0x00
        else:
            v = int(value)
            if not (self.low <= v <= self.high):
                raise ValueError(f"{self.name} hors plage ({self.low}..{self.high}) : {v}")
        return build_payload(TYPE_WRITE, self.group, bytes([self.sub]) + v.to_bytes(self.width, "little"))

    def encode_query(self) -> bytes:
        return build_payload(TYPE_QUERY, self.group, bytes([self.sub]))

    def decode_value(self, raw: int) -> int | bool:
        return (raw == self.true_value) if self.is_bool else raw


SETTINGS: dict[str, Setting] = {s.name: s for s in [
    Setting("volume", GROUP_AUDIO, 0x01, low=1, high=8, status=READ_BACK),
    Setting("prompt_language", GROUP_AUDIO, 0x03, is_bool=True, status=PORTED),   # True = anglais
    Setting("prompt_tone", GROUP_AUDIO, 0x04, is_bool=True, status=PORTED),
    Setting("squelch", GROUP_RADIO, 0x04, low=0, high=9, status=READ_BACK),
    Setting("tot_seconds", GROUP_RADIO, 0x05, width=2, low=0, high=240, status=READ_BACK),
    Setting("vox", GROUP_RADIO, 0x06, is_bool=True, status=READ_BACK),
    Setting("vox_sensitivity", GROUP_RADIO, 0x07, low=1, high=5, status=READ_BACK),
    Setting("tx_inhibit", GROUP_RADIO, 0x09, is_bool=True, status=READ_BACK),
    Setting("tx_interval_seconds", GROUP_RADIO, 0x0A, width=2, low=0, high=240, status=READ_BACK),
    Setting("dual_watch", GROUP_RADIO, 0x0D, is_bool=True, true_value=0x02, status=READ_BACK),
    Setting("noise_reduction", GROUP_RADIO, 0x11, is_bool=True, status=READ_BACK),
    Setting("smart_link", GROUP_OFFLINE, 0x09, is_bool=True, status=NO_ANSWER),
]}

# Cibles de l'appui long du bouton PTT principal (Smart Link), officiel seulement.
MAIN_PTT_TARGETS = {"autre1": 0x01, "zello": 0x06, "autre3": 0x08, "autre4": 0x09, "autre2": 0x0A, "olaradio": 0x0B}


def _channel(channel: int) -> int:
    if not (1 <= channel <= 30):
        raise ValueError(f"canal hors plage (1..30) : {channel}")
    return channel


def select_channel(channel: int) -> bytes:
    """Canal actif (côté A du Dual Watch)."""
    return select_dual_watch_channel("A", channel)


def select_dual_watch_channel(side: str, channel: int) -> bytes:
    return build_payload(TYPE_WRITE, GROUP_RADIO, bytes([0x0E, SIDE[side], _channel(channel), 0x00]))


def select_dual_watch_focus(side: str) -> bytes:
    return build_payload(TYPE_WRITE, GROUP_RADIO, bytes([0x0F, SIDE[side]]))


def query_current_channel() -> bytes:
    return build_payload(TYPE_QUERY, GROUP_RADIO, bytes([0x0E]))


def query_dual_watch_focus() -> bytes:
    return build_payload(TYPE_QUERY, GROUP_RADIO, bytes([0x0F]))


def set_device_name(name: str) -> bytes:
    """Écriture du nom : ``00 02 03 01 <UTF-8>`` (le pont d'origine omettait le type 02)."""
    return build_payload(TYPE_WRITE, GROUP_DEVICE, bytes([0x01]) + name.encode("utf-8"))


def set_main_ptt_target(target: str) -> bytes:
    return build_payload(TYPE_WRITE, GROUP_OFFLINE, bytes([0x0A, 0x01, MAIN_PTT_TARGETS[target]]))


def query_main_ptt_target() -> bytes:
    return build_payload(TYPE_QUERY, GROUP_OFFLINE, bytes([0x0A, 0x01]))


def query_codeplug() -> bytes:
    """Demande de lecture globale des canaux (``Q@0202`` de l'application officielle)."""
    return build_payload(TYPE_QUERY, GROUP_RADIO, bytes([0x02]))


def write_codeplug_chunk(chunk: bytes) -> bytes:
    return build_payload(TYPE_WRITE, GROUP_RADIO, bytes([0x02]) + chunk)
