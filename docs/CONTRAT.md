# At2-Radio : contrat du projet (brouillon à relire)

> Décisions du 13/10/2026 intégrées (voir §10). Document de cadrage. Il décrit **ce qu'on va construire**, pas du code. Rien n'est implémenté.
> Les statuts « confirmé / non confirmé » viennent des README des dépôts `at2-bridge` et `at2-bridge_Mobile` ; ils seront revérifiés avant publication.

## 1. Objectif

Publier sur GitHub un **mini service** qui permet à n'importe qui d'utiliser le protocole de la radio **Baofeng / Alervites AT2** pour créer sa propre application, sans refaire la rétro-ingénierie.

Le projet fournit :

1. une **spécification** du protocole, indépendante du langage ;
2. une **bibliothèque** (Python) qui l'implémente ;
3. un **service local** (HTTP + WebSocket) qui expose la bibliothèque à n'importe quel langage ;
4. un module d'**historique** optionnel (SQLite) ;
5. une **page web de programmation** de la radio (canaux et réglages), qui sert aussi de client de référence.

**Périmètre : un portage complet des fonctions de l'application officielle** (voix, image et PTT compris, pas seulement ce qui est déjà confirmé). Ce qui n'est pas encore vérifié sur matériel est publié avec son statut (§6.2), jamais présenté comme fonctionnel.

Hors périmètre : comptes utilisateurs, page d'administration, messagerie et PTT dans une interface. Ce sont des choses que construit l'auteur d'une application par-dessus.

Contexte : usage **hors réseau**. Rien ne doit dépendre d'Internet (ni CDN, ni police, ni service d'authentification en ligne).

## 2. Arborescence prévue (nouveau dépôt)

```
at2-radio/
├─ README.md            (projet « At2-Radio ») premier message envoyé en dix lignes
├─ LICENSE, NOTICE      voir §8
├─ docs/
│  ├─ CONTRAT.md        ce document
│  ├─ PROTOCOLE.md      la spécification (§6)
│  └─ API.md            généré depuis l'OpenAPI du service
├─ vecteurs/            fichiers de test partagés entre implémentations (§6.3)
├─ at2radio/            la bibliothèque (§3)
│  ├─ protocole/        trames, commandes, canaux, messages, PTT
│  ├─ transports/       BLE, USB série
│  └─ radio.py          l'objet Radio (façade)
├─ service/             API HTTP + WebSocket (§5)
├─ historique/          module optionnel SQLite (§5.4)
├─ programmation/       page web de programmation (§7)
└─ tests/
```

Principe : **la bibliothèque ne dépend ni du web ni d'une base de données.** Le service dépend de la bibliothèque, jamais l'inverse.

## 3. Bibliothèque : interface publique

Une seule façade, `Radio`, asynchrone. Une instance = une radio. On peut en créer plusieurs.

### 3.1 Connexion
| Fonction | Rôle |
|---|---|
| `Radio.scan_ble(timeout)` | liste les radios Bluetooth visibles |
| `Radio.list_serial_ports()` | liste les ports USB série |
| `connect_ble(adresse)` / `connect_serial(port)` | connecte la radio |
| `disconnect()` | déconnecte |
| `status` | `déconnectée`, `connexion`, `connectée`, `perdue` |

### 3.2 Canaux (30 emplacements)
| Fonction | Rôle |
|---|---|
| `read_channel(n)` / `read_all_channels()` | lit un canal / les 30 |
| `write_channel(config)` | écrit un canal **puis le relit pour vérifier** (voir §6.2) |
| `write_all_channels(configs)` | écrit les 30, avec vérification |
| `clear_channel(n)` | efface |
| `select_channel(n)` | change le canal actif |
| `parse_cps_xml(octets)` | lit un export XML du logiciel d'origine (ne l'écrit jamais seul) |

`ChannelConfig` : `channel`, `rx_mhz`, `tx_mhz`, `rx_tone`, `tx_tone`, `busy_lock`, `bandwidth_narrow`, `high_power`, `scan_add`, `hop_on`, `mode_digital`, `encrypt_key`. Le nom d'un canal est **local** à l'application (la radio ne le stocke pas).

### 3.3 Réglages de l'appareil
Chaque réglage a un `get_*` et un `set_*` : volume (1–8), squelch (0–9), VOX et sensibilité (1–5), temporisation d'émission (0–240 s), intervalle TX, inhibition TX, réduction de bruit, tonalité de confirmation, langue des annonces, nom de l'appareil, Smart Link, Dual Watch (activation, canaux A et B, focus).

### 3.4 Messages hors réseau
| Fonction | Rôle |
|---|---|
| `send_text(pseudo, texte)` | texte (fragmenté automatiquement) |
| `send_position(pseudo, lat, lon, note)` | position (voir note ci-dessous) |
| `send_sos(pseudo, lat, lon, motif)` | position marquée SOS |
| `send_voice(...)`, `send_image(...)` | **expérimentaux** |

Note : le protocole **n'a pas de type « position » structuré** ; une position est du texte formaté (📍 / 🆘). La bibliothèque fournit l'encodage et le décodage, documentés comme une convention.

### 3.5 PTT
| Fonction | Rôle |
|---|---|
| `ptt_session()` | ouvre une session d'émission ; `feed_pcm_frame(...)`, `close()` |
| `on_ptt_voice(callback)` | audio reçu (AMR-NB décodé en PCM 8 kHz) |

L'émission exige un **appel explicite** : jamais déclenchée par un effet de bord.

### 3.6 Événements
Posés avec `radio.on(<événement>, callback)` :

| Événement | Contenu |
|---|---|
| `connection` | nouvel état de connexion |
| `message` | message complet reçu : `type` (`text`/`position`/`sos`/`voice`/`image`), `sender` *(déclaré, non vérifié)*, `channel`, `payload`, `received_at` |
| `ptt_state` | quelqu'un parle sur le canal (`rx`) / on émet (`tx`) / veille |
| `ptt_voice` | trame audio reçue |
| `frame` | trame brute (diagnostic) |
| `error` | erreur lisible, en français et en anglais |

## 4. Modèle de données de l'historique (optionnel)

SQLite, mode WAL. Une seule table utile au départ :

`messages` : `id`, `received_at`, `radio_id`, `direction` (`in`/`out`), `channel`, `type`, `sender_declared`, `text`, `lat`, `lon`, `blob` (image/voix), `delivery` (`sent`/`acked`/`failed`).

Règle : un message reçu a un expéditeur **déclaré** ; seul un message envoyé par le service a une origine certaine. Pas de table d'utilisateurs.

## 5. Service local : API v1

Principes : écoute sur `127.0.0.1` par défaut ; ouverture au réseau **explicite** ; clé d'API **incluse dès la v1** (en-tête `Authorization`, générée au premier lancement, obligatoire dès que le service écoute hors `127.0.0.1`) ; contrat décrit en **OpenAPI** ; version dans l'URL (`/v1`).

### 5.1 Connexion
`GET /v1/radios` · `POST /v1/radios/ble/scan` · `POST /v1/radios/{id}/connect` · `POST /v1/radios/{id}/disconnect` · `GET /v1/radios/{id}/status`

### 5.2 Canaux et réglages
`GET /v1/radios/{id}/channels` · `PUT /v1/radios/{id}/channels` · `GET|PUT|DELETE /v1/radios/{id}/channels/{n}` · `POST …/channels/{n}/select` · `POST /v1/cps-xml/parse`
`GET|PUT /v1/radios/{id}/settings/{nom}` (un réglage) · `GET|PUT /v1/radios/{id}/settings` (tous)

### 5.3 Messages, PTT, événements
`POST /v1/radios/{id}/messages/text|position|sos` · `GET /v1/radios/{id}/messages` (historique si activé)
`WS /v1/radios/{id}/events` : flux des événements du §3.6, en JSON
`WS /v1/radios/{id}/ptt` : audio PCM 8 kHz ↔ AMR (envoi et réception)

### 5.4 Erreurs
Format unique : `{ "error": { "code": "…", "message": "…", "details": … } }`, jamais de trace interne ni de donnée personnelle.

## 6. Spécification du protocole (`PROTOCOLE.md`)

### 6.1 Plan
1. Transports : UUID du service BLE et des caractéristiques, USB série (115200 bauds).
2. **Deux dialectes de trames** (marqueurs de début/fin communs) et comment les distinguer.
3. Trame : `AA 55` … charge … CRC16-CCITT … `77 EE`.
4. Charge utile : famille, commande, corps ; familles requête / réglage / appareil / extension ; accusé = famille | 0x80.
5. Réglages : tableau octet par octet de chaque commande.
6. Canaux : enregistrement de 24 octets (lecture) / 23 octets (écriture), champs, tonalités CTCSS/DCS, fréquences.
7. Messages hors réseau : en-tête, expéditeur (16 octets), types (texte/voix/image, début + fragments), tailles de fragment, identifiant, accusé, réassemblage, délai d'expiration.
8. PTT : commandes de prise et de fin de porteuse, paquets audio (5 trames AMR par paquet, cadence), session hors réseau.
9. Codec audio : AMR-NB, mode MR475, trames de 12 octets.

### 6.2 Statut de chaque élément (à revérifier avant publication)
| Élément | Statut annoncé dans les dépôts actuels |
|---|---|
| Trames, CRC, deux dialectes | implémenté, testé |
| Lecture de canaux | **confirmé sur matériel** (6 lectures réelles ; l'ancienne hypothèse de 25 octets était fausse) |
| Écriture de canaux | **non confirmée par lecture en retour** → toujours relire après écriture |
| Messages texte hors réseau | **confirmé** de bout en bout |
| Messages voix / image | implémenté, **non vérifié** |
| PTT sur canal numérique | **confirmé** |
| PTT sur canal analogique | **ne fonctionne pas** : la radio n'émet aucune porteuse (commande manquante probable) |
| Réglages (squelch, VOX, TOT…) | commande envoyée et acquittée, **jamais relue indépendamment** |
| Dual Watch, langue, intervalle TX | portés de l'application de référence, jamais relus |

Règle de rédaction : **un accusé de réception de trame ne prouve pas que la radio a appliqué la commande.** Chaque fonction de la spec porte l'un des statuts : `confirmé`, `acquitté seulement`, `non vérifié`, `ne fonctionne pas`.

### 6.3 Vecteurs de test partagés
Des fichiers de données (`vecteurs/*.json`) : entrée en hexadécimal, résultat attendu. Chaque implémentation (Python, Swift de l'app iOS, autres) les exécute. Ils incluent les 6 lectures de canaux capturées sur la radio réelle.

## 7. Page de programmation

Une page unique, mêmes composants et même design que le kit de l'app (sombre, français, tutoiement), **servie par le service**, sans dépendance externe.

**En-tête :** choix de la radio, bouton Connecter, pastille d'état (connectée / perdue / hors ligne).

**Bloc Canaux** (tableau de 30 lignes) :
| Colonne | Contrôle |
|---|---|
| Canal | numéro (lecture seule) |
| Nom | texte, local à la page (non écrit dans la radio) |
| RX MHz / TX MHz | nombre à 4 décimales, validé (plage, pas de canal) |
| Ton RX / Ton TX | liste CTCSS / DCS / désactivé |
| Bande étroite, Puissance haute, Scan, Numérique, Busy lock, Saut de fréquence | cases à cocher |
| Clé de chiffrement | nombre |
| Action | « Écrire ce canal » |

Boutons : **Lire les 30**, **Écrire les 30**, **Importer un export XML**. Après chaque écriture : relecture et message du résultat (« Enregistré et vérifié » ou « Écrit, mais la radio renvoie autre chose »). Avertissement fixe tant que l'écriture n'est pas confirmée sur matériel.

**Bloc Réglages** (trois groupes) : Audio (volume, squelch, réduction de bruit, tonalité) · Émission (temporisation, intervalle, inhibition) · Appareil (nom, langue, Smart Link, VOX et sensibilité, Dual Watch). Un bouton **Appliquer** envoie tout, un bouton **Relire** recharge ; une pastille « modifications non appliquées » est affichée.

**Bloc Diagnostic :** journal des trames, filtre, copie, export, trame brute (réservé aux tests).

Aide : une phrase sous chaque réglage non évident. Aucun terme technique brut dans les messages d'erreur.

## 8. Licence, provenance, sécurité

- Le protocole provient de la rétro-ingénierie de l'application Android `Baofeng-ALERVITES-AT2-Android` (Apache-2.0) : conserver `NOTICE` et les attributions. Le codec AMR (opencore-amr) est un composant tiers : conserver sa licence. **Licence retenue : Apache-2.0** (le code repris d'AT2 HT est sous Apache-2.0 ; celui de at2-bridge, sous MIT, s'y combine). Modifiable tant que le dépôt est privé.
- Mention claire : **projet communautaire, non affilié à Baofeng/Alervites**.
- Le service écoute en local par défaut, ne journalise ni secret ni donnée personnelle, et n'émet jamais sans demande explicite.
- **Hors réseau :** aucun CDN, aucune police externe ; si une carte est un jour ajoutée, tuiles servies localement.

## 9. Jalons

1. ✅ Valider ce document.
2. ✅ **Inventaire des fonctions officielles** (fait : voir `INVENTAIRE.md`) : lister toutes les fonctions de l'application Android d'origine (`At2Commands.kt` et le reste), les comparer à ce que `at2-bridge` implémente, et en déduire la liste des **écarts à porter** (périmètre complet).
3. Nouveau dépôt `At2-Radio`, squelette, licence et attributions.
4. Spécification `PROTOCOLE.md` + vecteurs de test.
5. 🟡 Bibliothèque `at2radio` (en cours) : façade `Radio` multi-radios, un seul codec de trame, vérification après écriture, format de position officiel. Reste : Smart Link / bouton PTT sur matériel, pipeline d'image, MTU BLE, amorçage à la connexion.
6. Service v1 + OpenAPI + clé d'API.
7. Page de programmation, avec mode Web Bluetooth sans service.
8. Historique SQLite (optionnel).
9. Documentation, exemples, première version publiée.

## 10. Décisions

| # | Question | Décision |
|---|---|---|
| 1 | Nom du dépôt | **At2-Radio** (licence encore à valider, §8) |
| 2 | Périmètre v1 | **Portage complet des fonctions officielles**, voix / image / PTT inclus ; statut de maturité affiché pour chacune |
| 3 | Plusieurs radios | **Oui, dès la v1** (une instance `Radio` par appareil, identifiants `{id}` dans l'API) |
| 4 | Clé d'API | **Oui, dès la v1** |
| 5 | Web Bluetooth sans service | **Oui**, comme option de la page de programmation |

Point d'attention : le PTT sur canal **analogique** ne fonctionne pas aujourd'hui (aucune porteuse émise). « Portage complet » impose de reprendre l'application officielle pour trouver la commande manquante : c'est une tâche de l'étape 2, pas une promesse de la v1.
