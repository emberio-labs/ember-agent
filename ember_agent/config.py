"""Чтение и валидация TOML-конфигурации агента.

Формат конфигурации описан в ``config.example.toml`` в корне проекта.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Имя файла конфигурации, который CLI ищет по умолчанию.
DEFAULT_CONFIG_FILE = "config.toml"

#: Промпт, используемый, если в конфигурации ничего не задано.
DEFAULT_SYSTEM_PROMPT = "Ты полезный и краткий помощник."

PROVIDER_MOCK = "mock"
PROVIDER_OPENAI = "openai"
VALID_PROVIDERS: frozenset[str] = frozenset({PROVIDER_MOCK, PROVIDER_OPENAI})

TRANSPORT_STDIO = "stdio"
TRANSPORT_HTTP = "http"
VALID_TRANSPORTS: frozenset[str] = frozenset({TRANSPORT_STDIO, TRANSPORT_HTTP})


class ConfigError(ValueError):
    """Ошибка конфигурации агента (файл, TOML-синтаксис, значения)."""


def _require_str(data: dict[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"Поле '{key}' должно быть строкой, получено {type(value).__name__}")
    return value


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"Поле '{key}' должно быть строкой, получено {type(value).__name__}")
    return value


def _str_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"Поле '{key}' должно быть списком строк")
    return list(value)


def _str_dict(data: dict[str, Any], key: str) -> dict[str, str]:
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ConfigError(f"Поле '{key}' должно быть таблицей строк ({{key = 'value'}})")
    return {str(k): str(v) for k, v in value.items()}


@dataclass
class MCPServerConfig:
    """Описание одного MCP-сервера (stdio-процесс или HTTP-endpoint)."""

    transport: str = TRANSPORT_STDIO
    #: Для transport = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    #: Для transport = "http"
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ProviderConfig:
    """Настройки LLM-провайдера: как и через какую модель агент ходит к LLM."""

    type: str = PROVIDER_MOCK
    #: Модель подключения LLM. Если не задана, провайдер берёт свою модель
    #: по умолчанию (например, "gpt-4o-mini" у OpenAI).
    model: str | None = None
    #: Переменная окружения с API-ключом (для type = "openai").
    api_key_env: str = "OPENAI_API_KEY"
    #: Полный base_url OpenAI-совместимого API (опционально).
    base_url: str | None = None


@dataclass
class AgentConfig:
    """Полная конфигурация агента после чтения TOML-файла."""

    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentConfig:
        agent_section = data.get("agent", {})
        if not isinstance(agent_section, dict):
            raise ConfigError("Секция '[agent]' должна быть таблицей")

        provider_section = data.get("provider", {})
        if not isinstance(provider_section, dict):
            raise ConfigError("Секция '[provider]' должна быть таблицей")

        return cls(
            system_prompt=_require_str(agent_section, "system_prompt", DEFAULT_SYSTEM_PROMPT),
            provider=_parse_provider(provider_section),
            mcp_servers=_parse_mcp_servers(data.get("mcp")),
        )


def _parse_provider(data: dict[str, Any]) -> ProviderConfig:
    provider_type = _require_str(data, "type", PROVIDER_MOCK)
    if provider_type not in VALID_PROVIDERS:
        valid = ", ".join(sorted(VALID_PROVIDERS))
        message = f"Неизвестный тип провайдера {provider_type!r}; ожидается одно из: {valid}"
        raise ConfigError(message)

    return ProviderConfig(
        type=provider_type,
        model=_optional_str(data, "model"),
        api_key_env=_require_str(data, "api_key_env", "OPENAI_API_KEY"),
        base_url=_optional_str(data, "base_url"),
    )


def _parse_mcp_servers(raw: Any) -> list[MCPServerConfig]:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ConfigError("Секция '[mcp]' должна быть таблицей")

    servers_raw = raw.get("servers", [])
    if not isinstance(servers_raw, list):
        raise ConfigError("Поле '[mcp].servers' должно быть списком таблиц ([[mcp.servers]])")

    servers: list[MCPServerConfig] = []
    for index, item in enumerate(servers_raw, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"MCP-сервер #{index} должен быть таблицей")
        transport = _require_str(item, "transport", TRANSPORT_STDIO)
        if transport not in VALID_TRANSPORTS:
            valid = ", ".join(sorted(VALID_TRANSPORTS))
            raise ConfigError(
                f"MCP-сервер #{index}: неизвестный transport {transport!r}; ожидается: {valid}"
            )
        servers.append(
            MCPServerConfig(
                transport=transport,
                command=_optional_str(item, "command"),
                args=_str_list(item, "args"),
                env=_str_dict(item, "env"),
                url=_optional_str(item, "url"),
                headers=_str_dict(item, "headers"),
            )
        )
    return servers


def load_config(path: str | Path) -> AgentConfig:
    """Читает TOML-файл и возвращает валидированную конфигурацию агента.

    Raises:
        ConfigError: файл не найден, некорректный TOML или неверные значения.
    """
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Файл конфигурации не найден: {config_path}")

    with config_path.open("rb") as handle:
        try:
            data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Некорректный TOML в {config_path}: {exc}") from exc

    return AgentConfig.from_dict(data)
