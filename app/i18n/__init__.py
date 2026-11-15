"""Translation catalog for Portuguese, English, Chitewe and Sena.

Portuguese is the reference catalog. Every supported language carries a
complete set of keys, so switching language never leaves part of the interface
in Portuguese. Chitewe and Sena remain provisional and require native review
before being presented as authoritative translations (see docs/LINGUAS.md).
"""

from __future__ import annotations

from functools import lru_cache

from ._chitewe import _CHITEWE
from ._en import _EN
from ._pt import _PT
from ._sena import _SENA

LANGUAGES: dict[str, dict] = {
    "pt": {"label": "Português", "reviewed": True},
    "en": {"label": "English", "reviewed": True},
    "chitewe": {"label": "Chitewe", "reviewed": False},
    "sena": {"label": "Sena", "reviewed": False},
}

SUPPORTED_LANGUAGES = tuple(LANGUAGES.keys())

TRANSLATIONS: dict[str, dict[str, str]] = {
    "pt": _PT,
    "en": _EN,
    "chitewe": _CHITEWE,
    "sena": _SENA,
}


@lru_cache(maxsize=8)
def get_catalog(lang: str = "pt") -> dict[str, str]:
    """Return the complete catalog for ``lang``.

    Portuguese is merged first so a future key can never break the interface,
    but every supported catalog is expected to carry all reference keys.
    """
    catalog = dict(TRANSLATIONS["pt"])
    if lang in TRANSLATIONS and lang != "pt":
        catalog.update({key: value for key, value in TRANSLATIONS[lang].items() if value})
    return catalog


def translate(key: str, lang: str = "pt") -> str:
    return get_catalog(lang).get(key, key)
