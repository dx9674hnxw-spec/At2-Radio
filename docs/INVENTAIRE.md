# At2-Radio : inventaire des fonctions officielles (jalon 2)

Comparaison entre l'application officielle **AT2 HT** (`byf3332/Baofeng-ALERVITES-AT2-Android`, commit `d91f50f`, Apache-2.0) et l'implémentation actuelle `at2-bridge` (Python).

Méthode : lecture du code Kotlin de l'application (`At2Commands`, `At2ProtocolExecutor`, `At2RxState`, `BleEventController`, `PttVoiceSender/Receiver`, `LocationShareController`, `BleSession`, `DeviceConnectionController`, README) et recherche des équivalents dans `at2-bridge`.
Mise à jour du 13/10/2026 : les essais sur radio réelle (USB) confirment la correction de Smart Link ; voir `PROTOCOLE.md` §9. Limite : lecture statique uniquement pour le reste. Rien n'a été exécuté, ni sur matériel, ni en test. Les écarts ci-dessous sont des **écarts de code**, pas des défauts prouvés sur radio.

## 1. Ce qu'on retrouve des deux côtés (déjà porté)

| Fonction officielle | Commande | Dans at2-bridge |
|---|---|---|
| Choisir le canal (1–30) | `0x020E` | oui |
| Dual Watch : activer, canal A/B, focus | `0x020D`, `0x020E` (côté), `0x020F` | oui |
| Volume 1–8 | `0x0101` | oui |
| Squelch 0–9 | `0x0204` | oui |
| Temporisation d'émission 0–240 s | `0x0205` | oui |
| VOX et sensibilité 1–5 | `0x0206`, `0x0207` | oui |
| Inhibition TX | `0x0209` | oui |
| Intervalle TX 0–240 s | `0x020A` | oui |
| Réduction de bruit | `0x0211` | oui |
| Langue des annonces, tonalité | `0x0103`, `0x0104` | oui |
| Nom de l'appareil | `0x0301` | oui |
| Smart Link activé / désactivé | `0x0409` | oui |
| Lire / écrire / effacer un canal ; écrire les 30 | `0x0202` | oui (écriture non relue, voir PROTOCOLE) |
| Messages texte, image, voix hors réseau (fragmentation, accusés) | famille `0x04` | oui (texte confirmé ; image et voix non vérifiés) |
| Session hors réseau et prise/fin de porteuse | `0x0407`, `0x0402` | oui |
| Voix PTT (AMR-NB MR475, 5 trames de 12 octets par paquet, un paquet toutes les 100 ms, queue de 4 trames) | `0x0403` | oui |
| UUID BLE `AE60` / `AE10` (écriture) / `AE05` (notification) | | oui |

## 2. Écarts : ce que fait l'application officielle et pas `at2-bridge`

Classés par intérêt pour At2-Radio. « Preuve » indique où lire le comportement officiel.

### A. Compatibilité : à corriger en priorité

| # | Écart | Détail | Preuve |
|---|---|---|---|
| A1 | **Format des positions et SOS incompatible** | L'application officielle envoie la position comme du texte `lat*-#-*-#-*-#-*lon` (6 décimales, zéros finaux supprimés) et un SOS comme `message#-*-#-*-#-*-#lat*-#-*-#-*-#-*lon`. `at2-bridge` envoie `📍 lat,lon` (5 décimales) : **l'app officielle et les radios équipées de l'app ne reconnaissent pas ces messages**, et inversement. | `LocationShareController.kt` : `LOCATION_COORD_SEPARATOR`, `HELP_TEXT_SEPARATOR`, `sendCurrentLocationMessage`, `parseSpecialText` |
| A2 | **Messages SOS prédéfinis** | 8 messages d'aide par défaut (perdu, blessé, bloqué par la pluie, hypothermie, sans signal, nuit/camp, manque d'eau, voiture bloquée), 10 modèles personnalisés maximum, 800 octets UTF-8 maximum. | `DEFAULT_HELP_PRESETS`, `MAX_HELP_PRESETS`, `MAX_HELP_MESSAGE_UTF8_BYTES` |
| A3 | **Limites de taille** | Texte : 1000 octets UTF-8 maximum. Voix : de 600 ms à 15 s (`at2-bridge` arrondit à la seconde supérieure, minimum 1 s). | `MAX_OFFLINE_TEXT_UTF8_BYTES`, `MIN/MAX_OFFLINE_VOICE_DURATION_MS` |
| A4 | **Pipeline d'image** | L'application a un redimensionnement dont la sortie a été vérifiée **octet pour octet** contre la bibliothèque officielle (300 px, JPEG qualité 75, passe intermédiaire JPEG qualité 100 avec correction d'orientation EXIF). `at2-bridge` utilise Pillow avec les mêmes paramètres, sans garantie d'une sortie identique. Les images officielles font 300 px au plus ; le champ largeur/hauteur annoncé est celui de l'image **d'origine** après rotation. | `OfflineImageProcessor.kt`, `tools/verification/` (images et sommes SHA-256 de référence réutilisables comme vecteurs de test) |

| A5 | **Trois commandes différentes de l'officiel** (constaté en générant les vecteurs de test) | Nom de l'appareil : officiel `00 02 03 01 <nom>`, `at2-bridge` `00 03 01 <nom>`. Smart Link : officiel `00 02 04 09 <v>` (écriture) et `00 01 04 09` (requête), `at2-bridge` `00 04 09 <v>` et `00 04 09`. Le type de commande (écriture `02`, requête `01`) est omis, comme pour le changement de canal déjà corrigé. | `At2Commands.kt` ; `vecteurs/commandes.json` |

### B. Fonctions absentes

| # | Fonction | Commande | Remarque |
|---|---|---|---|
| B1 | **Association du bouton PTT principal (appui long) : choix de l'application cible de Smart Link** | lecture `0x040A 01`, écriture `0x040A 01 <cible>` | Cibles : Autre 1 (`01`), Zello (`06`), Autre 3 (`08`), Autre 4 (`09`), Autre 2 (`0A`), Olaradio (`0B`). Accusé `82 04 0A 00`. |
| B2 | **Lecture de l'état Smart Link** | `0x0409` (requête) | `at2-bridge` n'a que l'écriture. |
| B3 | **Mode « discussion / PTT » de la page hors réseau** | `0x0402 <0/1>` | Existe sous une autre forme dans `at2-bridge` (prise de porteuse) ; à vérifier si c'est exactement la même commande. |
| B4 | **Lecture de la configuration du canal courant** | `0x0202` avec filtre canal courant | Utilisée par l'amorçage de la page PTT. |
| B5 | **Écriture de la fréquence TX seule** | `0x0204` + 1 octet | Présente dans le code officiel ; usage non démontré (semble inachevée). À ignorer sauf preuve. |
| B6 | **Amorçage de la page PTT (« preflight »)** | voir §3 | Six requêtes avant la première émission. **Piste principale pour le PTT analogique.** |
| B7 | **Amorçage à la connexion** | `0x0202` (lecture globale), puis lecture Dual Watch (`0x020D`), Smart Link (`0x0409`), réglages | Délais de 120 à 350 ms entre requêtes. |

### C. Comportements de l'application (hors protocole, mais utiles dans At2-Radio)

| # | Fonction officielle | Intérêt pour At2-Radio |
|---|---|---|
| C1 | Scan BLE trié par RSSI décroissant, délai de connexion de 10 s | à reprendre dans la bibliothèque (`scan_ble`) |
| C2 | Négociation MTU 247 et priorité de connexion haute | `at2-bridge` n'en fait pas ; peut affecter le débit et la fiabilité du PTT |
| C3 | Reconnexion automatique, liste des appareils connus (adresse, nom, RSSI) | module « appareils connus » du service |
| C4 | Historique de discussion : 100 messages au chargement, 500 par fil, nom d'utilisateur persistant, compteur d'identifiant de message persistant | module historique optionnel |
| C5 | Réception : état poussé par la radio (canal courant, Dual Watch A/B) lu dans les **notifications** sans requête | l'événement `connection`/`state` de la bibliothèque |
| C6 | Vibration à la réception | côté client, hors périmètre |

## 3. Piste pour le PTT analogique

`at2-bridge` envoie : session hors réseau activée, puis prise de porteuse, puis audio.

L'application officielle, en entrant sur la page PTT, envoie **d'abord six messages** (`enterPttPreflight`) :

1. requête `0x020D` (Dual Watch),
2. session hors réseau activée (`0x0407 01`),
3. requête `0x020F` (focus),
4. requête `0x020E` (canal),
5. requête `0x0202` filtrée sur le canal courant,
6. requête `0x0304` (famille appareil, **réponse non exploitée par l'application** ; rôle à déterminer),

puis, à chaque appui : `0x0402 01`, 20 ms de pause, audio, fin d'audio, `0x0402 00`.

Hypothèse à tester sur matériel : **la radio n'est pas « armée » pour l'émission sans cette séquence**, en particulier la requête du canal courant. C'est cohérent avec « émission acquittée mais aucune porteuse ». **Aucune certitude** : le canal numérique fonctionne aujourd'hui sans cette séquence.

## 4. Hors périmètre côté officiel (donc pas dans le « portage complet »)

D'après le README de l'application : programmation par USB-C et mise à jour du micrologiciel, modification du micrologiciel (AC696X / UC8288), radios Baofeng GMSK à 16 canaux hors BLE, décodage complet de l'interface radio (FEC, entrelacement).

À noter : `at2-bridge` offre une connexion **USB série** que l'application officielle n'a pas. On la garde dans At2-Radio comme transport supplémentaire, signalée comme non officielle.

## 5. Autres éléments à reprendre dans le dépôt

- `tools/verification/` : image source, sorties de référence et `baseline.json` → vecteurs de test pour le pipeline d'image.
- `THIRD_PARTY_NOTICES.md`, `NOTICE` : modèles pour les attributions d'At2-Radio.
- Le dépôt officiel contient un remplacement open source de `libtalkie.so` (codec AMR) : à étudier pour savoir si At2-Radio peut s'en passer ou le référencer.
- `tools/CPS_mod/` : script de modification de l'interface du logiciel de programmation d'origine (CPS). **À ne pas reprendre** : hors sujet et à risque (permet de modifier un identifiant de revendeur).

## 6. Liste d'écarts à porter, dans l'ordre

1. **A1** format de position et SOS (+ A2 messages prédéfinis), et **A5** commandes nom / Smart Link à corriger : interopérabilité avec l'application officielle.
2. **B6 / §3** séquence d'amorçage PTT : tester sur matériel l'hypothèse du PTT analogique.
3. **A3** limites de taille texte et voix.
4. **A4** pipeline d'image + vecteurs de test officiels.
5. **B1, B2** Smart Link : lecture et association du bouton PTT.
6. **C2** MTU 247 et priorité de connexion.
7. **B7, C5** amorçage à la connexion et lecture des notifications d'état.
8. **B3, B4** à confirmer par lecture ou capture ; **B5** ignorer sauf preuve.
9. **C1, C3, C4** services annexes (scan, appareils connus, historique).

## 7. Ce que je n'ai pas pu vérifier

- Le code compilé de l'application (bibliothèques natives `libgojni.so`, `libtalkie.so`) n'est pas lu : seuls les sources sont analysés.
- La commande `0x0304` : l'application l'envoie sans en décoder la réponse.
- Le comportement réel de chaque écart sur radio : toute affirmation « ne fonctionne pas sans X » reste une hypothèse tant qu'un test matériel ne l'a pas confirmée.
