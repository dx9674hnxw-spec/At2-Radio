#!/usr/bin/env python3
"""Essai à deux radios branchées sur la même machine : l'une ÉMET, l'autre ÉCOUTE.

    python exemples/essai_deux_radios.py --emetteur /dev/ttyACM0 --recepteur /dev/ttyACM1

ATTENTION : ce script ÉMET sur les ondes (chaque envoi demande confirmation).
Avant de commencer :
  * les deux radios sont allumées, sur le MÊME canal, avec la même fréquence, le même mode
    (analogique ou numérique) et la même clé de chiffrement ; le script le vérifie ;
  * place-les à 1 ou 2 mètres l'une de l'autre, pas collées ;
  * vérifie la fréquence et ta licence ; mets le volume bas.

Chaque radio écrit ses trames dans un fichier ``deux-radios-<A|B>-AAAAMMJJ-HHMMSS.log``.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from at2radio import Radio, RadioError  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []
STAMP = time.strftime("%Y%m%d-%H%M%S")


def say(line: str) -> None:
    print(line)


def record(name: str, ok: bool | None, detail: str = "") -> None:
    mark = {True: "OK ", False: "ÉCHEC", None: "IGNORÉ"}[ok]
    RESULTS.append((name, mark, detail))
    say(f"  -> {mark} {detail}")


def confirm(question: str) -> bool:
    return input(f"\n{question} [o/N] ").strip().lower() in ("o", "oui", "y", "yes")


async def open_radio(name: str, port: str) -> Radio:
    radio = Radio(name)
    log = open(f"deux-radios-{name}-{STAMP}.log", "w", encoding="utf-8")
    radio.on("frame", lambda line: (log.write(line + "\n"), log.flush()))
    radio.on("message", lambda m: say(f"  [radio {name} a reçu] {m.type} de {m.sender!r} : {m.text or ''} {m.lat or ''},{m.lon or ''}"))
    await radio.connect_serial(port)
    return radio


def same_channel(a, b) -> list[str]:
    diffs = []
    for f in ("rx_mhz", "tx_mhz", "rx_tone", "tx_tone", "mode_digital", "encrypt_key", "bandwidth_narrow"):
        if getattr(a, f) != getattr(b, f):
            diffs.append(f"{f} : A={getattr(a, f)} B={getattr(b, f)}")
    return diffs


async def deliver(sender: Radio, receiver: Radio, label: str, send_coro, check, timeout: float = 12.0) -> None:
    """Envoie avec ``sender`` et attend sur ``receiver`` un message qui vérifie ``check``."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def on_msg(m):
        if not fut.done() and check(m):
            fut.set_result(m)

    receiver.on("message", on_msg)
    t0 = loop.time()
    try:
        await send_coro
    except RadioError as exc:
        receiver.off("message", on_msg)
        return record(label, False, f"envoi refusé : {exc}")
    try:
        m = await asyncio.wait_for(fut, timeout)
        record(label, True, f"reçu en {loop.time() - t0:.1f} s, expéditeur déclaré {m.sender!r}")
    except asyncio.TimeoutError:
        record(label, False, f"rien reçu par la radio réceptrice en {timeout:.0f} s (l'envoi a été acquitté)")
    finally:
        receiver.off("message", on_msg)


async def main(a) -> int:
    say("== Connexion des deux radios")
    try:
        tx = await open_radio("A", a.emetteur)
        rx = await open_radio("B", a.recepteur)
    except RadioError as exc:
        record("connexion", False, str(exc))
        return summary()
    record("connexion des deux radios", True, f"A={a.emetteur}  B={a.recepteur}")

    say(f"\n== Vérification : le canal {a.canal} est-il identique sur les deux radios ?")
    try:
        ca = await tx.read_channel(a.canal)
        cb = await rx.read_channel(a.canal)
    except RadioError as exc:
        record("lecture du canal", False, f"{exc}")
        say("  Un autre programme utilise peut-être un de ces ports (le service de la page ? ModemManager ?).")
        say("  Vérifie avec : sudo fuser -v /dev/ttyACM0 /dev/ttyACM1")
        await tx.disconnect()
        await rx.disconnect()
        return summary()
    say(f"  A : {ca.rx_mhz} MHz, {'numérique' if ca.mode_digital else 'analogique'}, clé {ca.encrypt_key}")
    say(f"  B : {cb.rx_mhz} MHz, {'numérique' if cb.mode_digital else 'analogique'}, clé {cb.encrypt_key}")
    diffs = same_channel(ca, cb)
    if diffs:
        record("canaux identiques", False, "; ".join(diffs))
        say("  Corrige les deux radios (page de programmation) avant de relancer.")
        return summary()
    if ca.rx_mhz is None:
        record("canaux identiques", False, f"le canal {a.canal} est vide")
        return summary()
    record("canaux identiques", True)

    if a.selectionner and confirm(f"Mettre les deux radios sur le canal {a.canal} ? (commande de changement de canal, jamais testée)"):
        await tx.select_channel(a.canal)
        await rx.select_channel(a.canal)
        await asyncio.sleep(1)
        record("changement de canal (envoyé)", None, "vérifie que les deux radios sont bien sur ce canal")

    say("\n== A -> B")
    if confirm("A ÉMET « TEST At2-Radio » vers B ? (transmission réelle)"):
        await deliver(tx, rx, "texte A -> B", tx.send_text("ALPHA", "TEST At2-Radio"),
                      lambda m: m.type == "text" and m.text == "TEST At2-Radio")
    if confirm("A ÉMET une POSITION (48.8584, 2.2945) vers B ? (transmission réelle)"):
        await deliver(tx, rx, "position A -> B", tx.send_position("ALPHA", 48.8584, 2.2945),
                      lambda m: m.type == "position" and abs(m.lat - 48.8584) < 1e-4 and abs(m.lon - 2.2945) < 1e-4)
    if a.sos and confirm("A ÉMET un SOS DE TEST vers B ? (message « TEST — pas une vraie urgence » ; "
                         "toute radio ou appli à portée sur ce canal le recevra comme un SOS)"):
        await deliver(tx, rx, "SOS A -> B", tx.send_sos("ALPHA", 48.8584, 2.2945, "TEST — pas une vraie urgence"),
                      lambda m: m.type == "sos" and "TEST" in (m.text or ""))

    say("\n== B -> A (sens inverse)")
    if confirm("B ÉMET « Retour At2-Radio » vers A ? (transmission réelle)"):
        await deliver(rx, tx, "texte B -> A", rx.send_text("BRAVO", "Retour At2-Radio"),
                      lambda m: m.type == "text" and m.text == "Retour At2-Radio")

    await tx.disconnect()
    await rx.disconnect()
    return summary()


def summary() -> int:
    say("\n=========== RÉSUMÉ ===========")
    for name, mark, detail in RESULTS:
        say(f"{mark:7} {name} {('— ' + detail) if detail else ''}")
    say(f"\nFichiers à partager : deux-radios-A-{STAMP}.log et deux-radios-B-{STAMP}.log")
    return 1 if any(m == "ÉCHEC" for _, m, _ in RESULTS) else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--emetteur", required=True, metavar="PORT", help="port USB de la radio A (celle qui émet en premier)")
    p.add_argument("--recepteur", required=True, metavar="PORT", help="port USB de la radio B")
    p.add_argument("--canal", type=int, default=1, help="canal à utiliser (1 par défaut)")
    p.add_argument("--selectionner", action="store_true", help="envoyer aussi le changement de canal aux deux radios")
    p.add_argument("--sos", action="store_true", help="tester aussi un SOS (de test)")
    sys.exit(asyncio.run(main(p.parse_args())))
