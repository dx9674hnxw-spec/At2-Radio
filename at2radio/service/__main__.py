"""``python -m at2radio.service`` : lance le service local."""
from __future__ import annotations

import argparse
import sys

from . import auth


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="at2radio.service", description="Service local At2-Radio (API v1).")
    p.add_argument("--host", default="127.0.0.1", help="adresse d'écoute (127.0.0.1 par défaut : machine locale seulement)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--history", metavar="FICHIER", help="active l'historique des messages (SQLite)")
    p.add_argument("--no-key", action="store_true", help="pas de clé d'API (refusé hors écoute locale)")
    p.add_argument("--cors-origin", action="append", default=[], help="origine autorisée (répétable)")
    a = p.parse_args(argv)

    loopback = a.host in auth.LOOPBACK
    if a.no_key and not loopback:
        print("Refusé : sans clé d'API, le service ne peut écouter que sur 127.0.0.1.", file=sys.stderr)
        return 2
    key = None
    if not a.no_key:
        key, created = auth.load_or_create_key()
        if created:
            print(f"Clé d'API créée dans {auth.default_key_path()} (affichée une seule fois) :\n  {key}")

    import uvicorn

    from .app import create_app
    from .history import History
    from .manager import RadioManager

    manager = RadioManager(History(a.history) if a.history else None)
    print(f"At2-Radio : http://{a.host}:{a.port}/  (documentation : /v1/docs)")
    if not loopback:
        print("ATTENTION : le service est ouvert au réseau. Utiliser HTTPS ou un réseau de confiance.")
    uvicorn.run(create_app(manager, key, a.cors_origin or None), host=a.host, port=a.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
