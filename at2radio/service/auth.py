"""Clé d'API : générée au premier lancement, jamais écrite dans les journaux (sauf à sa création)."""
from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
ENV_VAR = "AT2RADIO_API_KEY"


def default_key_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "at2radio" / "api-key"


def load_or_create_key(path: Path | None = None) -> tuple[str, bool]:
    """Retourne ``(clé, créée_maintenant)``. Priorité : variable d'environnement, puis fichier."""
    env = os.environ.get(ENV_VAR)
    if env:
        return env, False
    path = path or default_key_path()
    if path.exists():
        return path.read_text().strip(), False
    key = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    return key, True


def check(expected: str | None, given: str | None) -> bool:
    if expected is None:
        return True
    return bool(given) and hmac.compare_digest(expected.encode(), given.encode())


def bearer(header: str | None) -> str | None:
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return None
