"""Тесты фабрики: сборка агента, память и обёртка инструментов (mock-first)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from ember import (
    ChatRequest,
    ChatResponse,
    FunctionTool,
    Memory,
    Message,
    MockProvider,
)
from ember.memory import FileMemory
from ember_agent import factory as factory_module
from ember_agent.config import AgentConfig, ConfigError, MemoryConfig
from ember_agent.factory import build_agent, build_memory, wrap_tool


def _echo_tool() -> FunctionTool:
    """Инструмент, повторяющий текст заглавными буквами."""

    def echo(*, text: str) -> str:
        return text.upper()

    return FunctionTool(
        name="echo",
        description="повторить текст",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}},
        func=echo,
    )


class _RecordingProvider(MockProvider):
    """MockProvider, запоминающий сообщения каждого запроса (для проверки recall)."""

    def __init__(self, response_text: str = "ок") -> None:
        super().__init__(response_text=response_text)
        self.requests: list[list[Message]] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(list(request.messages))
        return super().complete(request)


class _StubMemory(Memory):
    """Свой бэкенд памяти: проверяем, что фабрика не привязана к ``FileMemory``."""

    def __init__(self) -> None:
        self.sessions: dict[str, list[Message]] = {}
        self.searches: list[tuple[str, str | None]] = []

    def load_session(self, session_id: str) -> list[Message]:
        return list(self.sessions.get(session_id, []))

    def save_session(self, session_id: str, messages: Sequence[Message]) -> None:
        self.sessions[session_id] = list(messages)

    def search(
        self,
        query: str,
        *,
        exclude_session_id: str | None = None,
        limit: int = 5,
    ) -> list[Message]:
        self.searches.append((query, exclude_session_id))
        return []

    def delete_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)


def test_wrap_tool_without_hooks_returns_original() -> None:
    tool = _echo_tool()

    assert wrap_tool(tool) is tool
    assert wrap_tool(tool, on_tool_call=lambda name, args: None) is not tool


def test_wrap_tool_keeps_metadata() -> None:
    tool = _echo_tool()

    wrapped = wrap_tool(
        tool,
        on_tool_call=lambda name, args: None,
        on_tool_result=lambda name, result: None,
    )

    assert wrapped.name == tool.name == "echo"
    assert wrapped.description == tool.description
    assert wrapped.parameters == tool.parameters


def test_wrap_tool_logs_call_and_result() -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    results: list[tuple[str, object]] = []
    wrapped = wrap_tool(
        _echo_tool(),
        on_tool_call=lambda name, args: calls.append((name, args)),
        on_tool_result=lambda name, result: results.append((name, result)),
    )

    assert wrapped.func(text="привет") == "ПРИВЕТ"

    assert calls == [("echo", {"text": "привет"})]
    assert results == [("echo", "ПРИВЕТ")]


def test_wrap_tool_logs_exception_and_reraises() -> None:
    def boom() -> None:
        raise RuntimeError("сломалось")

    tool = FunctionTool(name="boom", func=boom)
    results: list[tuple[str, object]] = []
    wrapped = wrap_tool(tool, on_tool_result=lambda name, result: results.append((name, result)))

    with pytest.raises(RuntimeError, match="сломалось"):
        wrapped.func()

    assert len(results) == 1
    name, result = results[0]
    assert name == "boom"
    assert isinstance(result, RuntimeError)


# --- память -------------------------------------------------------------


def _memory_config(tmp_path: Path, *, session_id: str = "s1") -> AgentConfig:
    return AgentConfig(
        memory=MemoryConfig(
            enabled=True,
            directory=str(tmp_path / "mem"),
            session_id=session_id,
        )
    )


def test_build_memory_disabled_returns_none(tmp_path: Path) -> None:
    directory = tmp_path / "mem"

    assert build_memory(MemoryConfig(directory=str(directory))) is None
    assert not directory.exists(), "выключенная память не должна создавать директорию"


def test_build_memory_enabled_returns_file_memory(tmp_path: Path) -> None:
    directory = tmp_path / "mem"

    memory = build_memory(MemoryConfig(enabled=True, directory=str(directory)))

    assert isinstance(memory, FileMemory)
    assert isinstance(memory, Memory), "возвращается интерфейс, а не конкретный класс"
    assert memory.directory == directory
    assert directory.is_dir()


def test_build_memory_passes_config_to_registered_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubMemory()
    seen: list[MemoryConfig] = []

    def factory(config: MemoryConfig) -> Memory:
        seen.append(config)
        return stub

    monkeypatch.setitem(factory_module._MEMORY_FACTORIES, "stub", factory)
    config = MemoryConfig(enabled=True, type="stub", session_id="custom")

    assert build_memory(config) is stub
    assert seen == [config], "фабрика получает всю секцию [memory]"


def test_build_memory_unknown_type_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    config = MemoryConfig(enabled=True, type="redis")

    with pytest.raises(ConfigError, match="тип памяти"):
        build_memory(config)


def test_build_agent_without_memory_leaves_agent_plain() -> None:
    with build_agent(AgentConfig()) as agent:
        assert agent.memory is None
        assert agent.session_id is None


def test_build_agent_wires_memory_and_session(tmp_path: Path) -> None:
    with build_agent(_memory_config(tmp_path)) as agent:
        assert isinstance(agent.memory, FileMemory)
        assert agent.session_id == "s1"


def test_build_agent_wires_custom_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubMemory()
    monkeypatch.setitem(factory_module._MEMORY_FACTORIES, "stub", lambda config: stub)
    config = AgentConfig(
        memory=MemoryConfig(enabled=True, type="stub", session_id="custom"),
    )

    with build_agent(config) as agent:
        agent.run("привет")
        assert agent.memory is stub
        assert agent.session_id == "custom"

    assert stub.sessions["custom"], "диалог должен уйти в пользовательский бэкенд"


def test_memory_persists_dialog_between_runs(tmp_path: Path) -> None:
    config = _memory_config(tmp_path)

    with build_agent(config) as agent:
        agent.run("Запомни: кодовое слово — сирень")

    with build_agent(config) as agent:
        roles = [message.role for message in agent.messages]

    assert roles[0] == "system"
    assert "user" in roles
    assert "assistant" in roles
    assert any("сирень" in message.content for message in agent.messages)


def test_memory_recall_adds_fragments_from_other_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "mem"
    FileMemory(directory).save_session(
        "old", [Message(role="user", content="Любимый цвет пользователя — синий")]
    )
    provider = _RecordingProvider()
    monkeypatch.setattr(factory_module, "build_provider", lambda _config: provider)

    with build_agent(_memory_config(tmp_path, session_id="new")) as agent:
        agent.run("Какой у меня любимый цвет?")

    system_messages = [
        message.content for message in provider.requests[0] if message.role == "system"
    ]
    assert any("синий" in content for content in system_messages)


def test_memory_recall_skips_current_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _StubMemory()
    monkeypatch.setitem(factory_module._MEMORY_FACTORIES, "stub", lambda config: stub)
    config = AgentConfig(
        memory=MemoryConfig(enabled=True, type="stub", session_id="current"),
    )

    with build_agent(config) as agent:
        agent.run("Какой у меня любимый цвет?")

    assert stub.searches, "агент должен спросить прошлые сессии"
    assert {session for _, session in stub.searches} == {"current"}
