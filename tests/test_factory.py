"""Тесты фабрики: сборка агента и обёртка инструментов (mock-first, без сети)."""

from __future__ import annotations

import pytest
from ember import FunctionTool
from ember_agent.factory import wrap_tool


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
