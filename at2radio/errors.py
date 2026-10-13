"""Erreurs d'At2-Radio. Les messages sont en français, lisibles tels quels."""


class RadioError(Exception):
    """Erreur de base."""


class NotConnectedError(RadioError):
    """Aucune radio connectée."""


class RadioTimeoutError(RadioError):
    """La radio n'a pas répondu à temps."""


class DeliveryError(RadioError):
    """Un message n'a pas été acquitté par la radio."""
