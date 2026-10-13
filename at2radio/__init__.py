"""At2-Radio : bibliothèque pour piloter la radio Baofeng / Alervites AT2."""
from .errors import DeliveryError, NotConnectedError, RadioError, RadioTimeoutError
from .protocole.channel import ChannelConfig
from .radio import ChannelWriteResult, Message, PttSession, PttVoice, Radio, RadioState

__version__ = "0.1.0.dev0"
__all__ = ["Radio", "RadioState", "Message", "PttVoice", "PttSession", "ChannelConfig", "ChannelWriteResult",
           "RadioError", "NotConnectedError", "RadioTimeoutError", "DeliveryError"]
