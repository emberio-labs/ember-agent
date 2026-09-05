"""Интерактивный режим (REPL): красивый вывод, поток, команды сессии.

Собирает в одном месте UX диалога с агентом, который раньше был
«минимальным каркасом» в ``cli.py``:

- баннер приветствия (rich-панель): версия, провайдер, модель, инструменты;
- диалог в виде чата: ответы агента с подписью, приглашение «Ваш ответ»;
- команды сессии ``/help``, ``/reset`` (сброс через ``Agent.reset()``);
- markdown-рендер ответов (rich) с потоковой печатью там, где нет тулов;
- показ процесса вызова инструментов (колбэки ``factory.build_agent``);
- Ctrl+C отменяет текущий ввод/ответ, а не завершает процесс.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Protocol

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from ember_agent import __version__
from ember_agent.config import AgentConfig
from ember_agent.factory import ToolCallHook, ToolResultHook, build_agent

#: Команды выхода из диалога (регистронезависимо).
QUIT_COMMANDS = frozenset({"exit", "quit", "выход"})

#: Подпись ответов агента в ленте диалога.
AGENT_LABEL = "🤖 ember-agent"

#: Приглашение ввода пользователя (rich-markup для ``Console.input``).
USER_PROMPT = "\n[bold cyan]Ваш ответ:[/bold cyan] "

HELP_TEXT = """\
Команды сессии:
  /help    — показать эту справку
  /reset   — начать новый диалог (сбросить историю)

Выход: exit, quit, выход. Или Ctrl+D; Ctrl+C дважды — тоже выход.
"""

#: Предел длины аргументов/результата тула в логе процесса.
_PREVIEW_LIMIT = 100


class ReplAgent(Protocol):
    """Агент в терминах REPL: что нужно диалогу от объекта ``Agent``."""

    provider: Any
    model: str | None
    tools: Sequence[Any] | None

    def run(self, user_input: str) -> str: ...
    def stream_run(self, user_input: str) -> Iterator[str]: ...
    def reset(self) -> None: ...


def format_greeting(
    *,
    provider: str,
    model: str | None,
    tool_names: Sequence[str],
) -> str:
    """Собрать текст баннера приветствия (тело rich-панели).

    Заголовок панели с версией добавляется при печати в ``_session`` —
    здесь только контекст сессии и подсказка.
    """
    lines = [f"🔌 провайдер: {provider}"]
    if model:
        lines.append(f"🧠 модель: {model}")
    if tool_names:
        lines.append(f"🧰 инструменты ({len(tool_names)}): {', '.join(tool_names)}")
    else:
        lines.append("🧰 инструменты: нет")
    lines.extend(["", "💬 Введите сообщение или наберите /help."])
    return "\n".join(lines)


def _agent_context(agent: ReplAgent) -> tuple[str, str | None, list[str]]:
    """Достать из агента провайдера, модель и имена инструментов."""
    provider_name = type(agent.provider).__name__
    model = agent.model or getattr(agent.provider, "model", None)
    names = [tool.name for tool in (agent.tools or [])]
    return provider_name, model, names


def _compact_arguments(arguments: dict[str, Any]) -> str:
    """Аргументы тула одной строкой (усечённой) для лога процесса."""
    if not arguments:
        return ""
    text = json.dumps(arguments, ensure_ascii=False, default=str)
    if len(text) > _PREVIEW_LIMIT:
        return text[: _PREVIEW_LIMIT - 1] + "…"
    return text


def _preview_result(text: str) -> str:
    """Усечь многострочный результат тула до одной читаемой строки."""
    one_line = " ".join(text.split())
    if len(one_line) <= _PREVIEW_LIMIT:
        return one_line
    return one_line[: _PREVIEW_LIMIT - 1] + "…"


def _tool_hooks(console: Console) -> tuple[ToolCallHook, ToolResultHook]:
    """Колбэки для ``build_agent``: печатают процесс вызова тулов в консоль."""

    def on_tool_call(name: str, arguments: dict[str, Any]) -> None:
        args = _compact_arguments(arguments)
        label = f"🔧 {name}({args})" if args else f"🔧 {name}"
        console.print(Text(label))

    def on_tool_result(name: str, result: Any) -> None:
        if isinstance(result, BaseException):
            console.print(Text(f"✖ {name}: {result}"))
            return
        if isinstance(result, str):
            preview = _preview_result(result)
        else:
            preview = _preview_result(str(result))
        if preview:
            console.print(Text(f"✔ {name}: {preview}"))
        else:
            console.print(Text(f"✔ {name}"))

    return on_tool_call, on_tool_result


def _stream_answer(agent: ReplAgent, user_input: str, console: Console) -> None:
    """Потоковая печать ответа модели (агент без инструментов).

    В терминале текст рендерится как markdown по мере поступления (rich
    ``Live``); при перенаправлении вывода куски печатаются как есть.
    """
    if console.is_terminal:
        buffer = ""
        with Live(Markdown(""), console=console, refresh_per_second=15) as live:
            for delta in agent.stream_run(user_input):
                buffer += delta
                live.update(Markdown(buffer))
    else:
        for delta in agent.stream_run(user_input):
            console.print(delta, end="")
        console.print()


def _print_answer(agent: ReplAgent, user_input: str, console: Console) -> None:
    """Получить и напечатать ответ агента на сообщение пользователя."""
    console.print(Text(AGENT_LABEL, style="bold cyan"))
    if agent.tools:
        # С тулами stream_run() в ember не работает: показываем «думаю…»
        # и живые вызовы инструментов (их печатают колбэки build_agent).
        console.print(Text("думаю…"))
        console.print(Markdown(agent.run(user_input)))
    else:
        _stream_answer(agent, user_input, console)


def _print_greeting(
    console: Console,
    *,
    provider: str,
    model: str | None,
    tool_names: Sequence[str],
) -> None:
    """Напечатать баннер приветствия: rich-панель с версией и контекстом."""
    body = format_greeting(provider=provider, model=model, tool_names=tool_names)
    console.print(
        Panel(
            body,
            title=f"⚡ ember-agent {__version__}",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def _session(
    agent: ReplAgent,
    console: Console,
    input_fn: Callable[[str], str],
) -> int:
    """Цикл диалога: ввод строк, команды, ответы агента. Код выхода 0."""
    provider, model, tool_names = _agent_context(agent)
    _print_greeting(console, provider=provider, model=model, tool_names=tool_names)

    interrupted = False
    while True:
        try:
            line = input_fn(USER_PROMPT).strip()
        except EOFError:
            console.print()
            return 0
        except KeyboardInterrupt:
            if interrupted:
                console.print()
                return 0
            interrupted = True
            console.print(Text("Ctrl+C ещё раз — выход."))
            continue
        interrupted = False

        if not line:
            continue
        if line.lower() in QUIT_COMMANDS:
            return 0

        if line.startswith("/"):
            command = line.lower()
            if command == "/help":
                console.print(HELP_TEXT)
            elif command == "/reset":
                agent.reset()
                console.print(Text("История сброшена: начинаем новый диалог."))
            else:
                console.print(Text(f"Неизвестная команда: {line}. Наберите /help."))
            continue

        try:
            _print_answer(agent, line, console)
        except KeyboardInterrupt:
            console.print(Text("Ответ прерван."))
        except Exception as exc:
            console.print(Text(f"ошибка: {exc}"))


def run_repl(
    config: AgentConfig,
    *,
    console: Console | None = None,
    input_fn: Callable[[str], str] | None = None,
) -> int:
    """Запустить интерактивный диалог с агентом из конфигурации.

    Создаёт агента через ``factory.build_agent`` с колбэками, печатающими
    процесс вызова инструментов в консоль. Возвращает код выхода 0.

    Args:
        config: Конфигурация агента.
        console: Консоль rich (по умолчанию создаётся новая).
        input_fn: Функция чтения строки с приглашением (для тестов);
            по умолчанию — ``console.input`` (rich-markup приглашения).
    """
    console = console or Console()
    on_tool_call, on_tool_result = _tool_hooks(console)
    with build_agent(
        config,
        on_tool_call=on_tool_call,
        on_tool_result=on_tool_result,
    ) as agent:
        return _session(agent, console, input_fn or console.input)
