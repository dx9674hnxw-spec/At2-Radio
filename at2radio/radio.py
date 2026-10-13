"""La façade ``Radio`` : une instance = une radio. On peut en créer plusieurs.

Elle n'a ni état global, ni serveur web, ni base de données. Elle enchaîne
les trames, attend les réponses, vérifie les écritures et émet des événements.

Événements (``radio.on(nom, callback)``) :

* ``connection`` — ``str`` : ``"connectée"``, ``"déconnectée"``, ``"perdue"``
* ``message``    — :class:`Message` reçu (texte, position, SOS, voix, image)
* ``state``      — :class:`RadioState` quand la radio signale un changement (canal, Dual Watch)
* ``ptt_state``  — ``"rx"`` quelqu'un parle, ``"standby"`` silence
* ``ptt_voice``  — :class:`PttVoice` : trames AMR reçues (et PCM 8 kHz si le codec est disponible)
* ``frame``      — ``str`` : ligne de journal d'une trame émise (``TX``) ou reçue (``RX``)
* ``error``      — ``Exception`` survenue dans un écouteur ou en arrière-plan
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import count

from .errors import DeliveryError, NotConnectedError, RadioError, RadioTimeoutError
from .protocole import channel as chan
from .protocole import commands, messages, position, ptt
from .protocole.frame import At2Packet
from .transports.base import Transport

logger = logging.getLogger("at2radio")

_PTT_SILENCE_SECONDS = 0.6


@dataclass
class Message:
    """Un message reçu. ``sender`` est **déclaré par l'émetteur, jamais vérifié**."""

    type: str                       # "text", "position", "sos", "voice", "image"
    sender: str
    msg_id: int
    text: str | None = None
    lat: float | None = None
    lon: float | None = None
    data: bytes | None = None       # AMR (voix) ou JPEG (image)
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None


@dataclass
class RadioState:
    current_channel: int | None = None
    dual_watch_channels: tuple[int | None, int | None] = (None, None)


@dataclass
class PttVoice:
    amr_frames: list[bytes]
    pcm: bytes | None = None        # 8 kHz, 16 bits, mono ; None si le codec AMR n'est pas installé


@dataclass
class ChannelWriteResult:
    channel: int
    verified: bool                  # la relecture correspond à ce qui a été écrit
    expected: chan.ChannelConfig
    actual: chan.ChannelConfig | None
    differences: list[str] = field(default_factory=list)


def _differences(expected: chan.ChannelConfig, actual: chan.ChannelConfig) -> list[str]:
    out = []
    for name in ("rx_mhz", "tx_mhz"):
        a, b = getattr(expected, name), getattr(actual, name)
        if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-5):
            out.append(f"{name} : écrit {a}, relu {b}")
    for name in ("rx_tone", "tx_tone", "busy_lock", "bandwidth_narrow", "high_power", "scan_add",
                 "hop_on", "mode_digital", "encrypt_key"):
        a, b = getattr(expected, name), getattr(actual, name)
        if a != b:
            out.append(f"{name} : écrit {a}, relu {b}")
    return out


class Radio:
    ACK_TIMEOUT = 1.5
    ACK_RETRIES = 3
    ACK_BACKOFF = 0.22
    QUERY_TIMEOUT = 2.0
    # Cadence entre fragments, reprise de l'application officielle (At2ProtocolExecutor.kt).
    PACING = {"text": (0.36, 0.40), "voice": (0.35, 0.36), "image": (0.36, 0.40)}

    def __init__(self, radio_id: str | None = None) -> None:
        self.id = radio_id
        self.kind: str | None = None          # "ble" ou "serial"
        self.target: str | None = None
        self.state = RadioState()
        self._transport: Transport | None = None
        self._listeners: dict[str, list[Callable]] = defaultdict(list)
        self._msg_ids = count(1)
        self._ack_event = asyncio.Event()
        self._send_lock = asyncio.Lock()      # un seul message à la fois sur le fil
        self._cmd_lock = asyncio.Lock()       # une seule séquence requête/réponse à la fois
        self._assembler = messages.MessageAssembler()
        self._amr = None
        self._amr_tried = False
        self._silence_handle: asyncio.TimerHandle | None = None
        self._chat_open = False

    # -- événements ------------------------------------------------------

    def on(self, event: str, callback: Callable) -> None:
        self._listeners[event].append(callback)

    def off(self, event: str, callback: Callable) -> None:
        if callback in self._listeners[event]:
            self._listeners[event].remove(callback)

    def _emit(self, event: str, *args) -> None:
        for cb in list(self._listeners[event]):
            try:
                cb(*args)
            except Exception as exc:  # un écouteur ne doit jamais casser la radio
                logger.exception("écouteur %s en erreur", event)
                if event != "error":
                    self._emit("error", exc)

    # -- connexion -------------------------------------------------------

    @property
    def status(self) -> str:
        return "connectée" if self.connected else "déconnectée"

    @property
    def connected(self) -> bool:
        return bool(self._transport and self._transport.connected)

    async def connect_ble(self, address: str, timeout: float = 10.0) -> None:
        from .transports.ble import BleTransport
        await self.attach(BleTransport(), address, "ble", timeout=timeout)

    async def connect_serial(self, port: str, baud_rate: int = 115200) -> None:
        from .transports.serial import SerialTransport
        await self.attach(SerialTransport(), port, "serial", baud_rate=baud_rate)

    async def attach(self, transport: Transport, target: str, kind: str, **kwargs) -> None:
        """Connecte la radio sur un transport donné (utile aussi pour les tests)."""
        await self.disconnect()
        transport.on_packet(self._on_packet)
        transport.on_log(lambda line: self._emit("frame", line))
        transport.on_disconnect(self._on_lost)
        try:
            await transport.connect(target, **kwargs)
        except RadioError:
            raise
        except Exception as exc:
            raise RadioError(f"connexion impossible sur {target} : {exc}") from exc
        self._transport, self.kind, self.target = transport, kind, target
        self._emit("connection", "connectée")

    async def disconnect(self) -> None:
        t, self._transport = self._transport, None
        if t is not None:
            await t.disconnect()
            self._emit("connection", "déconnectée")
        self.kind = self.target = None
        self._chat_open = False

    def _on_lost(self) -> None:
        self._chat_open = False
        self._emit("connection", "perdue")

    def _require(self) -> Transport:
        if not self._transport or not self._transport.connected:
            raise NotConnectedError("aucune radio connectée")
        return self._transport

    # -- réception -------------------------------------------------------

    def _on_packet(self, pkt: At2Packet) -> None:
        if messages.is_message_ack(pkt.type, pkt.group, pkt.body):
            self._ack_event.set()
            return
        if ptt.is_ptt_voice_packet(pkt.type, pkt.group, pkt.body):
            self._on_ptt_voice(pkt)
            return
        self._track_state(pkt)
        done = self._assembler.feed(pkt)
        if done is not None:
            self._emit("message", self._to_message(done))

    def _track_state(self, pkt: At2Packet) -> None:
        # 81 02 0E 01 <canal> ... : canal courant, poussé par la radio
        if pkt.type == commands.TYPE_RESPONSE and pkt.group == commands.GROUP_RADIO and pkt.body[:1] == b"\x0e":
            b = pkt.body
            changed = False
            if len(b) >= 4 and b[1] == 0x01 and 1 <= b[2] <= 30:
                if self.state.current_channel != b[2]:
                    self.state.current_channel = b[2]
                    changed = True
            if len(b) >= 7 and b[1] == 0x01 and b[4] == 0x02:
                pair = (b[2] if 1 <= b[2] <= 30 else None, b[5] if 1 <= b[5] <= 30 else None)
                if pair != self.state.dual_watch_channels:
                    self.state.dual_watch_channels = pair
                    changed = True
            if changed:
                self._emit("state", self.state)

    @staticmethod
    def _to_message(done: messages.CompletedMessage) -> Message:
        if done.kind == "text":
            parsed = position.parse_position(done.text or "")
            if parsed:
                return Message(parsed.kind, done.sender, done.msg_id, text=parsed.message or None,
                               lat=parsed.lat, lon=parsed.lon)
            return Message("text", done.sender, done.msg_id, text=done.text)
        return Message(done.kind, done.sender, done.msg_id, data=done.data, duration_ms=done.duration_ms,
                       width=done.width, height=done.height)

    def _codec(self):
        if not self._amr_tried:
            self._amr_tried = True
            try:
                from .protocole.amr import AmrNbCodec
                self._amr = AmrNbCodec()
            except Exception:
                logger.info("codec AMR indisponible : les trames vocales sont livrées sans PCM")
        return self._amr

    def _on_ptt_voice(self, pkt: At2Packet) -> None:
        frames = ptt.extract_amr_frames(pkt.body)
        codec = self._codec()
        pcm = b"".join(codec.decode(f) for f in frames) if codec else None
        loop = asyncio.get_running_loop()
        if self._silence_handle is None:
            self._emit("ptt_state", "rx")
        else:
            self._silence_handle.cancel()
        self._silence_handle = loop.call_later(_PTT_SILENCE_SECONDS, self._ptt_silence)
        self._emit("ptt_voice", PttVoice(frames, pcm))

    def _ptt_silence(self) -> None:
        self._silence_handle = None
        self._emit("ptt_state", "standby")

    # -- réglages --------------------------------------------------------

    async def _query(self, payload: bytes, group: int, sub: int, min_len: int) -> At2Packet:
        t = self._require()
        async with self._cmd_lock:
            pkt = await t.request(
                payload,
                lambda p: p.type == commands.TYPE_RESPONSE and p.group == group
                and len(p.body) >= min_len and p.body[0] == sub,
                timeout=self.QUERY_TIMEOUT,
            )
        if pkt is None:
            raise RadioTimeoutError("la radio n'a pas répondu à cette requête (non prise en charge, ou radio muette)")
        return pkt

    async def get(self, name: str) -> int | bool:
        """Lit un réglage de ``commands.SETTINGS``. Voir ``Setting.status`` pour sa fiabilité."""
        s = commands.SETTINGS[name]
        if not s.queryable:
            raise RadioError(f"le réglage {name} ne peut pas être lu")
        pkt = await self._query(s.encode_query(), s.group, s.sub, 1 + s.width)
        return s.decode_value(int.from_bytes(pkt.body[1:1 + s.width], "little"))

    async def set(self, name: str, value: int | bool) -> None:
        """Écrit un réglage. Un accusé ne prouve pas que la radio l'a appliqué : relire avec ``get``."""
        await self._require().send_payload(commands.SETTINGS[name].encode_write(value))

    async def get_all(self) -> dict[str, int | bool | None]:
        """Lit tous les réglages ; ``None`` pour ceux qui ne répondent pas."""
        out: dict[str, int | bool | None] = {}
        for name in commands.SETTINGS:
            try:
                out[name] = await self.get(name)
            except RadioTimeoutError:
                out[name] = None
        return out

    async def set_device_name(self, name: str) -> None:
        await self._require().send_payload(commands.set_device_name(name))

    async def select_channel(self, channel: int) -> None:
        await self._require().send_payload(commands.select_channel(channel))

    async def select_dual_watch_channel(self, side: str, channel: int) -> None:
        await self._require().send_payload(commands.select_dual_watch_channel(side, channel))

    async def select_dual_watch_focus(self, side: str) -> None:
        await self._require().send_payload(commands.select_dual_watch_focus(side))

    async def set_main_ptt_target(self, target: str) -> None:
        await self._require().send_payload(commands.set_main_ptt_target(target))

    # -- canaux ----------------------------------------------------------

    async def read_channel(self, channel: int, timeout: float = 3.0) -> chan.ChannelConfig:
        t = self._require()
        def match(p: At2Packet) -> bool:
            cfg = chan.decode_channel_read_packet(p.type, p.group, p.body)
            return cfg is not None and cfg.channel == channel

        async with self._cmd_lock:
            pkt = await t.request(chan.build_channel_read_request(channel), match, timeout=timeout)
        if pkt is None:
            raise RadioTimeoutError(f"la radio n'a pas renvoyé le canal {channel}")
        return chan.decode_channel_read_packet(pkt.type, pkt.group, pkt.body)

    async def read_all_channels(self) -> list[chan.ChannelConfig]:
        return [await self.read_channel(n) for n in range(1, chan.CHANNEL_COUNT + 1)]

    async def write_channel(self, config: chan.ChannelConfig, verify: bool = True) -> ChannelWriteResult:
        """Écrit un canal, puis le relit et le compare (``verify``). L'écriture n'est
        pas confirmée par la radio : sans relecture, rien ne prouve qu'elle a été prise."""
        t = self._require()
        await t.send_payload(chan.build_channel_write_request(config))
        if not verify:
            return ChannelWriteResult(config.channel, False, config, None, ["non vérifié"])
        await asyncio.sleep(0.15)
        actual = await self.read_channel(config.channel)
        diffs = _differences(config, actual)
        return ChannelWriteResult(config.channel, not diffs, config, actual, diffs)

    async def write_all_channels(self, configs: list[chan.ChannelConfig], verify: bool = True) -> list[ChannelWriteResult]:
        return [await self.write_channel(c, verify) for c in configs]

    async def clear_channel(self, channel: int) -> None:
        t = self._require()
        await t.send_payload(commands.build_payload(commands.TYPE_WRITE, commands.GROUP_RADIO,
                                                    bytes([0x02]) + bytes(chan.empty_channel_record(channel))))

    # -- messages --------------------------------------------------------

    @property
    def chat_open(self) -> bool:
        return self._chat_open

    async def open_chat(self, disable_blocking_features: bool = False) -> None:
        """Ouvre la session de messagerie hors réseau (``CHAT SESSION ON`` de l'application officielle).

        Nécessaire pour envoyer **et** pour recevoir des messages. L'application officielle
        refuse de l'ouvrir tant que le **Dual Watch** ou **Smart Link** est activé ; ici, une erreur
        explicite est levée, sauf si ``disable_blocking_features=True`` (ils sont alors désactivés,
        sans être remis ensuite : voir ``close_chat``).
        """
        t = self._require()
        if self._chat_open:
            return
        for name, label in (("dual_watch", "Dual Watch"), ("smart_link", "Smart Link")):
            try:
                enabled = await self.get(name)
            except RadioTimeoutError:
                continue                                      # la radio ne répond pas : on suppose désactivé
            if enabled:
                if not disable_blocking_features:
                    raise RadioError(f"la messagerie hors réseau est impossible tant que {label} est activé "
                                     f"(comportement de l'application officielle) : désactive-le, ou appelle "
                                     f"open_chat(disable_blocking_features=True)")
                await self.set(name, False)
        await t.send_payload(ptt.build_offline_session_payload(True))
        self._chat_open = True
        await asyncio.sleep(0.3)

    async def close_chat(self) -> None:
        """Ferme la session de messagerie (``CHAT SESSION OFF``)."""
        if self._chat_open and self.connected:
            await self._transport.send_payload(ptt.build_offline_session_payload(False))
        self._chat_open = False

    async def send_text(self, sender: str, text: str) -> None:
        await self._send_frames("text", messages.build_text_message_frames(sender, text, next(self._msg_ids)))

    async def send_position(self, sender: str, lat: float, lon: float) -> None:
        await self.send_text(sender, position.encode_position(lat, lon))

    async def send_sos(self, sender: str, lat: float, lon: float, message: str = position.DEFAULT_HELP_PRESETS[0]) -> None:
        await self.send_text(sender, position.encode_sos(message, lat, lon))

    async def send_voice(self, sender: str, pcm_8khz: bytes, duration_ms: int) -> None:
        """Message vocal différé (distinct du PTT). ``pcm_8khz`` : 16 bits, mono, 8 kHz."""
        if not (messages.MIN_VOICE_DURATION_MS <= duration_ms <= messages.MAX_VOICE_DURATION_MS):
            raise ValueError(f"durée hors limites ({messages.MIN_VOICE_DURATION_MS}..{messages.MAX_VOICE_DURATION_MS} ms)")
        from .protocole.amr import FRAME_BYTES_PCM, AmrNbCodec
        with AmrNbCodec() as codec:
            encoded = bytearray()
            for i in range(0, len(pcm_8khz) - FRAME_BYTES_PCM + 1, FRAME_BYTES_PCM):
                frame = codec.encode(pcm_8khz[i:i + FRAME_BYTES_PCM])
                if frame:
                    encoded += frame
        if not encoded:
            raise ValueError("aucun son à envoyer (enregistrement trop court ?)")
        await self._send_frames("voice", messages.build_voice_message_frames(sender, bytes(encoded), duration_ms, next(self._msg_ids)))

    async def send_image(self, sender: str, jpeg: bytes, width: int, height: int) -> None:
        """Image déjà réduite (300 px au plus, JPEG qualité 75). ``width`` et ``height`` :
        dimensions de l'image d'origine après rotation, comme l'application officielle."""
        await self._send_frames("image", messages.build_image_message_frames(sender, jpeg, width, height, next(self._msg_ids)))

    async def _send_frames(self, kind: str, frames: list[bytes]) -> None:
        t = self._require()
        await self.open_chat()
        first_delay, period = self.PACING[kind]
        async with self._send_lock:
            loop = asyncio.get_running_loop()
            next_at: float | None = None
            for index, frame in enumerate(frames):
                if index >= 1 and next_at is not None and (wait := next_at - loop.time()) > 0:
                    await asyncio.sleep(wait)
                for attempt in range(1, self.ACK_RETRIES + 1):
                    self._ack_event.clear()
                    await t.send_raw_frame(frame)
                    try:
                        await asyncio.wait_for(self._ack_event.wait(), timeout=self.ACK_TIMEOUT)
                        break
                    except asyncio.TimeoutError:
                        if attempt == self.ACK_RETRIES:
                            raise DeliveryError(
                                f"pas d'accusé de la radio pour la trame {index + 1}/{len(frames)} "
                                f"après {self.ACK_RETRIES} tentatives") from None
                        await asyncio.sleep(self.ACK_BACKOFF)
                next_at = loop.time() + first_delay if index == 0 else (next_at + period if next_at else None)

    # -- PTT -------------------------------------------------------------

    def ptt_session(self, preflight: bool = True) -> "PttSession":
        """Session d'émission : ``async with radio.ptt_session() as s: await s.feed(pcm_320_octets)``.

        L'émission n'a lieu que dans ce bloc, jamais par effet de bord.
        """
        return PttSession(self._require(), preflight)


class PttSession:
    """Une émission PTT : encode des trames PCM de 20 ms et les envoie par paquets de 100 ms."""

    def __init__(self, transport: Transport, preflight: bool) -> None:
        self._t = transport
        self._preflight = preflight
        self._pending: list[bytes] = []
        self._last = 0.0
        self._codec = None

    async def __aenter__(self) -> "PttSession":
        from .protocole.amr import AmrNbCodec
        self._codec = AmrNbCodec()
        if self._preflight:
            for payload in ptt.preflight_payloads():
                await self._t.send_payload(payload)
        else:
            await self._t.send_payload(ptt.build_offline_session_payload(True))
        await self._t.send_payload(ptt.build_ptt_key_payload(True))
        await asyncio.sleep(0.02)
        return self

    async def feed(self, pcm_320_bytes: bytes) -> None:
        """Une trame de 20 ms : exactement 320 octets (160 échantillons 16 bits mono, 8 kHz)."""
        enc = self._codec.encode(pcm_320_bytes)
        if enc is None:
            return
        self._pending.append(enc)
        if len(self._pending) >= ptt.FRAMES_PER_PACKET:
            await self._flush(ptt.FRAMES_PER_PACKET)

    async def _flush(self, n: int) -> None:
        chunk, self._pending = self._pending[:n], self._pending[n:]
        loop = asyncio.get_running_loop()
        gap = loop.time() - self._last
        if self._last and gap < ptt.PACKET_PACING_SECONDS:
            await asyncio.sleep(ptt.PACKET_PACING_SECONDS - gap)
        self._last = loop.time()
        await self._t.send_payload(ptt.build_ptt_voice_payload(chunk))

    async def __aexit__(self, *exc) -> None:
        try:
            if len(self._pending) >= ptt.TAIL_MIN_FRAMES:
                await self._flush(len(self._pending))
            await self._t.send_payload(ptt.build_ptt_key_payload(False))
        finally:
            if self._codec:
                self._codec.close()
