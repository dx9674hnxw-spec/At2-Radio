"""``Radio`` sur un faux transport : aucune radio ni Bluetooth nécessaire."""
import asyncio

import pytest

from at2radio import DeliveryError, NotConnectedError, Radio, RadioTimeoutError
from at2radio.protocole import channel as chan
from at2radio.protocole import messages, position
from at2radio.protocole.frame import decode_packet, encode_frame, try_decode_frame
from at2radio.transports.base import Transport

CH1_BODY = bytes.fromhex("0101009451900294519002000000000000010001010000" + "00")


class FakeTransport(Transport):
    """Imite une radio : répond aux requêtes, mémorise les canaux, acquitte les messages."""

    def __init__(self, drop_acks=0, mute=False):
        super().__init__()
        self.sent = []
        self.drop_acks = drop_acks
        self.mute = mute
        self.settings = {(0x01, 0x01): 4, (0x02, 0x05): 120, (0x02, 0x0D): 2}
        self.channels = {1: CH1_BODY}

    async def connect(self, target, **kwargs):
        self._connected = True

    async def disconnect(self):
        self._connected = False

    def push(self, type_, group, body):
        self._feed(encode_frame(bytes([0x00, type_, group]) + body))

    async def _write(self, frame):
        payload, _ = try_decode_frame(frame)
        pkt = decode_packet(payload)
        self.sent.append(pkt)
        if self.mute:
            return
        t, g, b = pkt.type, pkt.group, pkt.body
        if t == 0x01 and b and (g, b[0]) in self.settings:
            width = 2 if (g, b[0]) == (0x02, 0x05) else 1
            self.push(0x81, g, bytes([b[0]]) + self.settings[(g, b[0])].to_bytes(width, "little"))
        elif t == 0x11:
            ch = int.from_bytes(b[2:4], "little")
            if ch in self.channels:
                self.push(0x91, 0x02, b"\x02" + self.channels[ch])
        elif t == 0x12:
            fields = b[2:]                                   # après « 02 00 »
            ch = int.from_bytes(fields[0:2], "little")
            self.channels[ch] = b"\x01" + fields             # lecture = marqueur 01 + les 23 octets
        elif t == 0x02 and g == 0x04 and b[:1] == b"\x01":
            if self.drop_acks > 0:
                self.drop_acks -= 1
            else:
                self.push(0x82, 0x04, b"\x01\x00")


def run(coro):
    return asyncio.run(coro)


async def connected(**kw):
    r = Radio("test")
    t = FakeTransport(**kw)
    await r.attach(t, "fake", "ble")
    return r, t


def test_non_connectee():
    r = Radio()
    with pytest.raises(NotConnectedError):
        run(r.get("volume"))


def test_get_et_set():
    async def go():
        r, t = await connected()
        assert await r.get("volume") == 4
        assert await r.get("tot_seconds") == 120
        assert await r.get("dual_watch") is True
        await r.set("volume", 6)
        assert t.sent[-1].body == bytes([0x01, 6])
        with pytest.raises(ValueError):
            await r.set("volume", 9)
    run(go())


def test_reglage_sans_reponse():
    async def go():
        r, t = await connected()
        r.QUERY_TIMEOUT = 0.05
        with pytest.raises(RadioTimeoutError):
            await r.get("smart_link")
    run(go())


def test_lecture_de_canal():
    async def go():
        r, _ = await connected()
        cfg = await r.read_channel(1)
        assert cfg.channel == 1 and cfg.rx_mhz == pytest.approx(430.125) and cfg.rx_tone == "67.0Hz"
    run(go())


def test_ecriture_verifiee():
    async def go():
        r, _ = await connected()
        cfg = chan.ChannelConfig(channel=3, rx_mhz=446.00625, tx_mhz=446.00625, mode_digital=True, encrypt_key=2)
        res = await r.write_channel(cfg)
        assert res.verified and not res.differences
        assert res.actual.encrypt_key == 2
    run(go())


def test_ecriture_non_prise_est_detectee():
    async def go():
        r, t = await connected()
        orig = t._write

        async def ignore_writes(frame):               # la radio acquitte mais n'applique rien
            payload, _ = try_decode_frame(frame)
            if decode_packet(payload).type != 0x12:
                await orig(frame)
        t._write = ignore_writes
        t.channels[3] = CH1_BODY[:1] + (3).to_bytes(2, "little") + CH1_BODY[3:]
        res = await r.write_channel(chan.ChannelConfig(channel=3, rx_mhz=446.0, tx_mhz=446.0))
        assert not res.verified and any("rx_mhz" in d for d in res.differences)
    run(go())


def test_envoi_de_texte_acquitte():
    async def go():
        r, t = await connected()
        r.PACING = {"text": (0, 0), "voice": (0, 0), "image": (0, 0)}
        await r.send_text("ALPHA", "a" * 300)          # fragmenté : début + 3 fragments
        envoyes = [p for p in t.sent if p.type == 0x02 and p.group == 0x04]
        assert len(envoyes) == 4
    run(go())


def test_envoi_perdu_puis_repris():
    async def go():
        r, t = await connected(drop_acks=1)
        r.ACK_TIMEOUT, r.ACK_BACKOFF = 0.05, 0
        await r.send_text("ALPHA", "Bonjour")
        assert len([p for p in t.sent if p.group == 0x04]) == 2   # une répétition
    run(go())


def test_envoi_sans_accuse_leve_une_erreur():
    async def go():
        r, t = await connected(drop_acks=99)
        r.ACK_TIMEOUT, r.ACK_BACKOFF = 0.02, 0
        with pytest.raises(DeliveryError):
            await r.send_text("ALPHA", "Bonjour")
    run(go())


def test_texte_trop_long_refuse():
    async def go():
        r, _ = await connected()
        with pytest.raises(ValueError):
            await r.send_text("ALPHA", "a" * 1001)
    run(go())


def test_reception_texte_position_et_sos():
    async def go():
        r, t = await connected()
        recus = []
        r.on("message", recus.append)
        for i, texte in enumerate(["Bonjour", position.encode_position(48.8584, 2.2945),
                                   position.encode_sos("Perdu", 48.85, 2.3)], start=1):
            for f in messages.build_text_message_frames("BRAVO", texte, i):
                t._feed(f)
        assert [m.type for m in recus] == ["text", "position", "sos"]
        assert recus[1].lat == pytest.approx(48.8584) and recus[2].text == "Perdu"
        assert all(m.sender == "BRAVO" for m in recus)
    run(go())


def test_etat_pousse_par_la_radio():
    async def go():
        r, t = await connected()
        etats = []
        r.on("state", etats.append)
        t.push(0x81, 0x02, bytes([0x0E, 0x01, 7, 0x00]))
        assert r.state.current_channel == 7 and len(etats) == 1
        t.push(0x81, 0x02, bytes([0x0E, 0x01, 7, 0x00]))      # inchangé : pas de nouvel événement
        assert len(etats) == 1
    run(go())


def test_voix_ptt_recue_sans_codec(monkeypatch):
    async def go():
        r, t = await connected()
        r._amr_tried = True                                   # codec indisponible
        voix, etats = [], []
        r.on("ptt_voice", voix.append)
        r.on("ptt_state", etats.append)
        t.push(0x02, 0x04, bytes([0x03, 0x00, 0x00]) + bytes(60))
        assert len(voix[0].amr_frames) == 5 and voix[0].pcm is None and etats == ["rx"]
        await asyncio.sleep(0.7)
        assert etats == ["rx", "standby"]
    run(go())


def test_deux_radios_independantes():
    async def go():
        a, ta = await connected()
        b, tb = await connected()
        await a.set("volume", 2)
        assert ta.sent and not tb.sent
    run(go())


def test_perte_de_lien_signalee():
    async def go():
        r, t = await connected()
        etats = []
        r.on("connection", etats.append)
        t._lost()
        assert etats == ["perdue"] and not r.connected
    run(go())
