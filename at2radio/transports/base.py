"""Interface commune des transports (BLE, USB série) : même protocole de trames."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable

from ..protocole.frame import At2Packet, decode_packet, encode_frame, try_decode_frame

logger = logging.getLogger("at2radio.transport")

MAX_RX_BUFFER_BYTES = 64 * 1024


class Transport(ABC):
    """Un lien avec une radio. Ne connaît ni les commandes ni les messages."""

    def __init__(self) -> None:
        self._rx_buffer = bytearray()
        self._packet_listeners: list[Callable[[At2Packet], None]] = []
        self._log_listeners: list[Callable[[str], None]] = []
        self._disconnect_listeners: list[Callable[[], None]] = []
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def on_packet(self, callback: Callable[[At2Packet], None]) -> None:
        self._packet_listeners.append(callback)

    def off_packet(self, callback: Callable[[At2Packet], None]) -> None:
        if callback in self._packet_listeners:
            self._packet_listeners.remove(callback)

    def on_log(self, callback: Callable[[str], None]) -> None:
        self._log_listeners.append(callback)

    def on_disconnect(self, callback: Callable[[], None]) -> None:
        """Appelé quand le lien est perdu sans demande de déconnexion."""
        self._disconnect_listeners.append(callback)

    def _log_line(self, line: str) -> None:
        for cb in list(self._log_listeners):
            try:
                cb(line)
            except Exception:
                logger.exception("écouteur de journal en erreur")

    def _lost(self) -> None:
        self._connected = False
        for cb in list(self._disconnect_listeners):
            try:
                cb()
            except Exception:
                logger.exception("écouteur de déconnexion en erreur")

    def _feed(self, data: bytes) -> None:
        """Reçoit des octets bruts, extrait les trames complètes et les distribue."""
        self._rx_buffer += data
        if len(self._rx_buffer) > MAX_RX_BUFFER_BYTES:
            self._log_line("tampon de réception vidé (trop volumineux)")
            self._rx_buffer.clear()
            return
        while True:
            payload, consumed = try_decode_frame(bytes(self._rx_buffer))
            if consumed == 0:
                break
            raw = bytes(self._rx_buffer[:consumed])
            del self._rx_buffer[:consumed]
            if payload is None:
                self._log_line(f"RX trame incomplète ou corrompue ignorée : {raw.hex()}")
                continue
            self._log_line(f"RX {raw.hex()}")
            packet = decode_packet(payload)
            if packet is None:
                self._log_line(f"RX charge indécodable : {payload.hex()}")
                continue
            for cb in list(self._packet_listeners):
                try:
                    cb(packet)
                except Exception:
                    logger.exception("écouteur de paquet en erreur")

    @abstractmethod
    async def connect(self, target: str, **kwargs) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def _write(self, frame: bytes) -> None: ...

    async def send_payload(self, payload: bytes) -> None:
        """Encode une charge en trame complète et l'envoie."""
        await self.send_raw_frame(encode_frame(payload))

    async def send_raw_frame(self, frame: bytes) -> None:
        """Envoie une trame déjà encodée (``AA55…77EE``)."""
        if not self._connected:
            raise ConnectionError("transport non connecté")
        self._log_line(f"TX {frame.hex()}")
        await self._write(frame)

    async def request(self, payload: bytes, predicate: Callable[[At2Packet], bool], timeout: float = 2.0) -> At2Packet | None:
        """Envoie ``payload`` et attend la réponse qui vérifie ``predicate``.

        L'écouteur est posé **avant** l'envoi : une réponse rapide ne peut pas être perdue
        entre l'envoi et l'attente. Retourne ``None`` au bout de ``timeout``.
        """
        fut: asyncio.Future[At2Packet] = asyncio.get_running_loop().create_future()

        def _listener(pkt: At2Packet) -> None:
            if not fut.done() and predicate(pkt):
                fut.set_result(pkt)

        self.on_packet(_listener)
        try:
            await self.send_payload(payload)
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self.off_packet(_listener)

    async def wait_for_packet(self, predicate: Callable[[At2Packet], bool], timeout: float = 2.0) -> At2Packet | None:
        """Attend le prochain paquet qui vérifie ``predicate``, ou ``None`` au bout de ``timeout``."""
        fut: asyncio.Future[At2Packet] = asyncio.get_running_loop().create_future()

        def _listener(pkt: At2Packet) -> None:
            if not fut.done() and predicate(pkt):
                fut.set_result(pkt)

        self.on_packet(_listener)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self.off_packet(_listener)
