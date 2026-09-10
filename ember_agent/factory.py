"""Сборка агента ``ember`` из конфигурации ``ember_agent``.

Фабрика скрывает детали библиотеки ``ember``: провайдеров, MCP-клиенты,
память и передачу параметров в ``Agent``.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import datetime
from typing import Any

from ember import (
    Agent,
    FileMemory,
    FunctionTool,
    MCPClient,
    Memory,
    MockProvider,
    OpenAIProvider,
)

from ember_agent.config import (
    MEMORY_FILE,
    PROVIDER_MOCK,
    PROVIDER_OPENAI,
    TRANSPORT_HTTP,
    TRANSPORT_STDIO,
    AgentConfig,
    ConfigError,
    MCPServerConfig,
    MemoryConfig,
    ProviderConfig,
)

#: Вызывается перед исполнением инструмента: имя и аргументы из tool_calls.
type ToolCallHook = Callable[[str, dict[str, Any]], None]
#: Вызывается после исполнения инструмента: результат (или исключение).
type ToolResultHook = Callable[[str, Any], None]
#: Фабрика хранилища памяти: конфигурация → реализация интерфейса ``Memory``.
type MemoryFactory = Callable[[MemoryConfig], Memory]


def build_provider(config: ProviderConfig) -> MockProvider | OpenAIProvider:
    """Создаёт провайдера ``ember`` по конфигурации.

    Модель задаётся провайдеру: в ``ember`` именно провайдер подставляет
    свою модель по умолчанию, когда агент её не переопределил.
    """
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
        if config.model:
            kwargs["model"] = config.model
        if config.base_url:
            kwargs["base_url"] = config.base_url
        return OpenAIProvider(api_key=api_key, **kwargs)

    raise ConfigError(f"Неизвестный тип провайдера: {config.type!r}")  # не должно достигаться


def _build_file_memory(config: MemoryConfig) -> Memory:
    """Файловое хранилище ``ember``: JSONL, по файлу на сессию."""
    return FileMemory(config.directory)


#: Реестр известных хранилищ памяти: ключ — значение ``[memory] type``.
#: Программный код может зарегистрировать здесь свою реализацию ``Memory``
#: (Redis, SQLite, ... — интерфейс публичный); для CLI значения ограничены
#: ``config.VALID_MEMORY_TYPES``, чтобы конфиг не мог подсунуть произвольное.
_MEMORY_FACTORIES: dict[str, MemoryFactory] = {
    MEMORY_FILE: _build_file_memory,
}


def build_memory_store(config: MemoryConfig) -> Memory:
    """Создаёт хранилище памяти, не глядя на флаг ``enabled``.

    Нужно командам ``ember-agent memory``: они работают с уже сохранёнными
    сессиями и должны читать/удалять их даже тогда, когда память в конфигурации
    выключена (``enabled = false``).

    Args:
        config: Секция ``[memory]`` конфигурации.

    Raises:
        ConfigError: запрошен незарегистрированный тип хранилища.
    """
    factory = _MEMORY_FACTORIES.get(config.type)
    if factory is None:
        valid = ", ".join(sorted(_MEMORY_FACTORIES))
        raise ConfigError(f"Неизвестный тип памяти {config.type!r}; ожидается одно из: {valid}")
    return factory(config)


def build_memory(config: MemoryConfig) -> Memory | None:
    """Создаёт хранилище памяти по конфигурации.

    Возвращает ``None``, если память выключена: тогда агент работает как
    раньше — ничего не пишет на диск и не подтягивает прошлые сессии.
    Реализацию выбирает ``config.type`` через реестр ``_MEMORY_FACTORIES``,
    поэтому ни конфиг, ни вызывающий код не зависят от конкретного класса:
    ``FileMemory`` — реализация по умолчанию, а не часть контракта.

    Args:
        config: Секция ``[memory]`` конфигурации.

    Raises:
        ConfigError: запрошен незарегистрированный тип хранилища.
    """
    if not config.enabled:
        return None
    return build_memory_store(config)


#: Формат временной части id новой сессии.
_SESSION_ID_TIME_FORMAT = "%Y%m%d-%H%M%S"

#: Сколько случайных байт добавлять к id новой сессии.
_SESSION_ID_SUFFIX_BYTES = 3


def new_session_id() -> str:
    """Сгенерировать id новой сессии: ``20260910-221503-4f1a2b``.

    Время идёт первым, поэтому сессии сортируются по имени файла; случайный
    суффикс разводит запуски, начавшиеся в одну секунду, — иначе два
    одновременных запуска писали бы в один файл сессии.
    """
    stamp = datetime.now().strftime(_SESSION_ID_TIME_FORMAT)
    return f"{stamp}-{secrets.token_hex(_SESSION_ID_SUFFIX_BYTES)}"


def resolve_session_id(config: MemoryConfig) -> str | None:
    """Определить id сессии для текущего запуска.

    ``None`` — память выключена. Если ``[memory] session_id`` задан явно, он
    означает «продолжить эту сессию» и возвращается как есть. Если не задан —
    генерируется новый id: по умолчанию каждый запуск начинает отдельный
    диалог, а прошлые сессии остаются доступны через recall (их подмешивает
    ``ember`` при ответе).

    Args:
        config: Секция ``[memory]`` конфигурации.
    """
    if not config.enabled:
        return None
    return config.session_id or new_session_id()


def wrap_tool(
    tool: FunctionTool,
    *,
    on_tool_call: ToolCallHook | None = None,
    on_tool_result: ToolResultHook | None = None,
) -> FunctionTool:
    """Обернуть ``FunctionTool`` прокси с логированием вызовов.

    В ``Agent`` (ember) нет событий/хуков, но инструменты вызываются как
    ``tool.func(**arguments)``. Прокси сохраняет ``name``/``description``/
    ``parameters`` оригинала (индексация ``Agent`` по имени не меняется),
    а его ``func`` перед делегированием зовёт ``on_tool_call``, после —
    ``on_tool_result`` (с результатом или перехваченным исключением).

    Если колбэки не переданы, возвращается исходный инструмент без обёртки.
    """
    if on_tool_call is None and on_tool_result is None:
        return tool

    original_func = tool.func

    def logged_func(**arguments: Any) -> Any:
        if on_tool_call is not None:
            on_tool_call(tool.name, arguments)
        try:
            result = original_func(**arguments)
        except Exception as exc:
            if on_tool_result is not None:
                on_tool_result(tool.name, exc)
            raise
        if on_tool_result is not None:
            on_tool_result(tool.name, result)
        return result

    return FunctionTool(
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters,
        func=logged_func,
    )


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
def build_agent(
    config: AgentConfig,
    *,
    on_tool_call: ToolCallHook | None = None,
    on_tool_result: ToolResultHook | None = None,
) -> Iterator[Agent]:
    """Создаёт агента ``ember`` из конфигурации.

    Контекстный менеджер: пока контекст открыт, живут MCP-клиенты
    (stdio-процессы и HTTP-соединения), после выхода — корректно закрываются.

    Модель агенту не передаётся: она задана провайдеру (``[provider] model``),
    а агент ``ember`` наследует модель провайдера по умолчанию.

    Если память включена (``[memory] enabled`` или флаг ``--session``), агент
    получает хранилище (интерфейс ``Memory``, конкретный класс выбирает
    ``build_memory``) и ``session_id`` (см. ``resolve_session_id``): при старте
    он продолжает сохранённую сессию, а после каждого ответа сохраняет диалог.
    Механизм recall — внутри ``ember``.

    Args:
        config: Конфигурация агента.
        on_tool_call: Колбэк перед вызовом инструмента (имя, аргументы).
        on_tool_result: Колбэк после вызова (имя, результат или исключение).
            Нужен для показа процесса использования тулов в интерактивном
            режиме: каждый инструмент оборачивается прокси через ``wrap_tool``.
    """
    provider = build_provider(config.provider)
    memory = build_memory(config.memory)
    session_id = resolve_session_id(config.memory)

    with ExitStack() as stack:
        tools: list[FunctionTool] = []
        for server in config.mcp_servers:
            client = _open_mcp_client(server)
            stack.enter_context(client)
            for tool in client.list_tools():
                wrapped = wrap_tool(
                    tool,
                    on_tool_call=on_tool_call,
                    on_tool_result=on_tool_result,
                )
                tools.append(wrapped)

        kwargs: dict[str, Any] = {"provider": provider, "system_prompt": config.system_prompt}
        if tools:
            kwargs["tools"] = tools
        if memory is not None and session_id is not None:
            # memory и session_id идут только вместе — контракт Agent (ember).
            # session_id — из resolve_session_id: явный из TOML либо новый.
            kwargs["memory"] = memory
            kwargs["session_id"] = session_id

        yield Agent(**kwargs)
