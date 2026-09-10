"""Единый способ печатать сообщения CLI.

Ошибки уходят в stderr и с общим префиксом ``ошибка:``: stdout остаётся чистым
(его читают скрипты), а формат сообщений не разъезжается между командами.
"""

from __future__ import annotations

import sys


def print_error(message: str) -> None:
    """Напечатать ошибку команды в stderr, не засоряя stdout."""
    print(f"ошибка: {message}", file=sys.stderr)
