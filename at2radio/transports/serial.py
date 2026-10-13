"""Transport USB série, 115200 bauds (nécessite ``pip install at2radio[serial]``).

Non officiel : l'application AT2 HT n'offre pas la liaison USB.
"""
from __future__ import annotations

import asyncio
import logging

from .base import Transport

logger = logging.getLogger("at2radio.transport.serial")

BAUD_RATE = 115200


def _serial():
    try:
        import serial
        import serial.tools.list_ports
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("le transport USB demande « pip install at2radio[serial] »") from e
    return serial


def list_ports() -> list[dict]:
    serial = _serial()
    return [{"path": p.device, "description": p.description, "hwid": p.hwid} for p in serial.tools.list_ports.comports()]


class SerialTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self._ser = None
        self._reader: asyncio.Task | None = None

    async def connect(self, target: str, **kwargs) -> None:
        serial = _serial()
        await self.disconnect()
        loop = asyncio.get_running_loop()
        baud = kwargs.get("baud_rate", BAUD_RATE)
        self._ser = await loop.run_in_executor(None, lambda: serial.Serial(target, baudrate=baud, timeout=0.1))
        self._connected = True
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while self._connected and self._ser is not None:
                data = await loop.run_in_executor(None, self._ser.read, 256)
                if data:
                    self._feed(data)
        except Exception:
            logger.exception("lecture série interrompue")
            if self._connected:
                self._lost()

    async def disconnect(self) -> None:
        self._connected = False
        if self._reader:
            self._reader.cancel()
            self._reader = None
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    async def _write(self, frame: bytes) -> None:
        assert self._ser is not None
        await asyncio.get_running_loop().run_in_executor(None, self._ser.write, frame)
