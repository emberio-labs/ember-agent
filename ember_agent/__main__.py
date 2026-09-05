"""Поддержка запуска как ``python -m ember_agent``."""

from __future__ import annotations

from ember_agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
