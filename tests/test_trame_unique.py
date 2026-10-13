"""Il n'y a qu'un format de trame : l'ancien « dialecte CPS » est une trame classique."""
from at2radio.protocole import channel as chan
from at2radio.protocole.frame import crc16_ccitt, encode_frame


def cps_frame(payload: bytes) -> bytes:  # définition de l'ancien dialecte CPS
    return b"\xaa\x55" + len(payload).to_bytes(2, "little") + payload + crc16_ccitt(payload).to_bytes(2, "little") + b"\x77\xee"


def test_cps_egale_classique_avec_type_11():
    req = chan.build_channel_read_request(1)          # 00 11 02 02 00 01 00
    assert cps_frame(req[1:]) == encode_frame(req)
    assert encode_frame(req).hex() == "aa550600110202000100d2d177ee"


def test_ecriture_egale_aussi():
    cfg = chan.ChannelConfig(channel=12, rx_mhz=433.725, tx_mhz=433.725)
    req = chan.build_channel_write_request(cfg)
    assert cps_frame(req[1:]) == encode_frame(req)
