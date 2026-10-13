# At2-Radio

Bibliothèque, service local et page de programmation pour la radio **Baofeng / Alervites AT2**, pour construire sa propre application sans refaire la rétro-ingénierie du protocole.

> **Projet communautaire, non affilié à Baofeng ni à Alervites.** Le protocole est issu de la rétro-ingénierie. Tout ce qui n'est pas confirmé sur matériel est marqué comme tel dans [`docs/PROTOCOLE.md`](docs/PROTOCOLE.md) §9.
>
> **État : développement.** La bibliothèque, le service HTTP et la page de programmation sont écrits et testés sur un faux transport (119 tests), mais **rien n'a encore été essayé sur une vraie radio**. Voir [`exemples/essai_materiel.py`](exemples/essai_materiel.py).

## Premier message

```python
import asyncio
from at2radio import Radio

async def main():
    radio = Radio("ma-radio")
    radio.on("message", lambda m: print(m.sender, m.type, m.text))
    await radio.connect_ble("AA:BB:CC:DD:EE:FF")      # pip install "at2radio[ble]"
    await radio.send_text("ALPHA", "Bonjour")
    await asyncio.sleep(30)

asyncio.run(main())
```

Une instance `Radio` par appareil ; on peut en créer plusieurs. Lire un canal, écrire avec relecture automatique, régler le volume :

```python
cfg = await radio.read_channel(1)
res = await radio.write_channel(cfg)      # relit et compare : res.verified, res.differences
await radio.set("volume", 5)
```

## Service local et page de programmation

```bash
pip install -e ".[ble,service]"
python -m at2radio.service          # http://127.0.0.1:8765/  (documentation de l'API : /v1/docs)
```

La page de programmation (connexion, canaux, réglages, journal des trames) est servie sur `/`. Le service n'écoute que sur `127.0.0.1` par défaut. Une clé d'API est créée au premier lancement (`~/.config/at2radio/api-key`) ; elle est obligatoire dès que le service écoute ailleurs. Option `--history fichier.db` : historique des messages en SQLite.

## Tests

```bash
pip install -e ".[test]" && pytest
```

## Documentation

- [`docs/CONTRAT.md`](docs/CONTRAT.md) : périmètre, API, jalons.
- [`docs/PROTOCOLE.md`](docs/PROTOCOLE.md) : spécification du protocole et statut de chaque élément.
- [`docs/INVENTAIRE.md`](docs/INVENTAIRE.md) : fonctions de l'application officielle et écarts.
- [`vecteurs/`](vecteurs/) : fichiers de test partagés entre implémentations (Python, Swift…).

## Licence

Apache-2.0, voir [`LICENSE`](LICENSE) et [`NOTICE`](NOTICE). Le codec AMR (libopencore-amrnb) n'est pas inclus.
