"""Интерактивный режим (REPL): красивый вывод, поток, команды сессии.

Собирает в одном месте UX диалога с агентом, который раньше был
«минимальным каркасом» в ``cli.py``:

- баннер приветствия (rich-панель): версия, провайдер, модель, инструменты, память;
- диалог в виде чата: ответы агента с подписью, приглашение «Ваш ответ»;
- команды сессии ``/help``, ``/reset`` (сброс истории через ``Agent.reset()``);
- markdown-рендер ответов (rich) с потоковой печатью там, где нет тулов;
- анимированный индикатор «думаю…» (rich ``Status``) на время ответа агента;
- цветной лог вызовов инструментов: имя тула, аргументы и результат;
- Ctrl+C отменяет текущий ввод/ответ, а не завершает процесс.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from queue import Empty, Queue
from typing import Any, Protocol

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from ember_agent import __version__
from ember_agent.config import AgentConfig
from ember_agent.factory import build_agent

#: Команды выхода из диалога (регистронезависимо).
QUIT_COMMANDS = frozenset({"exit", "quit", "выход"})

#: Подпись ответов агента в ленте диалога.
AGENT_LABEL = "🤖 ember-agent"

#: Приглашение ввода пользователя (rich-markup для ``Console.input``).
USER_PROMPT = "\n[bold cyan]Ваш ответ:[/bold cyan] "

HELP_TEXT = """\
Команды сессии:
  /help    — показать эту справку
  /reset   — начать новый диалог (очистить историю и текущую сессию памяти)

Выход: exit, quit, выход. Или Ctrl+D; Ctrl+C дважды — тоже выход.
"""

#: Предел длины аргументов/результата тула в логе процесса.
_PREVIEW_LIMIT = 100

#: Предел длины одного значения аргумента в логе вызова.
_VALUE_LIMIT = 60

#: Как часто главный поток опрашивает очередь событий инструментов.
_SPINNER_POLL_SECONDS = 0.05

#: Текст анимированного индикатора (рисуется rich ``Status``).
_THINKING_TEXT = "💭 думаю…"


class ReplAgent(Protocol):
    """Агент в терминах REPL: что нужно диалогу от объекта ``Agent``."""

    provider: Any
    model: str | None
    tools: Sequence[Any] | None
    memory: Any
    session_id: str | None

    def run(self, user_input: str) -> str: ...
    def stream_run(self, user_input: str) -> Iterator[str]: ...
    def reset(self) -> None: ...


#: Событие лога инструмента: вид ("call"/"result"), имя тула, данные события.
ToolEvent = tuple[str, str, Any]


def format_greeting(
    *,
    provider: str,
    model: str | None,
    tool_names: Sequence[str],
    session_id: str | None = None,
    memory_directory: str | None = None,
) -> str:
    """Собрать текст баннера приветствия (тело rich-панели).

    Заголовок панели с версией добавляется при печати в ``_session`` —
    здесь только контекст сессии и подсказка. Про память пишем всегда:
    выключенная — это тоже полезно знать до первого запроса.
    """
    lines = [f"🔌 провайдер: {provider}"]
    if model:
        lines.append(f"🧠 модель: {model}")
    if tool_names:
        lines.append(f"🧰 инструменты ({len(tool_names)}): {', '.join(tool_names)}")
    else:
        lines.append("🧰 инструменты: нет")
    if session_id and memory_directory:
        lines.append(f"🗂 память: сессия {session_id!r} → {memory_directory}")
        lines.append(f"↻ продолжить диалог: ember-agent run --session {session_id}")
    else:
        lines.append("🗂 память: выключена")
    lines.extend(["", "💬 Введите сообщение или наберите /help."])
    return "\n".join(lines)


def _agent_context(agent: ReplAgent) -> tuple[str, str | None, list[str]]:
    """Достать из агента провайдера, модель и имена инструментов."""
    provider_name = type(agent.provider).__name__
    model = agent.model or getattr(agent.provider, "model", None)
    names = [tool.name for tool in (agent.tools or [])]
    return provider_name, model, names


def _memory_directory(agent: ReplAgent) -> str | None:
    """Директория хранилища памяти или ``None``, если память выключена.

    У ``FileMemory`` есть атрибут ``directory``; для произвольной реализации
    ``Memory`` показываем имя класса — лишь бы пользователь понимал, куда пишем.
    """
    memory = agent.memory
    if memory is None:
        return None
    directory = getattr(memory, "directory", None)
    return str(directory) if directory is not None else type(memory).__name__


def _preview_result(text: str) -> str:
    """Усечь многострочный результат тула до одной читаемой строки."""
    one_line = " ".join(text.split())
    if len(one_line) <= _PREVIEW_LIMIT:
        return one_line
    return one_line[: _PREVIEW_LIMIT - 1] + "…"


def _clip(text: Text, limit: int) -> Text:
    """Обрезать rich-``Text`` до ``limit`` символов, сохранив стили кусков."""
    if len(text) <= limit:
        return text
    clipped = Text()
    clipped.append_text(text[: limit - 1])
    clipped.append("…", style="dim")
    return clipped


def _argument_value(value: Any) -> Text:
    """Одно значение аргумента: JSON-вид с цветом по типу."""
    if isinstance(value, str):
        body, style = json.dumps(value, ensure_ascii=False), "yellow"
    elif isinstance(value, bool):
        body, style = json.dumps(value), "magenta"
    elif isinstance(value, int | float):
        body, style = str(value), "magenta"
    elif value is None:
        body, style = "null", "magenta"
    else:
        body = json.dumps(value, ensure_ascii=False, default=str)
        style = "cyan"
    return Text(body, style=style)


def _tool_call_text(name: str, arguments: dict[str, Any]) -> Text:
    """Строка события «вызов инструмента»: имя и аргументы в цвете."""
    text = Text()
    text.append("🔧 ", style="dim")
    text.append(name, style="bold cyan")
    if arguments:
        args = Text()
        for index, (key, value) in enumerate(arguments.items()):
            if index:
                args.append(" ")
            args.append(key, style="bold")
            args.append("=")
            args.append_text(_clip(_argument_value(value), _VALUE_LIMIT))
        text.append("  ")
        text.append_text(_clip(args, _PREVIEW_LIMIT))
    return text


def _tool_result_text(name: str, result: Any) -> Text:
    """Строка события «результат инструмента»: успех или ошибка в цвете."""
    if isinstance(result, BaseException):
        return Text(f"✖ {name}: {result}", style="bold red")

    preview = _preview_result(str(result) if not isinstance(result, str) else result)
    text = Text()
    text.append("✔ ", style="green")
    text.append(name, style="bold cyan")
    if preview:
        text.append(" → ")
        text.append(preview, style="dim")
    return text


class _ToolFeed:
    """Потокобезопасный буфер событий вызовов инструментов.

    Хуки обёрток инструментов (``build_agent``) срабатывают в потоке,
    где исполняется агент, а рисовать в консоль можно только из главного
    потока — иначе вывод конфликтует со спиннером rich. Поэтому события
    складываются в очередь и печатаются методом ``print_pending`` из цикла
    анимации (или сразу после ответа, если терминала нет).
    """

    def __init__(self, console: Console) -> None:
        self._console = console
        self._events: Queue[ToolEvent] = Queue()
        self._closed = False
        # Последнее напечатанное событие: чтобы спиннер показывал имя тула,
        # который сейчас исполняется (пока не пришёл его результат).
        self.last_kind: str | None = None
        self.last_name: str | None = None

    @property
    def empty(self) -> bool:
        """Пуста ли очередь событий."""
        return self._events.empty()

    def close(self) -> None:
        """Закрыть буфер и отбросить необработанные события.

        Вызывается при прерывании ответа: «зомби»-поток агента продолжит
        работу в фоне, но его события больше не попадут в консоль.
        """
        self._closed = True
        while not self._events.empty():
            try:
                self._events.get_nowait()
            except Empty:
                return

    # Хуки для ``build_agent`` (вызываются в потоке исполнения агента).
    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        """Запомнить событие вызова инструмента."""
        if not self._closed:
            self._events.put(("call", name, arguments))

    def on_tool_result(self, name: str, result: Any) -> None:
        """Запомнить событие результата инструмента."""
        if not self._closed:
            self._events.put(("result", name, result))

    def print_pending(self) -> None:
        """Напечатать все накопленные события (только из главного потока)."""
        while not self._events.empty():
            try:
                kind, name, payload = self._events.get_nowait()
            except Empty:
                return
            if kind == "call":
                self._console.print(_tool_call_text(name, payload))
            else:
                self._console.print(_tool_result_text(name, payload))
            self.last_kind, self.last_name = kind, name


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


def _answer_with_animation(
    agent: ReplAgent,
    user_input: str,
    console: Console,
    feed: _ToolFeed,
) -> None:
    """Ответ агента с тулами: спиннер «думаю…» + живой цветной лог вызовов.

    ``agent.run`` исполняется в фоновом потоке (в ember с тулами потоковой
    печати нет), а главный поток крутит rich ``Status`` и печатает события
    инструментов из очереди ``feed`` — весь вывод идёт из одного потока,
    поэтому спиннер не «дерёт» консоль. Пока исполняется конкретный тул,
    спиннер показывает его имя.
    """
    outcome: dict[str, Any] = {}

    def worker() -> None:
        try:
            outcome["text"] = agent.run(user_input)
        except Exception as exc:  # результат покажем как ошибку ответа
            outcome["error"] = exc

    thread = threading.Thread(target=worker, name="ember-agent-run", daemon=True)
    thread.start()

    try:
        with console.status(_THINKING_TEXT, spinner="dots") as status:
            while thread.is_alive() or not feed.empty:
                feed.print_pending()
                if feed.last_kind == "call":
                    status.update(f"🔧 {feed.last_name}…")
                else:
                    status.update(_THINKING_TEXT)
                time.sleep(_SPINNER_POLL_SECONDS)
            feed.print_pending()
    except KeyboardInterrupt:
        # Прерываем только показ: агент в фоне доработает, его события гасим.
        feed.close()
        console.print(Text("Ответ прерван."))
        return

    thread.join()
    error = outcome.get("error")
    if error is not None:
        if isinstance(error, BaseException):
            raise error
        raise RuntimeError(str(error))
    console.print(Markdown(outcome["text"]))


def _print_answer(
    agent: ReplAgent,
    user_input: str,
    console: Console,
    feed: _ToolFeed | None = None,
) -> None:
    """Получить и напечатать ответ агента на сообщение пользователя."""
    console.print(Text(AGENT_LABEL, style="bold cyan"))
    if agent.tools:
        if feed is not None and console.is_terminal:
            _answer_with_animation(agent, user_input, console, feed)
        else:
            # Без терминала анимировать нечего: «думаю…», затем лог вызовов
            # (накопился в очереди за время ответа) и сам ответ.
            console.print(Text("думаю…", style="dim"))
            answer = agent.run(user_input)
            if feed is not None:
                feed.print_pending()
            console.print(Markdown(answer))
    else:
        _stream_answer(agent, user_input, console)


def _print_greeting(
    console: Console,
    *,
    provider: str,
    model: str | None,
    tool_names: Sequence[str],
    session_id: str | None = None,
    memory_directory: str | None = None,
) -> None:
    """Напечатать баннер приветствия: rich-панель с версией и контекстом."""
    body = format_greeting(
        provider=provider,
        model=model,
        tool_names=tool_names,
        session_id=session_id,
        memory_directory=memory_directory,
    )
    console.print(
        Panel(
            body,
            title=f"⚡ ember-agent {__version__}",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def _reset_message(agent: ReplAgent) -> str:
    """Текст подтверждения ``/reset``: с памятью уточняем, что сессия очищена."""
    message = "История сброшена: начинаем новый диалог."
    if agent.memory is not None and agent.session_id:
        return f"{message} Сессия {agent.session_id!r} очищена в хранилище."
    return message


def _session(
    agent: ReplAgent,
    console: Console,
    input_fn: Callable[[str], str],
    feed: _ToolFeed | None = None,
) -> int:
    """Цикл диалога: ввод строк, команды, ответы агента. Код выхода 0."""
    provider, model, tool_names = _agent_context(agent)
    _print_greeting(
        console,
        provider=provider,
        model=model,
        tool_names=tool_names,
        session_id=agent.session_id,
        memory_directory=_memory_directory(agent),
    )

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
                console.print(Text(_reset_message(agent)))
            else:
                console.print(Text(f"Неизвестная команда: {line}. Наберите /help."))
            continue

        try:
            _print_answer(agent, line, console, feed)
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

    Создаёт агента через ``factory.build_agent`` с хуками, которые пишут
    события вызовов инструментов в буфер ``_ToolFeed``: в терминале их
    печатает цикл анимации, в перенаправленном выводе — сразу после ответа.
    Если в конфигурации включена память, диалог продолжает сессию с диска.
    Возвращает код выхода 0.

    Args:
        config: Конфигурация агента.
        console: Консоль rich (по умолчанию создаётся новая).
        input_fn: Функция чтения строки с приглашением (для тестов);
            по умолчанию — ``console.input`` (rich-markup приглашения).
    """
    console = console or Console()
    feed = _ToolFeed(console)
    with build_agent(
        config,
        on_tool_call=feed.on_tool_call,
        on_tool_result=feed.on_tool_result,
    ) as agent:
        return _session(agent, console, input_fn or console.input, feed=feed)
