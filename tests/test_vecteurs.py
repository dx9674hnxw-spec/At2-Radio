"""Conformité aux vecteurs de ``vecteurs/*.json`` : toute implémentation doit les reproduire."""
import json
from pathlib import Path

import pytest

from at2radio.protocole import channel as chan
from at2radio.protocole import commands, messages, ptt
from at2radio.protocole.frame import crc16_ccitt, decode_packet, encode_frame, try_decode_frame

V = Path(__file__).resolve().parent.parent / "vecteurs"


def load(name):
    return json.loads((V / f"{name}.json").read_text())["vecteurs"]


@pytest.mark.parametrize("v", load("crc16"), ids=lambda v: v["nom"])
def test_crc16(v):
    assert crc16_ccitt(bytes.fromhex(v["entree_hex"])) == v["attendu_crc16"]


@pytest.mark.parametrize("v", load("trames_classiques") + load("trames_canal") + load("commandes") + load("ptt"), ids=lambda v: v["nom"])
def test_trame_et_charge(v):
    payload = bytes.fromhex(v["charge_hex"])
    assert encode_frame(payload).hex() == v["trame_hex"]
    decoded, consumed = try_decode_frame(bytes.fromhex(v["trame_hex"]))
    assert decoded == payload and consumed == len(v["trame_hex"]) // 2


def _setting_payload(nom):
    table = {
        "volume 4": lambda: commands.SETTINGS["volume"].encode_write(4),
        "squelch 3": lambda: commands.SETTINGS["squelch"].encode_write(3),
        "temporisation 120 s": lambda: commands.SETTINGS["tot_seconds"].encode_write(120),
        "VOX activé": lambda: commands.SETTINGS["vox"].encode_write(True),
        "sensibilité VOX 3": lambda: commands.SETTINGS["vox_sensitivity"].encode_write(3),
        "inhibition TX activée": lambda: commands.SETTINGS["tx_inhibit"].encode_write(True),
        "intervalle TX 60 s": lambda: commands.SETTINGS["tx_interval_seconds"].encode_write(60),
        "réduction de bruit activée": lambda: commands.SETTINGS["noise_reduction"].encode_write(True),
        "annonces en anglais": lambda: commands.SETTINGS["prompt_language"].encode_write(True),
        "tonalité activée": lambda: commands.SETTINGS["prompt_tone"].encode_write(True),
        "Smart Link activé": lambda: commands.SETTINGS["smart_link"].encode_write(True),
        "Dual Watch activé": lambda: commands.SETTINGS["dual_watch"].encode_write(True),
        "Dual Watch désactivé": lambda: commands.SETTINGS["dual_watch"].encode_write(False),
        "canal 5 (selectChannel)": lambda: commands.select_channel(5),
        "Dual Watch côté B canal 7": lambda: commands.select_dual_watch_channel("B", 7),
        "focus Dual Watch côté A": lambda: commands.select_dual_watch_focus("A"),
        "nom AT2_TEST": lambda: commands.set_device_name("AT2_TEST"),
        "requête canal courant": commands.query_current_channel,
    }
    for q, key in [("volume", "volume"), ("squelch", "squelch"), ("temporisation", "tot_seconds"), ("VOX", "vox"),
                   ("sensibilité VOX", "vox_sensitivity"), ("inhibition TX", "tx_inhibit"), ("intervalle TX", "tx_interval_seconds"),
                   ("réduction de bruit", "noise_reduction"), ("Dual Watch", "dual_watch"), ("langue des annonces", "prompt_language"),
                   ("tonalité", "prompt_tone"), ("Smart Link", "smart_link")]:
        table[f"requête {q}"] = (lambda k=key: commands.SETTINGS[k].encode_query())
    return table[nom]()


@pytest.mark.parametrize("v", load("commandes"), ids=lambda v: v["nom"])
def test_commandes_conformes_a_l_officiel(v):
    assert _setting_payload(v["nom"]).hex() == v["charge_hex"]


def test_lectures_de_canaux_reelles():
    for v in load("canaux"):
        if "corps_hex" not in v:
            continue
        cfg = chan.decode_channel_read_body(bytes.fromhex(v["corps_hex"]))
        for champ, attendu in v["attendu"].items():
            assert getattr(cfg, champ) == pytest.approx(attendu) if isinstance(attendu, float) else getattr(cfg, champ) == attendu


def test_reponse_de_lecture_reelle_est_reconnue():
    v = next(x for x in load("trames_canal") if "réponse" in x["nom"])
    payload, _ = try_decode_frame(bytes.fromhex(v["trame_hex"]))
    pkt = decode_packet(payload)
    cfg = chan.decode_channel_read_packet(pkt.type, pkt.group, pkt.body)
    assert cfg is not None and cfg.channel == 1 and cfg.rx_mhz == pytest.approx(430.125)


def test_ecriture_canal_12_reproduit_la_trame_envoyee_au_materiel():
    v = next(x for x in load("canaux") if x["nom"].startswith("écriture du canal 12"))
    body = next(x for x in load("canaux") if x["nom"].startswith("canal 12"))["corps_hex"]
    cfg = chan.decode_channel_read_body(bytes.fromhex(body))
    assert encode_frame(chan.build_channel_write_request(cfg)).hex() == v["trame_hex"]


def test_tonalites():
    for v in next(x for x in load("canaux") if "tonalites" in x)["tonalites"]:
        assert chan.parse_tone_label(v["etiquette"]) == (v["valeur"], v["type"], v["polarite"])


@pytest.mark.parametrize("v", [x for x in load("messages") if "trames_hex" in x], ids=lambda v: v["nom"])
def test_messages(v):
    asm = messages.MessageAssembler()
    done = None
    for hx in v["trames_hex"]:
        payload, _ = try_decode_frame(bytes.fromhex(hx))
        done = asm.feed(decode_packet(payload)) or done
    exp = v["reassemblage_attendu"]
    assert done is not None
    assert (done.kind, done.msg_id, done.sender) == (exp["kind"], exp["msg_id"], exp["sender"])
    if "text" in exp:
        assert done.text == exp["text"]
    else:
        assert done.data.hex() == exp["data_hex"]


def test_amorcage_ptt_a_six_etapes():
    assert len(ptt.preflight_payloads()) == 6
