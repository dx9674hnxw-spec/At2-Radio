"""Transport Bluetooth Low Energy (nécessite ``pip install at2radio[ble]``).

UUID relevés dans l'application officielle (``BleConstants.kt``, Apache-2.0) :
service ``AE60``, écriture ``AE10``, notifications ``AE05``.
"""
from __future__ import annotations

import logging

from .base import Transport

logger = logging.getLogger("at2radio.transport.ble")

SERVICE_UUID = "0000ae60-0000-1000-8000-00805f9b34fb"
TX_CHAR_UUID = "0000ae10-0000-1000-8000-00805f9b34fb"
RX_CHAR_UUID = "0000ae05-0000-1000-8000-00805f9b34fb"


def _bleak():
    try:
        import bleak
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("le transport BLE demande « pip install at2radio[ble] »") from e
    return bleak


async def scan(timeout: float = 5.0) -> list[dict]:
    """Radios BLE visibles, triées par signal décroissant (comme l'application officielle)."""
    bleak = _bleak()
    found = await bleak.BleakScanner.discover(timeout=timeout, return_adv=True)
    rows = [{"address": d.address, "name": d.name or adv.local_name or "(sans nom)", "rssi": adv.rssi}
            for d, adv in found.values()]
    return sorted(rows, key=lambda r: (-r["rssi"], r["name"].lower()))


class BleTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self._client = None

    async def connect(self, target: str, **kwargs) -> None:
        bleak = _bleak()
        await self.disconnect()
        self._client = bleak.BleakClient(target, disconnected_callback=self._on_disconnected)
        await self._client.connect(timeout=kwargs.get("timeout", 10.0))
        await self._client.start_notify(RX_CHAR_UUID, lambda _h, data: self._feed(bytes(data)))
        self._connected = True
        logger.info("BLE connecté : %s", target)

    def _on_disconnected(self, _client) -> None:
        if self._connected:
            self._lost()

    async def disconnect(self) -> None:
        was, self._connected = self._connected, False
        client, self._client = self._client, None
        if client is not None and was:
            try:
                await client.stop_notify(RX_CHAR_UUID)
                await client.disconnect()
            except Exception:
                logger.debug("erreur à la déconnexion BLE", exc_info=True)

    async def _write(self, frame: bytes) -> None:
        assert self._client is not None
        await self._client.write_gatt_char(TX_CHAR_UUID, frame, response=True)
