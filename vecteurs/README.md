# Vecteurs de test

Fichiers de données (JSON) que **toute implémentation** d'At2-Radio doit reproduire : Python, Swift (app iOS), ou autre.
Chaque fichier a `description`, `source` et une liste `vecteurs`. Les octets sont en hexadécimal minuscule.

| Fichier | Contenu |
|---|---|
| `crc16.json` | CRC-16/CCITT (poly 0x1021, init 0x1234) |
| `trames_classiques.json` | charge ↔ trame complète, dialecte classique |
| `trames_cps.json` | idem dialecte CPS, dont 2 **captures sur radio réelle** |
| `commandes.json` | réglages et requêtes, 30 charges. L'attendu est relu dans le code Kotlin de l'application officielle |
| `canaux.json` | 3 lectures de canaux réelles décodées, trame d'écriture, tonalités, enregistrement de codeplug |
| `messages.json` | messages texte / fragmenté / voix / image : trames et réassemblage attendu |
| `ptt.json` | session hors réseau, prise et fin de porteuse, paquets de voix |

## Provenance et fiabilité
- Générés avec le code de `at2-bridge` (52 tests de protocole passants), puis **comparés à l'application officielle** pour les commandes.
- Les vecteurs « capture sur radio réelle » sont la seule vérité terrain. Les autres prouvent l'accord entre implémentations, pas le comportement de la radio.
- Dans `commandes.json`, l'attendu vient du Kotlin officiel. À la génération, **trois commandes d'`at2-bridge` différaient** (nom de l'appareil, Smart Link activé, requête Smart Link) : les vecteurs gardent la valeur officielle (voir `docs/PROTOCOLE.md` §8).
- `canaux.json` : le corps d'une lecture fait **24 octets** après opcode / groupe / paramètre (`01`, canal sur 2 octets, …). `at2-bridge` y ajoute un `02` en tête pour son décodeur ; les vecteurs donnent le corps réel sans cet octet.
