"""emberio-labs-ember-agent — настраиваемый агент на базе ``ember`` (emberio-labs-ember).

Пакет даёт:
- CLI ``ember-agent run`` (команда короткая) с интерактивным диалогом или разовым запросом;
- загрузку конфигурации агента из TOML-файла;
- сборку провайдера и MCP-инструментов в готового агента.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("emberio-labs-ember-agent")
except PackageNotFoundError:  # пакет не установлен (запуск из исходников)
    __version__ = "0.2.0"
