"""Тесты интерактивного режима REPL: без сети, на MockProvider и фейках."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest
from ember import Agent, FunctionTool, MockProvider
from ember_agent.config import AgentConfig
from ember_agent.repl import (
    AGENT_LABEL,
    HELP_TEXT,
    USER_PROMPT,
    _session,
    _ToolFeed,
    format_greeting,
    run_repl,
)
from rich.console import Console


def _make_input(*lines: str) -> Callable[[str], str]:
    """Фейковый ввод: отдаёт строки по очереди, после — EOF."""
    iterator = iter(lines)

    def read(_prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise EOFError from exc

    return read


def _mock_agent(system_prompt: str = "Ты тестовый агент.") -> Agent:
    """Агент на MockProvider без инструментов (потоковый вывод)."""
    return Agent(
        provider=MockProvider(response_text="Привет! Я мок-провайдер."),
        system_prompt=system_prompt,
    )


class _InterruptingStreamAgent:
    """Фейковый агент, чей ответ прерывается KeyboardInterrupt."""

    provider = MockProvider()
    model: str | None = None
    tools: Sequence[Any] | None = None

    def stream_run(self, user_input: str) -> Iterator[str]:
        yield "начало"
        raise KeyboardInterrupt

    def run(self, user_input: str) -> str:
        return ""

    def reset(self) -> None:
        return None


# --- форматирование -----------------------------------------------------


def test_format_greeting_contains_context() -> None:
    text = format_greeting(
        provider="MockProvider",
        model="mock-1",
        tool_names=["read_file", "echo"],
    )

    assert "MockProvider" in text
    assert "mock-1" in text
    assert "инструменты (2): read_file, echo" in text
    assert "/help" in text


def test_format_greeting_without_model_and_tools() -> None:
    text = format_greeting(provider="MockProvider", model=None, tool_names=[])

    assert "инструменты: нет" in text
    assert "модель:" not in text


def test_help_text_documents_commands() -> None:
    assert "/help" in HELP_TEXT
    assert "/reset" in HELP_TEXT


# --- цикл диалога -------------------------------------------------------


def test_session_exit_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = _session(_mock_agent(), Console(), _make_input("exit"))

    assert code == 0


def test_session_quit_is_case_insensitive(capsys: pytest.CaptureFixture[str]) -> None:
    code = _session(_mock_agent(), Console(), _make_input("ВЫХОД"))

    assert code == 0


def test_session_ends_on_eof(capsys: pytest.CaptureFixture[str]) -> None:
    code = _session(_mock_agent(), Console(), _make_input())

    assert code == 0


def test_session_prints_greeting_banner(capsys: pytest.CaptureFixture[str]) -> None:
    code = _session(_mock_agent(), Console(), _make_input("exit"))

    captured = capsys.readouterr()
    assert code == 0
    assert "ember-agent" in captured.out
    assert "MockProvider" in captured.out
    assert "/help" in captured.out


def test_session_print_answer_from_mock(capsys: pytest.CaptureFixture[str]) -> None:
    code = _session(_mock_agent(), Console(), _make_input("привет", "exit"))

    captured = capsys.readouterr()
    assert code == 0
    assert "Привет! Я мок-провайдер." in captured.out


def test_session_marks_agent_reply_with_label(capsys: pytest.CaptureFixture[str]) -> None:
    code = _session(_mock_agent(), Console(), _make_input("привет", "exit"))

    captured = capsys.readouterr()
    assert code == 0
    assert AGENT_LABEL in captured.out


def test_session_help_and_reset(capsys: pytest.CaptureFixture[str]) -> None:
    agent = _mock_agent()

    code = _session(agent, Console(), _make_input("/help", "/reset", "exit"))

    captured = capsys.readouterr()
    assert code == 0
    assert "Команды сессии" in captured.out
    assert "История сброшена" in captured.out
    assert [m.role for m in agent.messages] == ["system"]


def test_session_reset_clears_history() -> None:
    agent = _mock_agent()

    code = _session(agent, Console(), _make_input("привет", "/reset", "exit"))

    assert code == 0
    assert [m.role for m in agent.messages] == ["system"]


def test_session_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    code = _session(_mock_agent(), Console(), _make_input("/nope", "exit"))

    captured = capsys.readouterr()
    assert code == 0
    assert "Неизвестная команда" in captured.out


def test_session_second_ctrl_c_exits(capsys: pytest.CaptureFixture[str]) -> None:
    class _CtrlCInput:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, _prompt: str) -> str:
            self.calls += 1
            if self.calls <= 2:
                raise KeyboardInterrupt
            raise EOFError

    code = _session(_mock_agent(), Console(), _CtrlCInput())

    captured = capsys.readouterr()
    assert code == 0
    assert "Ctrl+C ещё раз" in captured.out


def test_session_interrupted_answer_continues(capsys: pytest.CaptureFixture[str]) -> None:
    code = _session(_InterruptingStreamAgent(), Console(), _make_input("сообщение", "exit"))

    captured = capsys.readouterr()
    assert code == 0
    assert "Ответ прерван" in captured.out


def test_session_with_tools_prints_thinking_and_answer(capsys: pytest.CaptureFixture[str]) -> None:
    def echo(*, text: str) -> str:
        return text

    tool = FunctionTool(name="echo", description="повторить", parameters=None, func=echo)
    agent = Agent(provider=MockProvider(response_text="Готово!"), tools=[tool])

    code = _session(agent, Console(), _make_input("сделай", "exit"))

    captured = capsys.readouterr()
    assert code == 0
    assert "думаю…" in captured.out
    assert "Готово!" in captured.out


def test_user_prompt_is_not_a_bare_lowercase_you() -> None:
    assert "вы:" not in USER_PROMPT.lower().replace(" ", "")


# --- лог вызовов инструментов (_ToolFeed) -------------------------------


def test_tool_feed_prints_call_and_result(capsys: pytest.CaptureFixture[str]) -> None:
    feed = _ToolFeed(Console())

    feed.on_tool_call("read_file", {"path": "config.toml", "lines": 40})
    feed.on_tool_result("read_file", "🔌 провайдер: mock")

    feed.print_pending()

    captured = capsys.readouterr()
    assert "🔧 read_file" in captured.out
    assert 'path="config.toml"' in captured.out
    assert "lines=40" in captured.out
    assert "✔ read_file" in captured.out
    assert "🔌 провайдер: mock" in captured.out
    assert feed.last_kind == "result"
    assert feed.last_name == "read_file"


def test_tool_feed_prints_error_in_red(capsys: pytest.CaptureFixture[str]) -> None:
    feed = _ToolFeed(Console())

    feed.on_tool_result("read_file", RuntimeError("нет файла"))
    feed.print_pending()

    captured = capsys.readouterr()
    assert "✖ read_file" in captured.out
    assert "нет файла" in captured.out


def test_tool_feed_clips_long_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    feed = _ToolFeed(Console())
    long_text = "а" * 300

    feed.on_tool_call("write_file", {"path": "note.txt", "content": long_text})
    feed.print_pending()

    captured = capsys.readouterr()
    assert "…" in captured.out
    assert long_text not in captured.out


def test_tool_feed_empty_after_drain(capsys: pytest.CaptureFixture[str]) -> None:
    feed = _ToolFeed(Console())
    assert feed.empty

    feed.on_tool_call("echo", {"text": "привет"})
    assert not feed.empty

    feed.print_pending()
    assert feed.empty


def test_tool_feed_close_discards_events(capsys: pytest.CaptureFixture[str]) -> None:
    feed = _ToolFeed(Console())

    feed.on_tool_call("echo", {"text": "привет"})
    feed.close()
    assert feed.empty

    feed.on_tool_call("echo", {"text": "после закрытия"})
    feed.print_pending()

    captured = capsys.readouterr()
    assert "echo" not in captured.out


# --- run_repl (агент из конфигурации) -----------------------------------


def test_run_repl_with_default_config(capsys: pytest.CaptureFixture[str]) -> None:
    code = run_repl(AgentConfig(), input_fn=_make_input("привет", "exit"))

    captured = capsys.readouterr()
    assert code == 0
    assert "Привет! Я мок-провайдер." in captured.out
