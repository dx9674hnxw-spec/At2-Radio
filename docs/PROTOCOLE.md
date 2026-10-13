# Protocole de la radio AT2

Brouillon de spécification, indépendant du langage. Sources : code Kotlin de l'application officielle AT2 HT (Apache-2.0, `d91f50f`), implémentation `at2-bridge`, 6 lectures de canaux capturées sur radio réelle. Les octets sont en hexadécimal. « LE » = petit-boutiste, « BE » = grand-boutiste.

**Règle de lecture : un accusé de réception de trame ne prouve pas que la radio a appliqué la commande.** Chaque élément porte un statut (§9).

## 1. Transports
| Transport | Détails | Origine |
|---|---|---|
| BLE | Service `0000ae60-0000-1000-8000-00805f9b34fb`. Écriture : `0000ae10-…` (avec réponse). Notifications : `0000ae05-…` (descripteur `2902`). L'application officielle demande une MTU de 247 et la priorité de connexion haute. | officiel |
| USB série | 115200 bauds, mêmes trames | `at2-bridge` seulement (non officiel) |

## 2. Trame : un seul format
Début `AA 55`, fin `77 EE`. Une trame : `AA55 <long> 00 <type> <groupe> <sous-cmd> <corps> <crc16 LE> 77EE`.

CRC : CRC-16/CCITT non réfléchi, polynôme `0x1021`, valeur initiale `0x1234`, calculé **sur la charge sans le `00` initial**, écrit en petit-boutiste. La longueur compte les octets qui suivent le `00` initial.

**Il n'y a pas de second dialecte.** Les versions précédentes décrivaient un « dialecte CPS » (longueur sur 2 octets, pas de `00`) pour la lecture et l'écriture des canaux. Vérifié octet pour octet (`tests/test_trame_unique.py`) : une trame CPS est identique à une trame classique de type `0x11` (lecture), `0x12` (écriture) ou `0x91` (réponse), tant que la charge fait moins de 256 octets. Les deux octets de longueur n'en font qu'un suivi du `00` initial.

Réception : l'application officielle accepte deux variantes de longueur (avec ou sans le `00` initial compté). L'implémentation fait de même, puis se resynchronise sur le prochain `AA 55` si une trame est incomplète ou corrompue.

Vecteurs : `trames_classiques.json`, `trames_canal.json`, `crc16.json`.

## 3. Charge classique
`00` `<type>` `<groupe>` `<sous-cmd>` `<corps>`

| Type | Sens |
|---|---|
| `01` | requête |
| `02` | écriture / action |
| `81`, `82` | réponses (type de la demande OU `0x80`) |

| Groupe | Contenu |
|---|---|
| `01` | audio : volume, annonces, tonalité |
| `02` | radio : canaux, squelch, VOX, émission, Dual Watch |
| `03` | appareil : nom |
| `04` | hors réseau et extensions : Smart Link, messages, PTT |

Note de nommage : `at2-bridge` appelle « famille » le type, « commande » le groupe, et met la sous-commande au début du corps.

## 4. Réglages
Écriture : `00 02 <groupe> <sous-cmd> <valeur>`. Requête : `00 01 <groupe> <sous-cmd>`.

| Réglage | Groupe / sous-cmd | Valeur | Plage |
|---|---|---|---|
| Volume | `01 01` | 1 octet | 1–8 |
| Langue des annonces | `01 03` | `00` chinois, `01` anglais | |
| Tonalité de confirmation | `01 04` | `00` / `01` | |
| Squelch | `02 04` | 1 octet | 0–9 |
| Temporisation d'émission (TOT) | `02 05` | 2 octets LE, secondes | 0–240 |
| VOX | `02 06` | `00` / `01` | |
| Sensibilité VOX | `02 07` | 1 octet | 1–5 |
| Inhibition TX | `02 09` | `00` / `01` | |
| Intervalle TX | `02 0A` | 2 octets LE, secondes | 0–240 |
| Dual Watch | `02 0D` | `02` activé, `00` désactivé | |
| Canal actif (côté A) | `02 0E` | `01 <canal> 00` | 1–30 |
| Dual Watch : canal d'un côté | `02 0E` | `<côté> <canal> 00` (A=`01`, B=`02`) | 1–30 |
| Dual Watch : focus | `02 0F` | `<côté>` | |
| Réduction de bruit | `02 11` | `00` / `01` | |
| Nom de l'appareil | `03 01` | UTF-8 | |
| Smart Link | `04 09` | `00` / `01` | |
| Association du bouton PTT principal | `04 0A` | `01 <cible>` : Autre1 `01`, Zello `06`, Autre3 `08`, Autre4 `09`, Autre2 `0A`, Olaradio `0B` | officiel seulement |

Vecteurs : `commandes.json`. Accusés relevés dans l'application officielle : Smart Link `82 04 09 00`, bouton PTT `82 04 0A 00`, nom `82 03 01 00`, changement de canal `82 02 0E 00`, écriture de codeplug `82 02 02 00`.

Réponses aux requêtes : `81 <groupe> <sous-cmd> <valeur>`. L'état courant du canal (`81 02 0E 01 <canal> …`) et du Dual Watch est aussi **poussé spontanément** par la radio.

## 5. Canaux (30 emplacements)
### 5.1 Lecture d'un canal (confirmé sur matériel)
Requête : type `11`, groupe `02`, sous-commande `02`, `00`, canal LE16 (charge `00 11 02 02 00 <canal>`), par exemple `aa550600110202000100d2d177ee` pour le canal 1.
Réponse : type `91`, groupe `02`, sous-commande `02`, puis un **corps de 24 octets** :

| Octets | Champ |
|---|---|
| 0 | marqueur `01` |
| 1–2 | numéro de canal, LE16 |
| 3–6 | fréquence RX, LE32, valeur = MHz × 100 000 (0 = vide) |
| 7–10 | fréquence TX, idem |
| 11 / 12 | RX tonalité : valeur (`7F` = désactivé) / type (`00` CTCSS, `01` DCS) |
| 13 / 14 | TX tonalité : valeur / type |
| 15 / 16 | polarité DCS RX / TX (`00` normale, `01` inversée) |
| 17 | busy lock (`00` actif, `01` inactif) |
| 18 | largeur de bande (`01` étroite, `00` large) |
| 19 | puissance (`01` haute, `00` basse) |
| 20 | scan (`00` inclus, `01` exclu) |
| 21 | saut de fréquence (`01` actif) |
| 22 | mode (`01` numérique, `00` analogique) |
| 23 | clé de chiffrement (0 = aucune, 1 à 31) |

Le « corps de 25 octets » des anciennes versions comptait la sous-commande `02` : le corps réel fait 24 octets. Vecteurs : `canaux.json`.

### 5.2 Écriture
Deux chemins existent ; **aucun n'est confirmé par relecture** :
- **Type `12`** (`at2-bridge`) : `00 12 02 02 00` + 23 octets (canal LE16, RX, TX, six octets de tonalité, sept octets d'options, dans l'ordre de la table CPS officielle).
- **Classique** (application officielle) : `00 02 02 02` + enregistrement de 24 octets (marqueur `01`, canal, RX, TX, tonalités, options). Les 30 canaux = 720 octets, envoyés en morceaux de 168 octets.
- Effacer un canal : enregistrement vide (RX = TX = 0, tonalités `7F`).

**Règle de l'API : toute écriture est suivie d'une relecture et d'une comparaison.**

### 5.3 Tonalités
CTCSS : 51 fréquences de 67,0 à 254,1 Hz. DCS : 104 codes, normal (`N`) ou inversé (`I`). L'indice dans la table est la valeur transmise. Tables dans `canaux.json`.

## 6. Messages hors réseau
Charge : `00 02 04 01 <type> <id BE32> 00 <expéditeur 16 octets> …` (`02 04` = type et groupe, `01` = sous-commande « message »).

| Type | Valeur |
|---|---|
| texte début / fragment | `01` / `02` |
| voix début / fragment | `03` / `04` |
| image début / fragment | `05` / `06` |

- **Expéditeur** : 16 octets UTF-8, complétés d'espaces. Il est **déclaré**, jamais authentifié.
- **Texte court** (≤ 180 octets) : un seul message, `longueur LE16, 01, 00, texte`.
- **Texte long** : message de début (`longueur du flux LE16, nombre de morceaux, 00`), puis des fragments de 131 octets : `00 02 04 01 02 <id> <n° BE16> 00 <données>`. Limite de l'application officielle : 1000 octets UTF-8.
- **Voix** : trames AMR de 12 octets, fragments de 132 octets ; début : `longueur LE16, nombre de fragments LE16, durée en secondes LE16`. Durée officielle : 0,6 à 15 s.
- **Image** : JPEG de 300 px au plus, qualité 75, fragments de 132 octets ; début : `longueur LE16, nombre de fragments, 00, largeur LE16, hauteur LE16` (dimensions de l'image d'origine après rotation).
- **Session** : l'application officielle envoie `00 02 04 07 01` (« CHAT SESSION ON ») en entrant dans la messagerie, et `…07 00` en sortant. Elle **refuse** d'ouvrir la messagerie tant que le **Dual Watch** ou **Smart Link** est activé. Avec le Dual Watch désactivé et la session ouverte, une position envoyée en USB a été reçue par l'application officielle (13/10/2026). *Non déterminé* : si ces deux conditions sont nécessaires (le premier essai, sans elles, n'a pas pu être observé : le récepteur était en USB).
- **Accusé** : `82 04 01 00` après chaque trame. L'émetteur attend l'accusé avant d'envoyer la suivante et renvoie en cas de perte.
- **Réassemblage** : tampon par identifiant, expiration de 120 s, 64 messages en attente au plus.

Divergence connue : le décodeur Kotlin lit les données de fragment à l'offset 8, celui d'`at2-bridge` à l'offset 9 (octet de remplissage `00`). L'encodeur et le décodeur de ce dernier sont cohérents entre eux, mais l'écart avec l'officiel est **à clarifier**.

Vecteurs : `messages.json`.

### 6.1 Positions et SOS
Il n'y a **pas de type « position » dans le protocole** : une position est un message texte avec une convention. L'application officielle :
- position : `<lat>*-#-*-#-*-#-*<lon>`
- SOS : `<message>#-*-#-*-#-*-#<lat>*-#-*-#-*-#-*<lon>`
Coordonnées décimales, 6 décimales au plus, zéros finaux supprimés. `at2-bridge` utilise à la place `📍 <lat>,<lon>`, **incompatible** : At2-Radio adoptera le format officiel.

## 7. PTT
Séquence d'émission de l'application officielle :
1. À l'entrée de la page PTT, six messages : requêtes `01 02 0D`, `01 02 0F`, `01 02 0E`, `01 02 02 01 01 00 01 01 00`, `01 03 04`, et session activée `02 04 07 01` (dans l'ordre : `0D`, session, `0F`, `0E`, canal courant, `0304`).
2. Appui : `02 04 02 01` (prise de porteuse), pause de 20 ms.
3. Audio : paquets `02 04 03 00 00 <5 × 12 octets>`, un paquet toutes les 100 ms ; dernier paquet de 4 trames possible.
4. Relâchement : `02 04 02 00`.

Audio : AMR-NB, mode MR475, 8 kHz, trames de 20 ms = 160 échantillons 16 bits = 320 octets en entrée, 12 octets codés (sans l'octet d'en-tête du flux IETF). Réception : mêmes paquets, 12 octets à décoder par trame.

`at2-bridge` n'envoie **pas** l'étape 1 (sauf la session). Hypothèse non vérifiée sur le PTT analogique : voir §9.

Vecteurs : `ptt.json`.

## 8. Divergences constatées entre `at2-bridge` et l'application officielle
| Commande | Officiel | `at2-bridge` |
|---|---|---|
| Nom de l'appareil | `00 02 03 01 <nom>` | `00 03 01 <nom>` |
| Smart Link, écriture | `00 02 04 09 <v>` | `00 04 09 <v>` |
| Smart Link, requête | `00 01 04 09` | `00 04 09` |
| Position / SOS | séparateurs `*-#-*…` | `📍 lat,lon` |
| Amorçage PTT | 6 requêtes | session seulement |

Les trois premières étaient la même erreur que celle déjà corrigée pour le changement de canal (type omis). **Smart Link (écriture et requête) est confirmé corrigé sur matériel** ; le nom reste à confirmer.

## 9. Statut de chaque élément
| Élément | Statut |
|---|---|
| Trames, CRC | testé (vecteurs, 6 captures réelles) |
| Lecture de canaux | **confirmé sur matériel** |
| Écriture de canaux | **confirmée sur matériel (USB)** : canal 19 vide, écriture de 446,1 MHz relue à l'identique, puis remis à vide ; canal 5 réécrit à l'identique |
| Lecture de 30 canaux, 12 réglages | **confirmé sur matériel (USB)**, 30/30 canaux et 12/12 réglages, par le script et par la page de programmation |
| Page de programmation (service + navigateur) | **confirmée de bout en bout sur matériel (USB)** : connexion, lecture, écriture vérifiée du canal 19, réglages relus |
| Position, émission (USB) | **confirmée sur matériel (13/10/2026)** : envoyée depuis le serveur par USB, reçue et affichée comme une localisation par l'application officielle (radio B en Bluetooth). Conditions de l'essai : Dual Watch désactivé, session de messagerie ouverte (`04 07 01`) |
| Messages texte, émission (USB) | **confirmée sur matériel (13/10/2026)** : « Test A vers appli » envoyé par USB, reçu par l'application officielle |
| Messages texte et image, émission depuis la page (USB) | **confirmée sur matériel (13/10/2026)** : texte et image envoyés depuis l'écran Messagerie, reçus par l'application officielle |
| Émission de voix PTT (USB, canal numérique) | **confirmée sur matériel (13/10/2026)** : amorçage officiel (cinq requêtes + session `04 07 01`, **avec 120 ms de pause entre chaque commande**), prise de porteuse acquittée (`82 04 02 00`), paquets de voix ; un son est reçu par l'appli officielle sur l'autre radio. Sans pause entre les commandes d'amorçage, la radio ne répondait à rien. Intelligibilité du son à préciser |
| Requête `01 03 04` | réponse `81 03 04 48` : probablement le **niveau de batterie** (0x48 = 72 %), à confirmer |
| Réception de voix PTT par l'USB | **confirmée sur matériel (13/10/2026)** : 77 paquets (PTT physique de l'autre radio) et 93 paquets (PTT de l'appli officielle) `02 04 03 00 00` + 5 trames AMR de 12 octets ; le décodage en son (fichier WAV) reste à valider à l'écoute |
| Bluetooth (connexion, lecture des canaux et des réglages) | **confirmé sur matériel (13/10/2026)**, depuis un PC Windows, `bleak` |
| Réception de messages texte par le Bluetooth | **confirmée sur matériel** : quatre textes envoyés par l'application officielle reçus et décodés, avec l'expéditeur déclaré |
| Réception d'une image par le Bluetooth | **confirmée sur matériel** : JPEG de 70 fragments réassemblé, enregistré et affiché correctement (13/10/2026) |
| Réception de messages texte par l'USB | **non relayée par la radio (trois essais, 13/10/2026)** : textes envoyés depuis l'appli officielle, session ouverte, Dual Watch désactivé ; aucune trame reçue, ni valide ni rejetée (29 logs sans trame corrompue), alors que la voix remontait. La réception du texte passe vraisemblablement par le Bluetooth seulement |
| Messages texte | **confirmé de bout en bout** |
| Messages voix, image | implémenté, **non vérifié** |
| PTT numérique | **confirmé** |
| PTT analogique | **non pris en charge par l'application officielle elle-même** (« PTT mode does not support non-digital channels ») : ce n'est pas un défaut du pont. L'émission analogique se fait avec le bouton PTT physique de la radio |
| Volume, squelch, TOT, VOX, TX, bruit, tonalité, langue | acquitté seulement |
| Dual Watch, intervalle TX | porté de l'officiel, jamais relu |
| Smart Link, requête | **confirmé sur matériel (USB)** : la requête officielle `00 01 04 09` reçoit une réponse (l'ancienne forme du pont n'en recevait pas) |
| Smart Link, écriture | **confirmé sur matériel (USB)** : `00 02 04 09 01` bascule l'état, relu `True` puis remis |
| Nom de l'appareil | commande officielle `00 02 03 01 <nom>`, envoyée sur matériel, effet **à confirmer** (non relisable) |
| Bouton PTT principal | officiel, non porté |
| Position / SOS | convention ; format officiel à adopter |
