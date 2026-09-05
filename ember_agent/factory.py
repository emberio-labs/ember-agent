"""Сборка агента ``ember`` из конфигурации ``ember_agent``.

Фабрика скрывает детали библиотеки ``ember``: провайдеров, MCP-клиенты
и передачу параметров в ``Agent``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

from ember import Agent, MCPClient, MockProvider, OpenAIProvider

from ember_agent.config import (
    PROVIDER_MOCK,
    PROVIDER_OPENAI,
    TRANSPORT_HTTP,
    TRANSPORT_STDIO,
    AgentConfig,
    ConfigError,
    MCPServerConfig,
    ProviderConfig,
)


def build_provider(config: ProviderConfig) -> MockProvider | OpenAIProvider:
    """Создаёт провайдера ``ember`` по конфигурации."""
    if config.type == PROVIDER_MOCK:
        return MockProvider()

    if config.type == PROVIDER_OPENAI:
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise ConfigError(
                f"Для провайдера 'openai' задайте переменную окружения "
                f"{config.api_key_env!r} (или укажите другую в [provider].api_key_env)"
            )
        kwargs: dict[str, str] = {}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        return OpenAIProvider(api_key=api_key, **kwargs)

    raise ConfigError(f"Неизвестный тип провайдера: {config.type!r}")  # не должно достигаться


def _open_mcp_client(config: MCPServerConfig) -> MCPClient:
    """Создаёт (ещё не открытый) MCP-клиент по конфигурации сервера."""
    if config.transport == TRANSPORT_STDIO:
        if not config.command:
            raise ConfigError("MCP-сервер с transport='stdio': укажите 'command'")
        kwargs: dict[str, Any] = {"command": config.command, "args": list(config.args)}
        if config.env:
            kwargs["env"] = dict(config.env)
        return MCPClient.stdio(**kwargs)

    if config.transport == TRANSPORT_HTTP:
        if not config.url:
            raise ConfigError("MCP-сервер с transport='http': укажите 'url'")
        kwargs = {"url": config.url}
        if config.headers:
            kwargs["headers"] = dict(config.headers)
        return MCPClient.http(**kwargs)

    raise ConfigError(f"Неизвестный transport MCP: {config.transport!r}")  # не должно достигаться


@contextmanager
def build_agent(config: AgentConfig) -> Iterator[Agent]:
    """Создаёт агента ``ember`` из конфигурации.

    Контекстный менеджер: пока контекст открыт, живут MCP-клиенты
    (stdio-процессы и HTTP-соединения), после выхода — корректно закрываются.
    """
    provider = build_provider(config.provider)

    with ExitStack() as stack:
        tools: list[Any] = []
        for server in config.mcp_servers:
            client = _open_mcp_client(server)
            stack.enter_context(client)
            tools.extend(client.list_tools())

        kwargs: dict[str, Any] = {"provider": provider, "system_prompt": config.system_prompt}
        if config.model:
            kwargs["model"] = config.model
        if tools:
            kwargs["tools"] = tools

        yield Agent(**kwargs)
