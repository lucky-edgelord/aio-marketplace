"""Exception hierarchy. Provider errors are caught by the bot and turned into friendly replies."""


class KitsuneError(Exception):
    """Base class for Kitsune errors."""


class ConfigError(KitsuneError):
    """Missing or invalid configuration."""


class ProviderError(KitsuneError):
    """A backend (LLM, speech, images...) failed."""


class ChatError(ProviderError):
    pass


class SpeechError(ProviderError):
    pass


class ImageError(ProviderError):
    pass


class RenderError(KitsuneError):
    pass
