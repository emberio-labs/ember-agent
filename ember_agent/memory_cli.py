"""Подкоманда ``ember-agent memory``: просмотр и очистка памяти агента.

Хранилище и его формат — зона ``ember`` (``FileMemory``: файл
``<session_id>.json`` на сессию, JSONL внутри); здесь только CLI: показать,
что сохранено, и удалить ненужное. Это особенно полезно при автогенерации
сессий: каждый запуск без ``session_id`` создаёт новую сессию, и без команды
списка файлы пришлось бы искать вручную.

Команды работают с секцией ``[memory]`` конфигурации (директория, тип), но не
смотрят на флаг ``enabled``: управлять сохранённым можно и при выключенной
памяти.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ember.types import Message

from ember_agent.config import DEFAULT_CONFIG_FILE, ConfigError, MemoryConfig, load_config
from ember_agent.console import print_error
from ember_agent.factory import build_memory_store

#: Расширение файлов файлового хранилища: ``<session_id>.json``.
_SESSION_SUFFIX = ".json"

#: Метка роли сообщения в выводе ``memory show``.
_ROLE_MARKS = {"user": "👤", "assistant": "🤖", "tool": "🧰"}


def load_memory_config(config_path: str) -> MemoryConfig:
    """Прочитать секцию ``[memory]`` для команд памяти.

    Отличается от ``config.load_config`` мягким отношением к отсутствующему
    файлу: команды ``memory`` полезны и в проекте без конфигурации — тогда
    берутся значения по умолчанию (``.ember/memory``). Явно указанный
    ``--config`` без файла — по-прежнему ошибка: опечатка в пути не должна
    оставаться незамеченной.

    Raises:
        ConfigError: указан несуществующий путь или файл некорректен.
    """
    path = Path(config_path)
    if path.is_file():
        return load_config(path).memory
    if config_path == DEFAULT_CONFIG_FILE:
        return MemoryConfig()
    raise ConfigError(f"Файл конфигурации не найден: {path}")


def _session_ids(directory: Path) -> list[str]:
    """Id сессий по именам файлов хранилища, отсортированные по возрастанию.

    Раскладка файлов — деталь ``FileMemory``. Других типов хранилищ в CLI-конфиге
    пока нет (``config.VALID_MEMORY_TYPES``), поэтому перечисление смотрит на
    файлы; при появлении нового бэкенда его место — в интерфейсе ``Memory``.
    """
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob(f"*{_SESSION_SUFFIX}"))


def _empty_message(directory: Path) -> str:
    """Сообщение о пустом хранилище."""
    return f"Память пуста: {directory} — сохранённых сессий нет"


def _human_size(size: int) -> str:
    """Размер файла в удобных единицах."""
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} КиБ"
    return f"{size / (1024 * 1024):.1f} МиБ"


def _format_message(message: Message) -> str:
    """Одна строка вывода для сообщения диалога."""
    mark = _ROLE_MARKS.get(message.role, "•")
    content = message.content
    if not content and message.tool_calls:
        names = ", ".join(call.name for call in message.tool_calls)
        content = f"(вызовы инструментов: {names})"
    return f"{mark} {message.role}: {content}".rstrip()


def _not_found(config: MemoryConfig, session_id: str) -> int:
    """Сообщить, что сессии нет, и вернуть код ошибки."""
    print_error(f"Сессия {session_id!r} не найдена в {config.directory}")
    return 1


def list_sessions(config: MemoryConfig) -> int:
    """Напечатать список сохранённых сессий: id, сообщений, время, размер.

    Returns:
        Код выхода: 0 — список выведен (в том числе пустой).
    """
    directory = Path(config.directory)
    session_ids = _session_ids(directory)
    if not session_ids:
        print(_empty_message(directory))
        return 0

    memory = build_memory_store(config)
    rows: list[tuple[str, int, str, str]] = []
    for session_id in session_ids:
        stat = (directory / f"{session_id}{_SESSION_SUFFIX}").stat()
        changed = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        count = len(memory.load_session(session_id))
        rows.append((session_id, count, changed, _human_size(stat.st_size)))

    id_width = max(len("ID"), *(len(row[0]) for row in rows))
    header = f"{'ID':<{id_width}}  {'Сообщений':>9}  {'Изменена':<19}  {'Размер':>8}"
    print(f"Хранилище: {directory}")
    print(header)
    print("-" * len(header))
    for session_id, count, changed, size in rows:
        print(f"{session_id:<{id_width}}  {count:>9}  {changed:<19}  {size:>8}")
    print(f"Всего сессий: {len(rows)}")
    return 0


def show_session(config: MemoryConfig, session_id: str) -> int:
    """Напечатать диалог сессии.

    Returns:
        Код выхода: 0 — диалог выведен, 1 — сессии нет.
    """
    directory = Path(config.directory)
    if not directory.is_dir():
        return _not_found(config, session_id)

    memory = build_memory_store(config)
    messages = memory.load_session(session_id)
    if not messages:
        return _not_found(config, session_id)

    print(f"Сессия {session_id!r}: сообщений {len(messages)}")
    for message in messages:
        print(_format_message(message))
    return 0


def delete_session(config: MemoryConfig, session_id: str) -> int:
    """Удалить одну сессию.

    Returns:
        Код выхода: 0 — удалено, 1 — сессии нет.
    """
    directory = Path(config.directory)
    if not directory.is_dir():
        return _not_found(config, session_id)

    memory = build_memory_store(config)
    if not memory.load_session(session_id):
        return _not_found(config, session_id)

    memory.delete_session(session_id)
    print(f"Сессия {session_id!r} удалена из {directory}")
    return 0


def clear_sessions(config: MemoryConfig, *, yes: bool) -> int:
    """Удалить все сессии.

    Требует явного ``--yes``: операция необратима. Без флага ничего не удаляет,
    а сообщает, чего не хватает (код 2 — как у ошибок использования).

    Returns:
        Код выхода: 0 — удалено (или удалять было нечего), 2 — нет ``--yes``.
    """
    directory = Path(config.directory)
    session_ids = _session_ids(directory)
    if not session_ids:
        print(_empty_message(directory))
        return 0

    if not yes:
        print_error(
            f"Удалить все сессии ({len(session_ids)}) из {directory}? "
            f"Повторите команду с флагом --yes"
        )
        return 2

    memory = build_memory_store(config)
    for session_id in session_ids:
        memory.delete_session(session_id)
    print(f"Удалено сессий: {len(session_ids)} из {directory}")
    return 0
