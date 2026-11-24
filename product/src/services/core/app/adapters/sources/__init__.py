"""Adapters that turn local files and supported links into normalized content."""

from .link import LinkImportError, prepare_link_import
from .local import LocalImportError, prepare_local_import

__all__ = ["LinkImportError", "LocalImportError", "prepare_link_import", "prepare_local_import"]
