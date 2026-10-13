"""Registre des radios du service : une ``Radio`` par identifiant, événements diffusés aux abonnés."""
from __future__ import annotations

import asyncio
import base64
import dataclasses
from typing import Any

from ..radio import Message, PttVoice, Radio, RadioState
from ..transports.base import Transport
from .history import History

EVENTS = ("connection", "message", "state", "ptt_state", "frame")
MAX_SUBSCRIBER_QUEUE = 500


def to_json(obj: Any) -> Any:
    """Rend un événement sérialisable en JSON (les octets deviennent du base64)."""
    if isinstance(obj, PttVoice):
        return {"amr_frames": len(obj.amr_frames), "has_pcm": obj.pcm is not None}
    if dataclasses.is_dataclass(obj):
        return {k: to_json(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, (bytes, bytearray)):
        return base64.b64encode(bytes(obj)).decode()
    if isinstance(obj, tuple):
        return [to_json(v) for v in obj]
    return obj


class RadioManager:
    def __init__(self, history: History | None = None, max_radios: int = 16) -> None:
        self.history = history
        self.max_radios = max_radios
        self._radios: dict[str, Radio] = {}
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._wants_frames: set[asyncio.Queue] = set()

    def ids(self) -> list[str]:
        return sorted(self._radios)

    def get(self, radio_id: str) -> Radio:
        try:
            return self._radios[radio_id]
        except KeyError:
            raise KeyError(f"radio inconnue : {radio_id}") from None

    def get_or_create(self, radio_id: str) -> Radio:
        if radio_id in self._radios:
            return self._radios[radio_id]
        if len(self._radios) >= self.max_radios:
            raise ValueError(f"trop de radios (maximum {self.max_radios})")
        radio = Radio(radio_id)
        self._radios[radio_id] = radio
        self._subs[radio_id] = set()
        for name in EVENTS:
            radio.on(name, lambda *a, _n=name, _r=radio_id: self._publish(_r, _n, *a))
        radio.on("message", lambda m, _r=radio_id: self._store_incoming(_r, m))
        return radio

    async def remove(self, radio_id: str) -> None:
        radio = self.get(radio_id)
        await radio.disconnect()
        del self._radios[radio_id]
        self._subs.pop(radio_id, None)

    async def attach(self, radio_id: str, transport: Transport, target: str, kind: str, **kw) -> Radio:
        radio = self.get_or_create(radio_id)
        await radio.attach(transport, target, kind, **kw)
        return radio

    # -- événements ------------------------------------------------------

    def subscribe(self, radio_id: str, frames: bool = False) -> asyncio.Queue:
        """Abonné aux événements ; ``frames=True`` ajoute le journal des trames (diagnostic)."""
        self.get(radio_id)
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_SUBSCRIBER_QUEUE)
        self._subs[radio_id].add(q)
        if frames:
            self._wants_frames.add(q)
        return q

    def unsubscribe(self, radio_id: str, q: asyncio.Queue) -> None:
        self._subs.get(radio_id, set()).discard(q)
        self._wants_frames.discard(q)

    def _publish(self, radio_id: str, name: str, *args) -> None:
        event = {"event": name, "radio": radio_id, "data": to_json(args[0]) if args else None}
        for q in list(self._subs.get(radio_id, ())):
            if name == "frame" and q not in self._wants_frames:
                continue                           # trop verbeux : seulement sur demande
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self.unsubscribe(radio_id, q)      # abonné trop lent : on le coupe plutôt que de bloquer

    def _store_incoming(self, radio_id: str, m: Message) -> None:
        if self.history:
            self.history.add(radio_id, "in", m.type, m.sender, m.text, self._radios[radio_id].state.current_channel,
                             m.lat, m.lon, m.data)

    def state_of(self, radio_id: str) -> dict:
        r = self.get(radio_id)
        s: RadioState = r.state
        return {"id": radio_id, "status": r.status, "kind": r.kind, "target": r.target,
                "current_channel": s.current_channel, "dual_watch_channels": list(s.dual_watch_channels)}
