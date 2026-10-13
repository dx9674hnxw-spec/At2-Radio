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
    rx_kinds: dict[str, int] = {}

    listening = {"on": False}

    def on_frame(line):
        LOG.write(line + "\n")
        # Pendant l'écoute : toute trame reçue qui n'est pas de la voix est affichée en direct,
        # y compris celles que le décodeur rejette (elles ne figurent sinon que dans le fichier log).
        if listening["on"] and line.startswith("RX ") and not line.startswith("RX aa5541000204030000"):
            print(f"  [trame brute reçue] {line[3:]}")
        if line.startswith("RX "):
            try:
                b = bytes.fromhex(line[3:])
                key = f"type {b[4]:02x} groupe {b[5]:02x} sous-commande {b[6]:02x}"
                rx_kinds[key] = rx_kinds.get(key, 0) + 1
            except (ValueError, IndexError):
                pass
    radio.on("frame", on_frame)
    radio.on("message", lambda m: log(f"  [reçu] {m.type} de {m.sender} : {m.text or m.lat or ''}"))
    radio.on("state", lambda s: log(f"  [état poussé par la radio] canal {s.current_channel}"))
    voice = {"packets": 0, "pcm": bytearray()}

    def on_voice(v):
        voice["packets"] += 1
        if v.pcm:
            voice["pcm"] += v.pcm
    radio.on("ptt_voice", on_voice)
    radio.on("ptt_state", lambda st: log(f"  [voix] {'quelqu\'un parle' if st == 'rx' else 'silence'} ({voice['packets']} paquets reçus)"))

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

    if args.volume:
        cur = await step("Lecture du volume", radio.get("volume"))
        if cur is not FAILED and confirm(f"Mettre le VOLUME de la radio sur {args.volume} (actuellement {cur}) ? (reste ainsi après le test)"):
            await radio.set("volume", args.volume)
            await asyncio.sleep(0.5)
            now = await step("Relecture du volume", radio.get("volume"))
            record("volume", now == args.volume, f"maintenant {now}")

    if args.dual_watch:
        want = args.dual_watch == "on"
        cur = await step("Lecture du Dual Watch", radio.get("dual_watch"))
        if cur is not FAILED and cur != want and confirm(f"Mettre le Dual Watch sur {args.dual_watch.upper()} ? (modifie la radio ; il reste ainsi après le test)"):
            await radio.set("dual_watch", want)
            await asyncio.sleep(0.5)
            now = await step("Relecture du Dual Watch", radio.get("dual_watch"))
            record("Dual Watch", now == want, f"maintenant {'activé' if now else 'désactivé'}")
        elif cur == want:
            record("Dual Watch", True, "déjà dans cet état")

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

    if args.ecriture_vide:
        n = args.ecriture_vide
        cur = await step(f"Lecture du canal {n}", radio.read_channel(n))
        if cur is not FAILED and (cur.rx_mhz is not None or cur.tx_mhz is not None):
            record("écriture réelle", None, f"le canal {n} n'est pas vide ({cur.rx_mhz} MHz) : choisis un canal vide (--ecriture-vide)")
        elif cur is not FAILED and confirm(f"Écrire une fréquence de TEST (446,10000 MHz, ton OFF) dans le canal VIDE {n}, la relire, puis le remettre vide ? "
                                           "(modifie la radio, sans émettre)"):
            from at2radio import ChannelConfig
            test = ChannelConfig(channel=n, rx_mhz=446.1, tx_mhz=446.1)
            res = await step(f"Écriture de test du canal {n}", radio.write_channel(test))
            if res is not FAILED:
                record(f"canal {n} : écriture réelle relue", res.verified, "; ".join(res.differences) or "446,1 MHz bien relu")
            back = await step(f"Remise à vide du canal {n}", radio.write_channel(cur))
            if back is not FAILED:
                record(f"canal {n} : remis à vide", back.verified, "; ".join(back.differences) or "")

    if args.nom:
        if confirm(f"Changer le NOM de la radio en « {args.nom} » ? (commande corrigée, jamais testée ; "
                   "tu pourras remettre l'ancien nom depuis l'appli officielle)"):
            await radio.set_device_name(args.nom)
            record("nom de l'appareil (envoyé)", None, "à vérifier à l'écran ou dans l'appli officielle")

    if args.smart_link:
        if confirm("Inverser SMART LINK, le relire, puis le remettre comme avant ?"):
            old = await step("Lecture de Smart Link", radio.get("smart_link"))
            if old is not FAILED:
                await radio.set("smart_link", not old)
                await asyncio.sleep(0.5)
                got = await step("Relecture de Smart Link", radio.get("smart_link"))
                await radio.set("smart_link", old)
                await asyncio.sleep(0.5)
                back = await step("Remise de Smart Link", radio.get("smart_link"))
                record("Smart Link : écriture puis relecture", got == (not old),
                       f"avant {old}, après écriture {got}, remis à {back}")

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

    if args.ptt_test or args.ptt_wav:
        what = f"le fichier {args.ptt_wav}" if args.ptt_wav else "un son de test (440 Hz, 2 secondes)"
        if confirm(f"ÉMETTRE EN VOIX (PTT) {what} ? (transmission réelle ; écoute la radio B : tu dois l'entendre)"):
            import math, struct, wave
            if args.ptt_wav:
                with wave.open(args.ptt_wav, "rb") as w:
                    ok = (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 8000)
                    pcm = w.readframes(w.getnframes()) if ok else b""
                if not ok:
                    record("PTT", False, "le fichier doit être en mono, 16 bits, 8000 Hz")
                    pcm = b""
            else:
                pcm = b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 440 * i / 8000))) for i in range(16000))
            if pcm:
                try:
                    async with radio.ptt_session() as ptt_session:
                        log(f"  prise de porteuse acquittée par la radio : {'OUI' if ptt_session.key_acked else 'NON'}")
                        for i in range(0, len(pcm) - 319, 320):
                            await ptt_session.feed(pcm[i:i + 320])
                    record("émission de voix (PTT)", None, f"{len(pcm) // 16000:.0f} s envoyées, prise de porteuse acquittée : "
                           f"{'oui' if ptt_session.key_acked else 'NON'} ; dis si B l'a entendue")
                except Exception as exc:
                    record("émission de voix (PTT)", False, f"{type(exc).__name__}: {exc}")

    if args.ecoute_guidee:
        listening["on"] = True
        log("\n== Ouverture de la messagerie (Dual Watch et Smart Link doivent être désactivés)")
        try:
            await radio.open_chat()
            record("session de messagerie ouverte", True)
        except RadioError as exc:
            record("session de messagerie", False, str(exc))
        got_msgs: list = []
        radio.on("message", got_msgs.append)

        async def phase(titre: str, consigne: str, secondes: int) -> tuple[int, int, dict]:
            rx_kinds.clear()
            v0, m0 = voice["packets"], len(got_msgs)
            log(f"\n######## {titre} ########\n>>> {consigne}\n    (tu as {secondes} secondes ; ne touche à rien d'autre)")
            await asyncio.sleep(secondes)
            return voice["packets"] - v0, len(got_msgs) - m0, dict(rx_kinds)

        v, m, kinds = await phase("PHASE 1 : VOIX avec le bouton PTT PHYSIQUE de la radio B",
                                  "MAINTENANT : maintiens le bouton PTT de la radio B et dis « test un deux trois » pendant 4 secondes, puis relâche.", 25)
        log(f"  Phase 1 : {v} paquets de voix, {m} messages, trames reçues par type : {kinds or 'aucune'}")
        record("phase 1 : voix (PTT physique de B)", v > 0, f"{v} paquets de voix reçus par l'USB")
        v, m, kinds = await phase("PHASE 2 : TEXTE depuis l'APPLI OFFICIELLE (radio B)",
                                  "MAINTENANT : envoie le message « Bonjour depuis l'appli » depuis l'appli officielle.", 40)
        log(f"  Phase 2 : {v} paquets de voix, {m} messages, trames reçues par type : {kinds or 'aucune'}")
        record("phase 2 : texte (appli officielle)", m > 0, f"{m} message(s) décodé(s) ; trames reçues : {kinds or 'aucune'}")
        v, m, kinds = await phase("PHASE 3 : VOIX depuis l'APPLI OFFICIELLE (radio B)",
                                  "MAINTENANT : dans l'appli officielle, maintiens le bouton PTT et dis « test un deux trois » pendant 4 secondes.", 30)
        log(f"  Phase 3 : {v} paquets de voix, {m} messages, trames reçues par type : {kinds or 'aucune'}")
        record("phase 3 : voix (appli officielle)", v > 0, f"{v} paquets de voix reçus par l'USB")
        if voice["pcm"]:
            import wave
            name = f"reception-{time.strftime('%Y%m%d-%H%M%S')}.wav"
            with wave.open(name, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(bytes(voice["pcm"]))
            record("son enregistré", True, name)

    if args.ecoute:
        listening["on"] = True
        log("\n== Ouverture de la messagerie (nécessaire pour recevoir ; le Dual Watch et Smart Link doivent être désactivés)")
        try:
            await radio.open_chat()
            record("session de messagerie ouverte", True)
        except RadioError as exc:
            record("session de messagerie", False, str(exc))
        log(f"\n== Écoute pendant {args.ecoute} s (envoie un message depuis une autre radio)")
        await asyncio.sleep(args.ecoute)
        if voice["packets"]:
            detail = f"{voice['packets']} paquets de voix reçus (~{voice['packets'] * 0.1:.1f} s)"
            if voice["pcm"]:
                import wave
                name = f"reception-{time.strftime('%Y%m%d-%H%M%S')}.wav"
                with wave.open(name, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(bytes(voice["pcm"]))
                detail += f" ; son enregistré dans {name}"
            else:
                detail += " ; son non décodé (installe libopencore-amrnb0 pour l'enregistrer)"
            record("réception de voix par l'USB", True, detail)
        record("écoute", None, "voir les lignes [reçu] et [voix] ci-dessus")

    await radio.close_chat()
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
    p.add_argument("--smart-link", action="store_true", help="tester Smart Link (inverser, relire, remettre)")
    p.add_argument("--ecriture-vide", type=int, metavar="N", help="écrire une fréquence de test dans le canal VIDE N, la relire, puis le remettre vide")
    p.add_argument("--texte", metavar="TEXTE", help="ÉMET un message texte")
    p.add_argument("--position", metavar="LAT,LON", help="ÉMET une position")
    p.add_argument("--ecoute-guidee", action="store_true", help="écoute en trois phases guidées (PTT physique, texte de l'appli, PTT de l'appli) avec un verdict par phase")
    p.add_argument("--ptt-test", action="store_true", help="ÉMET un son de test en voix (PTT), 2 secondes")
    p.add_argument("--ptt-wav", metavar="FICHIER", help="ÉMET un fichier son (mono, 16 bits, 8000 Hz) en voix (PTT), par exemple un reception-….wav")
    p.add_argument("--volume", type=int, choices=range(1, 9), metavar="1-8", help="régler le volume de la radio (il reste ainsi)")
    p.add_argument("--dual-watch", choices=["on", "off"], help="mettre le Dual Watch sur on ou off (l'appli officielle bloque la messagerie s'il est activé)")
    p.add_argument("--pseudo", default="TEST", help="pseudo affiché pour les messages émis")
    p.add_argument("--ecoute", type=int, metavar="SECONDES", help="écouter les messages reçus")
    sys.exit(asyncio.run(main(p.parse_args())))
