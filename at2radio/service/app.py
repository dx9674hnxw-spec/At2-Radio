"""Service HTTP + WebSocket (API v1) au-dessus de la bibliothèque. Voir docs/CONTRAT.md §5."""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from pathlib import Path
from typing import Annotated

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..errors import DeliveryError, NotConnectedError, RadioError, RadioTimeoutError
from ..protocole import channel as chan
from ..protocole import commands, position
from . import auth
from .manager import RadioManager, to_json

logger = logging.getLogger("at2radio.service")
STATIC = Path(__file__).parent / "static"

MAX_XML_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 64 * 1024
MAX_VOICE_BYTES = 16_000 * 16        # 16 s de PCM 8 kHz 16 bits


# -- modèles -------------------------------------------------------------

class ConnectIn(BaseModel):
    kind: str = Field(pattern="^(ble|serial)$")
    target: str = Field(min_length=1, max_length=200)
    baud_rate: int = 115200


class ChannelIn(BaseModel):
    channel: int | None = Field(None, ge=1, le=30)
    rx_mhz: float | None = Field(None, ge=0)
    tx_mhz: float | None = Field(None, ge=0)
    rx_tone: str = "OFF"
    tx_tone: str = "OFF"
    busy_lock: bool = False
    bandwidth_narrow: bool = True
    high_power: bool = True
    scan_add: bool = True
    hop_on: bool = False
    mode_digital: bool = False
    encrypt_key: int = Field(0, ge=0, le=31)

    def to_config(self, channel: int) -> chan.ChannelConfig:
        for tone in (self.rx_tone, self.tx_tone):
            chan.parse_tone_label(tone)                    # ValueError si inconnue
        data = self.model_dump(exclude={"channel"})
        return chan.ChannelConfig(channel=channel, **data)


class SettingIn(BaseModel):
    value: int | bool | str


class TextIn(BaseModel):
    sender: str = Field("At2Radio", max_length=16)
    text: str = Field(min_length=1, max_length=2000)


class PositionIn(BaseModel):
    sender: str = Field("At2Radio", max_length=16)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class SosIn(PositionIn):
    message: str = Field(position.DEFAULT_HELP_PRESETS[0], max_length=800)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(manager: RadioManager | None = None, api_key: str | None = None, cors_origins: list[str] | None = None) -> FastAPI:
    """``api_key=None`` : pas d'authentification (réservé à l'écoute locale, voir ``__main__``)."""
    manager = manager or RadioManager()
    app = FastAPI(title="At2-Radio", version=__version__, docs_url="/v1/docs", openapi_url="/v1/openapi.json")
    app.state.manager = manager

    if cors_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"], allow_headers=["*"])

    # -- erreurs : jamais de trace interne dans la réponse ---------------
    @app.exception_handler(NotConnectedError)
    async def _nc(_r, e): return _error(409, "radio_non_connectee", str(e))

    @app.exception_handler(RadioTimeoutError)
    async def _to(_r, e): return _error(504, "radio_muette", str(e))

    @app.exception_handler(DeliveryError)
    async def _de(_r, e): return _error(502, "message_non_acquitte", str(e))

    @app.exception_handler(RadioError)
    async def _re(_r, e): return _error(502, "erreur_radio", str(e))

    @app.exception_handler(KeyError)
    async def _ke(_r, e): return _error(404, "introuvable", str(e.args[0]) if e.args else "introuvable")

    @app.exception_handler(ValueError)
    async def _ve(_r, e): return _error(400, "valeur_invalide", str(e))

    @app.exception_handler(HTTPException)
    async def _http(_r, e): return _error(e.status_code, "erreur_http", str(e.detail))

    @app.exception_handler(Exception)
    async def _any(_r, e):
        logger.exception("erreur interne")
        return _error(500, "erreur_interne", "erreur interne du service")

    async def require_key(authorization: Annotated[str | None, Header()] = None,
                          x_api_key: Annotated[str | None, Header()] = None) -> None:
        if not auth.check(api_key, auth.bearer(authorization) or x_api_key):
            raise HTTPException(401, "clé d'API manquante ou invalide")

    secured = [Depends(require_key)]

    def radio_of(radio_id: str):
        return manager.get(radio_id)

    # -- général ---------------------------------------------------------
    @app.get("/v1/health", dependencies=secured)
    async def health():
        return {"version": __version__, "radios": len(manager.ids()), "history": manager.history is not None}

    @app.get("/v1/radios", dependencies=secured)
    async def list_radios():
        return [manager.state_of(i) for i in manager.ids()]

    @app.post("/v1/ble/scan", dependencies=secured)
    async def ble_scan(timeout: float = Query(5.0, ge=1, le=30)):
        from ..transports import ble
        return await ble.scan(timeout)

    @app.get("/v1/serial/ports", dependencies=secured)
    async def serial_ports():
        from ..transports import serial
        return serial.list_ports()

    @app.get("/v1/tones", dependencies=secured)
    async def tones():
        return chan.tone_options()

    @app.get("/v1/settings-spec", dependencies=secured)
    async def settings_spec():
        return {n: {"low": s.low, "high": s.high, "bool": s.is_bool, "status": s.status, "queryable": s.queryable}
                for n, s in commands.SETTINGS.items()}

    @app.post("/v1/cps-xml/parse", dependencies=secured)
    async def parse_xml(request: Request):
        raw = await request.body()
        if len(raw) > MAX_XML_BYTES:
            raise ValueError("fichier XML trop volumineux")
        return [dataclasses.asdict(c) for c in chan.parse_cps_xml(raw)]

    # -- connexion -------------------------------------------------------
    @app.post("/v1/radios/{radio_id}/connect", dependencies=secured)
    async def connect(radio_id: str, body: ConnectIn):
        if not radio_id.replace("-", "").replace("_", "").isalnum() or len(radio_id) > 40:
            raise ValueError("identifiant de radio invalide (lettres, chiffres, - et _, 40 caractères au plus)")
        radio = manager.get_or_create(radio_id)
        if body.kind == "ble":
            await radio.connect_ble(body.target)
        else:
            await radio.connect_serial(body.target, body.baud_rate)
        return manager.state_of(radio_id)

    @app.post("/v1/radios/{radio_id}/disconnect", dependencies=secured)
    async def disconnect(radio_id: str):
        await radio_of(radio_id).disconnect()
        return manager.state_of(radio_id)

    @app.delete("/v1/radios/{radio_id}", dependencies=secured, status_code=204)
    async def remove(radio_id: str):
        await manager.remove(radio_id)

    @app.get("/v1/radios/{radio_id}/status", dependencies=secured)
    async def status(radio_id: str):
        radio_of(radio_id)
        return manager.state_of(radio_id)

    # -- canaux ----------------------------------------------------------
    @app.get("/v1/radios/{radio_id}/channels", dependencies=secured)
    async def read_channels(radio_id: str):
        return [dataclasses.asdict(c) for c in await radio_of(radio_id).read_all_channels()]

    @app.get("/v1/radios/{radio_id}/channels/{n}", dependencies=secured)
    async def read_channel(radio_id: str, n: int):
        return dataclasses.asdict(await radio_of(radio_id).read_channel(n))

    @app.put("/v1/radios/{radio_id}/channels/{n}", dependencies=secured)
    async def write_channel(radio_id: str, n: int, body: ChannelIn, verify: bool = True):
        res = await radio_of(radio_id).write_channel(body.to_config(n), verify)
        return {"channel": res.channel, "verified": res.verified, "differences": res.differences,
                "actual": dataclasses.asdict(res.actual) if res.actual else None}

    @app.put("/v1/radios/{radio_id}/channels", dependencies=secured)
    async def write_channels(radio_id: str, body: Annotated[list[ChannelIn], Body(min_length=1, max_length=30)], verify: bool = True):
        configs = []
        for i, c in enumerate(body, start=1):
            configs.append(c.to_config(c.channel or i))
        results = await radio_of(radio_id).write_all_channels(configs, verify)
        return [{"channel": r.channel, "verified": r.verified, "differences": r.differences} for r in results]

    @app.delete("/v1/radios/{radio_id}/channels/{n}", dependencies=secured, status_code=204)
    async def clear_channel(radio_id: str, n: int):
        await radio_of(radio_id).clear_channel(n)

    @app.post("/v1/radios/{radio_id}/channels/{n}/select", dependencies=secured)
    async def select_channel(radio_id: str, n: int):
        await radio_of(radio_id).select_channel(n)
        return {"selected": n}

    # -- réglages --------------------------------------------------------
    @app.get("/v1/radios/{radio_id}/settings", dependencies=secured)
    async def get_settings(radio_id: str):
        return await radio_of(radio_id).get_all()

    @app.get("/v1/radios/{radio_id}/settings/{name}", dependencies=secured)
    async def get_setting(radio_id: str, name: str):
        if name not in commands.SETTINGS:
            raise KeyError(f"réglage inconnu : {name}")
        return {"name": name, "value": await radio_of(radio_id).get(name)}

    @app.put("/v1/radios/{radio_id}/settings/{name}", dependencies=secured)
    async def put_setting(radio_id: str, name: str, body: SettingIn):
        radio = radio_of(radio_id)
        if name == "device_name":
            await radio.set_device_name(str(body.value))
        elif name == "main_ptt_target":
            if str(body.value) not in commands.MAIN_PTT_TARGETS:
                raise ValueError(f"cible inconnue ; valeurs : {', '.join(commands.MAIN_PTT_TARGETS)}")
            await radio.set_main_ptt_target(str(body.value))
        elif name in commands.SETTINGS:
            if isinstance(body.value, str):
                raise ValueError("valeur numérique ou booléenne attendue")
            await radio.set(name, body.value)
        else:
            raise KeyError(f"réglage inconnu : {name}")
        return {"name": name, "value": body.value, "note": "un accusé ne prouve pas l'application ; relire avec GET"}

    @app.put("/v1/radios/{radio_id}/dual-watch", dependencies=secured)
    async def dual_watch(radio_id: str, side: str = Query(pattern="^[AB]$"), channel: int | None = Query(None, ge=1, le=30),
                         focus: bool = False):
        radio = radio_of(radio_id)
        if focus:
            await radio.select_dual_watch_focus(side)
        elif channel is not None:
            await radio.select_dual_watch_channel(side, channel)
        else:
            raise ValueError("indiquer channel ou focus=true")
        return {"side": side, "channel": channel, "focus": focus}

    # -- messagerie : session hors réseau ----------------------------------
    @app.post("/v1/radios/{radio_id}/chat/open", dependencies=secured)
    async def chat_open(radio_id: str, disable_blocking_features: bool = False):
        """Ouvre la session de messagerie (nécessaire pour envoyer et recevoir). Refusée si le Dual Watch
        ou Smart Link est activé, sauf ``disable_blocking_features=true``."""
        await radio_of(radio_id).open_chat(disable_blocking_features)
        return {"chat_open": True}

    @app.post("/v1/radios/{radio_id}/chat/close", dependencies=secured)
    async def chat_close(radio_id: str):
        await radio_of(radio_id).close_chat()
        return {"chat_open": False}

    # -- messages --------------------------------------------------------
    def _log_out(radio_id, type_, sender, text=None, lat=None, lon=None, blob=None):
        if manager.history:
            manager.history.add(radio_id, "out", type_, sender, text, manager.get(radio_id).state.current_channel,
                                lat, lon, blob, delivery="acked")

    @app.post("/v1/radios/{radio_id}/messages/text", dependencies=secured)
    async def send_text(radio_id: str, body: TextIn):
        await radio_of(radio_id).send_text(body.sender, body.text)
        _log_out(radio_id, "text", body.sender, body.text)
        return {"sent": True}

    @app.post("/v1/radios/{radio_id}/messages/position", dependencies=secured)
    async def send_position(radio_id: str, body: PositionIn):
        await radio_of(radio_id).send_position(body.sender, body.lat, body.lon)
        _log_out(radio_id, "position", body.sender, None, body.lat, body.lon)
        return {"sent": True}

    @app.post("/v1/radios/{radio_id}/messages/sos", dependencies=secured)
    async def send_sos(radio_id: str, body: SosIn):
        await radio_of(radio_id).send_sos(body.sender, body.lat, body.lon, body.message)
        _log_out(radio_id, "sos", body.sender, body.message, body.lat, body.lon)
        return {"sent": True}

    @app.post("/v1/radios/{radio_id}/messages/voice", dependencies=secured)
    async def send_voice(radio_id: str, request: Request, sender: str = Query("At2Radio", max_length=16),
                         duration_ms: int = Query(ge=600, le=15000)):
        """Corps : PCM 16 bits mono 8 kHz (``application/octet-stream``). **Expérimental.**"""
        pcm = await request.body()
        if not pcm or len(pcm) > MAX_VOICE_BYTES:
            raise ValueError("audio vide ou trop long")
        await radio_of(radio_id).send_voice(sender, pcm, duration_ms)
        _log_out(radio_id, "voice", sender, blob=pcm)
        return {"sent": True, "experimental": True}

    @app.post("/v1/radios/{radio_id}/messages/image", dependencies=secured)
    async def send_image(radio_id: str, request: Request, sender: str = Query("At2Radio", max_length=16),
                         width: int = Query(ge=1, le=65535), height: int = Query(ge=1, le=65535)):
        """Corps : JPEG déjà réduit (300 px au plus). **Expérimental.**"""
        jpeg = await request.body()
        if not jpeg or len(jpeg) > MAX_IMAGE_BYTES:
            raise ValueError("image vide ou trop volumineuse (64 Ko au plus, réduire à 300 px)")
        await radio_of(radio_id).send_image(sender, jpeg, width, height)
        _log_out(radio_id, "image", sender, blob=jpeg)
        return {"sent": True, "experimental": True}

    @app.get("/v1/radios/{radio_id}/messages", dependencies=secured)
    async def list_messages(radio_id: str, limit: int = Query(100, ge=1, le=500), before_id: int | None = None):
        radio_of(radio_id)
        if not manager.history:
            return JSONResponse(status_code=501, content={"error": {"code": "historique_desactive",
                                "message": "historique désactivé (lancer le service avec --history FICHIER)"}})
        return manager.history.list(radio_id, limit, before_id)

    # -- WebSocket -------------------------------------------------------
    async def _ws_auth(ws: WebSocket) -> bool:
        given = auth.bearer(ws.headers.get("authorization")) or ws.headers.get("x-api-key") or ws.query_params.get("key")
        if not auth.check(api_key, given):
            await ws.close(code=4401)
            return False
        return True

    @app.websocket("/v1/radios/{radio_id}/events")
    async def events(ws: WebSocket, radio_id: str, frames: bool = False):
        if not await _ws_auth(ws):
            return
        try:
            manager.get(radio_id)
        except KeyError:
            await ws.close(code=4404)
            return
        await ws.accept()
        q = manager.subscribe(radio_id, frames)
        try:
            await ws.send_json({"event": "hello", "radio": radio_id, "data": manager.state_of(radio_id)})
            while True:
                send = asyncio.create_task(q.get())
                recv = asyncio.create_task(ws.receive_text())
                done, pending = await asyncio.wait({send, recv}, return_when=asyncio.FIRST_COMPLETED)
                for p in pending:
                    p.cancel()
                if recv in done and recv.exception() is not None:
                    break
                if send in done:
                    await ws.send_json(send.result())
        except WebSocketDisconnect:
            pass
        finally:
            manager.unsubscribe(radio_id, q)

    @app.websocket("/v1/radios/{radio_id}/ptt")
    async def ptt(ws: WebSocket, radio_id: str, preflight: bool = True):
        """Octets binaires : PCM 8 kHz 16 bits mono, trames de 320 octets, dans les deux sens.
        L'émission dure tant que la connexion est ouverte. Nécessite libopencore-amrnb."""
        if not await _ws_auth(ws):
            return
        try:
            radio = manager.get(radio_id)
        except KeyError:
            await ws.close(code=4404)
            return
        await ws.accept()
        loop = asyncio.get_running_loop()
        outgoing: asyncio.Queue = asyncio.Queue(maxsize=200)

        def on_voice(v):
            if v.pcm is not None:
                loop.call_soon(lambda: outgoing.full() or outgoing.put_nowait(v.pcm))
        radio.on("ptt_voice", on_voice)
        pump = asyncio.create_task(_pump(ws, outgoing))
        try:
            async with radio.ptt_session(preflight) as session:
                while True:
                    data = await ws.receive_bytes()
                    if len(data) != 320:
                        await ws.close(code=1003, reason="trames de 320 octets attendues")
                        break
                    await session.feed(data)
        except (WebSocketDisconnect, NotConnectedError):
            pass
        except Exception as exc:                # codec absent, radio perdue…
            logger.warning("session PTT interrompue : %s", exc)
            await ws.close(code=1011, reason="session PTT impossible")
        finally:
            radio.off("ptt_voice", on_voice)
            pump.cancel()

    async def _pump(ws: WebSocket, q: asyncio.Queue):
        while True:
            await ws.send_bytes(await q.get())

    # -- page de programmation ------------------------------------------
    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return app
