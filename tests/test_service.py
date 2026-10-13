"""Service HTTP/WebSocket, avec un faux transport."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from at2radio.protocole import messages, position
from at2radio.service import auth
from at2radio.service.app import create_app
from at2radio.service.history import History
from at2radio.service.manager import RadioManager

from test_radio import FakeTransport

KEY = "cle-de-test"
H = {"Authorization": f"Bearer {KEY}"}


@pytest.fixture
def env(tmp_path):
    manager = RadioManager(History(tmp_path / "h.db"))
    app = create_app(manager, KEY)
    with TestClient(app) as client:
        transport = FakeTransport()
        client.portal.call(manager.attach, "r1", transport, "fake", "ble")
        manager.get("r1").ACK_TIMEOUT = 0.1
        manager.get("r1").PACING = {"text": (0, 0), "voice": (0, 0), "image": (0, 0)}
        yield client, manager, transport


def test_cle_obligatoire(env):
    c, *_ = env
    assert c.get("/v1/health").status_code == 401
    assert c.get("/v1/health", headers={"Authorization": "Bearer faux"}).status_code == 401
    assert c.get("/v1/health", headers={"X-API-Key": KEY}).status_code == 200
    assert c.get("/v1/health", headers=H).json()["history"] is True


def test_sans_cle_configuree_acces_libre():
    with TestClient(create_app(RadioManager(), None)) as c:
        assert c.get("/v1/health").status_code == 200


def test_liste_et_statut(env):
    c, *_ = env
    r = c.get("/v1/radios", headers=H).json()
    assert r[0]["id"] == "r1" and r[0]["status"] == "connectée"
    assert c.get("/v1/radios/inconnue/status", headers=H).status_code == 404


def test_lecture_et_ecriture_de_canal(env):
    c, *_ = env
    assert c.get("/v1/radios/r1/channels/1", headers=H).json()["rx_mhz"] == pytest.approx(430.125)
    body = {"rx_mhz": 446.00625, "tx_mhz": 446.00625, "mode_digital": True, "encrypt_key": 2}
    res = c.put("/v1/radios/r1/channels/3", headers=H, json=body).json()
    assert res["verified"] is True and res["actual"]["encrypt_key"] == 2


def test_canal_invalide(env):
    c, *_ = env
    assert c.put("/v1/radios/r1/channels/3", headers=H, json={"rx_tone": "bidon"}).status_code == 400
    assert c.put("/v1/radios/r1/channels/3", headers=H, json={"encrypt_key": 99}).status_code == 422
    assert c.get("/v1/radios/r1/channels/99", headers=H).status_code == 400


def test_reglages(env):
    c, _, t = env
    assert c.get("/v1/radios/r1/settings/volume", headers=H).json()["value"] == 4
    assert c.put("/v1/radios/r1/settings/volume", headers=H, json={"value": 6}).status_code == 200
    assert t.sent[-1].body == bytes([0x01, 6])
    assert c.put("/v1/radios/r1/settings/volume", headers=H, json={"value": 99}).status_code == 400
    assert c.get("/v1/radios/r1/settings/inconnu", headers=H).status_code == 404
    assert c.put("/v1/radios/r1/settings/device_name", headers=H, json={"value": "AT2_X"}).status_code == 200
    assert c.put("/v1/radios/r1/settings/main_ptt_target", headers=H, json={"value": "inconnu"}).status_code == 400


def test_radio_muette_donne_504(env):
    c, m, t = env
    t.mute = True
    m.get("r1").QUERY_TIMEOUT = 0.05
    r = c.get("/v1/radios/r1/settings/volume", headers=H)
    assert r.status_code == 504 and r.json()["error"]["code"] == "radio_muette"


def test_radio_non_connectee_donne_409(env):
    c, m, _ = env
    m.get_or_create("r2")
    r = c.get("/v1/radios/r2/settings/volume", headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "radio_non_connectee"


def test_envoi_et_historique(env):
    c, *_ = env
    assert c.post("/v1/radios/r1/messages/text", headers=H, json={"sender": "ALPHA", "text": "Bonjour"}).status_code == 200
    assert c.post("/v1/radios/r1/messages/position", headers=H, json={"sender": "ALPHA", "lat": 48.85, "lon": 2.29}).status_code == 200
    assert c.post("/v1/radios/r1/messages/position", headers=H, json={"lat": 120, "lon": 2}).status_code == 422
    rows = c.get("/v1/radios/r1/messages", headers=H).json()
    assert [r["type"] for r in rows] == ["position", "text"] and rows[0]["direction"] == "out"


def test_message_recu_dans_historique_et_evenement(env):
    c, m, t = env
    with c.websocket_connect("/v1/radios/r1/events", headers=H) as ws:
        assert ws.receive_json()["event"] == "hello"
        for f in messages.build_text_message_frames("BRAVO", position.encode_sos("Perdu", 48.85, 2.3), 5):
            c.portal.call(lambda f=f: t._feed(f))
        ev = ws.receive_json()
        assert ev["event"] == "message" and ev["data"]["type"] == "sos" and ev["data"]["sender"] == "BRAVO"
    rows = c.get("/v1/radios/r1/messages", headers=H).json()
    assert rows[0]["direction"] == "in" and rows[0]["type"] == "sos"


def test_websocket_sans_cle_refuse(env):
    c, *_ = env
    with pytest.raises(Exception):
        with c.websocket_connect("/v1/radios/r1/events"):
            pass
    with c.websocket_connect(f"/v1/radios/r1/events?key={KEY}") as ws:
        assert ws.receive_json()["event"] == "hello"


def test_historique_desactive():
    m = RadioManager()
    with TestClient(create_app(m, None)) as c:
        c.portal.call(m.attach, "r1", FakeTransport(), "fake", "ble")
        assert c.get("/v1/radios/r1/messages").status_code == 501


def test_identifiant_de_radio_invalide(env):
    c, *_ = env
    r = c.post("/v1/radios/a%20b/connect", headers=H, json={"kind": "ble", "target": "AA"})
    assert r.status_code == 400


def test_xml_trop_gros(env):
    c, *_ = env
    assert c.post("/v1/cps-xml/parse", headers=H, content=b"x" * (5 * 1024 * 1024 + 1)).status_code == 400


def test_cle_creee_avec_droits_prives(tmp_path, monkeypatch):
    monkeypatch.delenv(auth.ENV_VAR, raising=False)
    path = tmp_path / "sub" / "api-key"
    key, created = auth.load_or_create_key(path)
    assert created and path.stat().st_mode & 0o777 == 0o600
    assert auth.load_or_create_key(path) == (key, False)


def test_ecoute_reseau_sans_cle_refusee():
    from at2radio.service.__main__ import main
    assert main(["--host", "0.0.0.0", "--no-key"]) == 2
