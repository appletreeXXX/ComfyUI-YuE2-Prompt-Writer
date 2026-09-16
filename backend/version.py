"""Single source of truth for the extension version.

``pyproject.toml`` and ``__init__.py`` both read this value, so a release only
needs to change it in one place.
"""

VERSION = "0.3.0"

__all__ = ["VERSION"]
