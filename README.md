# At2-Radio

Bibliothèque, service local et page de programmation pour la radio **Baofeng / Alervites AT2**, pour construire sa propre application sans refaire la rétro-ingénierie du protocole.

> **Projet communautaire, non affilié à Baofeng ni à Alervites.** Le protocole est issu de la rétro-ingénierie. Tout ce qui n'est pas confirmé sur matériel est marqué comme tel dans [`docs/PROTOCOLE.md`](docs/PROTOCOLE.md) §9.
>
> **État : développement.** La bibliothèque est écrite et testée sur un faux transport (103 tests) mais **n'a pas encore été essayée sur une vraie radio**. Le service HTTP et la page de programmation ne sont pas commencés.

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

## Tests

```bash
pip install -e ".[test]" && pytest
```

## Documentation

- [`docs/CONTRAT.md`](docs/CONTRAT.md) : périmètre, API, jalons.
- [`docs/PROTOCOLE.md`](docs/PROTOCOLE.md) : spécification du protocole et statut de chaque élément.
- [`docs/INVENTAIRE.md`](docs/INVENTAIRE.md) : fonctions de l'application officielle et écarts.
- [`vecteurs/`](vecteurs/) : fichiers de test partagés entre implémentations (Python, Swift…).
