#!/usr/bin/env python3
"""Essai sur une vraie radio AT2. Par défaut : LECTURE SEULE (rien n'est écrit, rien n'est émis).

    pip install -e ".[ble]"                                   # ou ".[serial]" pour l'USB
    python exemples/essai_materiel.py --ble AA:BB:CC:DD:EE:FF
    python exemples/essai_materiel.py --serial /dev/ttyUSB0

Les étapes qui modifient la radio ou émettent sur les ondes sont des options, et chacune
demande une confirmation. Tout est enregistré dans un fichier ``essai-AAAAMMJJ-HHMMSS.log``
(trames envoyées et reçues) : c'est ce fichier qu'il faut partager pour analyser un échec.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from at2radio import Radio, RadioError  # noqa: E402

FAILED = object()          # retourné par step() quand l'étape a échoué
RESULTS: list[tuple[str, str, str]] = []
LOG = None


def log(line: str) -> None:
    print(line)
    if LOG:
        LOG.write(line + "\n")
        LOG.flush()


def record(name: str, ok: bool | None, detail: str = "") -> None:
    mark = {True: "OK ", False: "ÉCHEC", None: "IGNORÉ"}[ok]
    RESULTS.append((name, mark, detail))
    log(f"  -> {mark} {detail}")


def confirm(question: str) -> bool:
    return input(f"\n{question} [o/N] ").strip().lower() in ("o", "oui", "y", "yes")


async def step(name: str, coro):
    log(f"\n== {name}")
    try:
        result = await coro
        return result
    except (RadioError, ValueError, asyncio.TimeoutError) as exc:
        record(name, False, f"{type(exc).__name__}: {exc}")
        return FAILED


async def main(args) -> int:
    global LOG
    LOG = open(f"essai-{time.strftime('%Y%m%d-%H%M%S')}.log", "w", encoding="utf-8")
    radio = Radio("essai")
    radio.on("frame", lambda line: LOG.write(line + "\n"))
    radio.on("message", lambda m: log(f"  [reçu] {m.type} de {m.sender} : {m.text or m.lat or ''}"))
    radio.on("state", lambda s: log(f"  [état poussé par la radio] canal {s.current_channel}"))

    log("== Connexion")
    try:
        if args.ble:
            await radio.connect_ble(args.ble)
        else:
            await radio.connect_serial(args.serial)
    except RadioError as exc:
        record("connexion", False, str(exc))
        return summary()
    record("connexion", True, f"{radio.kind} {radio.target}")

    # --- 1. lecture seule -------------------------------------------------
    cfg = await step("Lecture du canal 1", radio.read_channel(1))
    if cfg is not FAILED:
        log(f"  canal 1 : RX {cfg.rx_mhz} MHz, TX {cfg.tx_mhz} MHz, ton {cfg.rx_tone}/{cfg.tx_tone}, "
            f"{'numérique' if cfg.mode_digital else 'analogique'}")
        record("lecture du canal 1", True)

    if args.tous_les_canaux:
        channels = await step("Lecture des 30 canaux", radio.read_all_channels())
        if channels is not FAILED:
            for c in channels:
                log(f"  CH{c.channel:02d} {c.rx_mhz} / {c.tx_mhz}")
            record("lecture des 30 canaux", True)

    settings = await step("Lecture des réglages", radio.get_all())
    if settings is not FAILED:
        for k, v in settings.items():
            log(f"  {k} = {v if v is not None else '(pas de réponse)'}")
        record("lecture des réglages", any(v is not None for v in settings.values()),
               f"{sum(v is not None for v in settings.values())}/{len(settings)} réponses")

    # --- 2. écritures (options) -------------------------------------------
    if args.reglage:
        if confirm("Changer le VOLUME d'un cran puis le remettre ? (modifie la radio, sans émettre)"):
            old = settings.get("volume") if settings not in (FAILED, None) and settings.get("volume") is not None else await radio.get("volume")
            new = old + 1 if old < 8 else old - 1
            await radio.set("volume", new)
            await asyncio.sleep(0.5)
            got = await step("Relecture du volume", radio.get("volume"))
            await radio.set("volume", old)
            record("volume : écriture puis relecture", got == new, f"écrit {new}, relu {got}, remis à {old}")
        else:
            record("volume", None)

    if args.ecriture_canal:
        n = args.ecriture_canal
        if confirm(f"Réécrire le canal {n} avec SON CONTENU ACTUEL puis le relire ? "
                   "(modifie la radio ; contenu identique, mais note le canal d'abord)"):
            cur = await step(f"Lecture du canal {n}", radio.read_channel(n))
            if cur is not FAILED:
                res = await step(f"Écriture du canal {n}", radio.write_channel(cur))
                if res is not FAILED:
                    record(f"canal {n} : écriture puis relecture", res.verified, "; ".join(res.differences) or "identique")
        else:
            record("écriture de canal", None)

    if args.nom:
        if confirm(f"Changer le NOM de la radio en « {args.nom} » ? (commande corrigée, jamais testée ; "
                   "tu pourras remettre l'ancien nom depuis l'appli officielle)"):
            await radio.set_device_name(args.nom)
            record("nom de l'appareil (envoyé)", None, "à vérifier à l'écran ou dans l'appli officielle")

    if args.smart_link:
        if confirm("Activer puis désactiver SMART LINK ? (commande corrigée, jamais testée)"):
            await radio.set("smart_link", True)
            await asyncio.sleep(0.5)
            await radio.set("smart_link", False)
            record("Smart Link (envoyé)", None, "à vérifier dans l'appli officielle")

    # --- 3. émission (option) -----------------------------------------------
    if args.texte:
        if confirm(f"ÉMETTRE le message « {args.texte} » sur le canal actuel ? "
                   "(transmission radio réelle : vérifie la fréquence et ta licence)"):
            res = await step("Envoi du texte", radio.send_text(args.pseudo, args.texte))
            record("envoi de texte (accusé reçu)", res is not FAILED, "vérifier la réception sur une 2e radio")

    if args.position:
        lat, lon = (float(x) for x in args.position.split(","))
        if confirm(f"ÉMETTRE une position {lat},{lon} au format de l'appli officielle ? (transmission réelle)"):
            ok = await step("Envoi de la position", radio.send_position(args.pseudo, lat, lon))
            record("envoi de position (accusé reçu)", ok is not FAILED, "vérifier qu'elle s'affiche dans l'appli officielle d'une 2e radio")

    if args.ecoute:
        log(f"\n== Écoute pendant {args.ecoute} s (envoie un message depuis une autre radio)")
        await asyncio.sleep(args.ecoute)
        record("écoute", None, "voir les lignes [reçu] ci-dessus")

    await radio.disconnect()
    return summary()


def summary() -> int:
    log("\n=========== RÉSUMÉ ===========")
    for name, mark, detail in RESULTS:
        log(f"{mark:7} {name} {('— ' + detail) if detail else ''}")
    log("\nPartage le fichier .log pour analyse (il contient l'adresse Bluetooth de la radio : masque-la si tu veux).")
    return 1 if any(m == "ÉCHEC" for _, m, _ in RESULTS) else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--ble", metavar="ADRESSE", help="adresse Bluetooth de la radio")
    g.add_argument("--serial", metavar="PORT", help="port USB série (ex. /dev/ttyUSB0, COM3)")
    p.add_argument("--tous-les-canaux", action="store_true", help="lire aussi les 30 canaux")
    p.add_argument("--reglage", action="store_true", help="tester l'écriture du volume (+1 puis remis)")
    p.add_argument("--ecriture-canal", type=int, metavar="N", help="réécrire le canal N avec son contenu actuel, puis relire")
    p.add_argument("--nom", metavar="NOM", help="tester le changement de nom de l'appareil")
    p.add_argument("--smart-link", action="store_true", help="tester Smart Link (activer puis désactiver)")
    p.add_argument("--texte", metavar="TEXTE", help="ÉMET un message texte")
    p.add_argument("--position", metavar="LAT,LON", help="ÉMET une position")
    p.add_argument("--pseudo", default="TEST", help="pseudo affiché pour les messages émis")
    p.add_argument("--ecoute", type=int, metavar="SECONDES", help="écouter les messages reçus")
    sys.exit(asyncio.run(main(p.parse_args())))
