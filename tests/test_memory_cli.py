"""Тесты подкоманды ``ember-agent memory`` (list/show/delete/clear).

Хранилище в тестах — настоящее ``FileMemory`` из ``ember`` в ``tmp_path``:
проверяем не формат файлов (это зона библиотеки), а поведение CLI — коды
выхода, вывод, отношение к отсутствующим данным и флагу ``enabled``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from ember.memory import FileMemory
from ember.types import Message
from ember_agent.cli import main


def _write_config(tmp_path: Path, *, enabled: bool = True, directory: str | None = None) -> Path:
    """Конфигурация с секцией ``[memory]``.

    Директория хранилища пишется абсолютной: относительный путь CLI разрешает
    от текущей рабочей директории, а не от ``tmp_path``.
    """
    storage = directory if directory is not None else str(tmp_path / "mem")
    path = tmp_path / "config.toml"
    path.write_text(
        textwrap.dedent(f"""\
            [memory]
            enabled = {str(enabled).lower()}
            directory = "{storage}"
            """),
        encoding="utf-8",
    )
    return path


def _save_session(tmp_path: Path, session_id: str, *contents: str) -> Path:
    """Положить в хранилище (``tmp_path/mem``) сессию с сообщениями."""
    messages: list[Message] = []
    for index, content in enumerate(contents):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append(Message(role=role, content=content))
    FileMemory(tmp_path / "mem").save_session(session_id, messages)
    return tmp_path / "mem" / f"{session_id}.json"


# --- memory list --------------------------------------------------------


def test_list_without_storage_reports_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    code = main(["memory", "list", "--config", str(config_path)])

    captured = capsys.readouterr()
    assert code == 0, "пустое хранилище — не ошибка"
    assert "Память пуста" in captured.out
    assert captured.err == ""


def test_list_shows_sessions_with_message_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _save_session(tmp_path, "alpha", "Привет", "Здравствуйте")
    _save_session(tmp_path, "beta", "Ещё один диалог")

    code = main(["memory", "list", "-c", str(_write_config(tmp_path))])

    captured = capsys.readouterr()
    assert code == 0
    assert "alpha" in captured.out
    assert "beta" in captured.out
    assert "Всего сессий: 2" in captured.out
    # счётчик сообщений: у alpha их два, у beta — одно
    alpha_line = next(line for line in captured.out.splitlines() if line.startswith("alpha"))
    beta_line = next(line for line in captured.out.splitlines() if line.startswith("beta"))
    assert alpha_line.split()[1] == "2"
    assert beta_line.split()[1] == "1"


def test_list_short_config_flag_works(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _save_session(tmp_path, "alpha", "Привет")

    code = main(["memory", "list", "-c", str(_write_config(tmp_path))])

    assert code == 0
    assert "alpha" in capsys.readouterr().out


def test_list_works_without_config_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без config.toml используются значения по умолчанию, а не ошибка."""
    monkeypatch.chdir(tmp_path)

    code = main(["memory", "list"])

    captured = capsys.readouterr()
    assert code == 0, "команда полезна и в проекте без конфигурации"
    assert ".ember/memory" in captured.out


def test_memory_sees_sessions_when_memory_disabled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Управлять сохранённым можно и при ``enabled = false``."""
    _save_session(tmp_path, "alpha", "Привет")
    config_path = _write_config(tmp_path, enabled=False)

    code = main(["memory", "list", "-c", str(config_path)])

    captured = capsys.readouterr()
    assert code == 0
    assert "alpha" in captured.out, "флаг enabled относится к записи, не к управлению"


# --- memory show --------------------------------------------------------


def test_show_prints_dialog(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _save_session(tmp_path, "alpha", "Вопрос", "Ответ")

    code = main(["memory", "show", "alpha", "-c", str(_write_config(tmp_path))])

    captured = capsys.readouterr()
    assert code == 0
    assert "user: Вопрос" in captured.out
    assert "assistant: Ответ" in captured.out
    assert "сообщений 2" in captured.out


def test_show_missing_session_returns_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    code = main(["memory", "show", "нет-такой", "-c", str(config_path)])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.startswith("ошибка:"), "ошибки CLI — в stderr с общим префиксом"
    assert "не найдена" in captured.err


def test_show_missing_storage_directory_returns_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path, directory=str(tmp_path / "нет-директории"))

    code = main(["memory", "show", "alpha", "-c", str(config_path)])

    captured = capsys.readouterr()
    assert code == 1
    assert "не найдена" in captured.err


# --- memory delete ------------------------------------------------------


def test_delete_removes_only_target_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file_to_delete = _save_session(tmp_path, "alpha", "Привет")
    other = _save_session(tmp_path, "beta", "Привет")

    code = main(["memory", "delete", "alpha", "-c", str(_write_config(tmp_path))])

    captured = capsys.readouterr()
    assert code == 0
    assert not file_to_delete.exists()
    assert other.is_file(), "чужая сессия не должна пострадать"
    assert "alpha" in captured.out


def test_delete_missing_session_returns_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(tmp_path)

    code = main(["memory", "delete", "нет-такой", "-c", str(config_path)])

    captured = capsys.readouterr()
    assert code == 1
    assert "не найдена" in captured.err


# --- memory clear -------------------------------------------------------


def test_clear_requires_yes_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _save_session(tmp_path, "alpha", "Привет")
    _save_session(tmp_path, "beta", "Привет")
    config_path = _write_config(tmp_path)

    code = main(["memory", "clear", "-c", str(config_path)])

    captured = capsys.readouterr()
    assert code == 2
    assert "yes" in captured.err
    assert len(list((tmp_path / "mem").glob("*.json"))) == 2, "без --yes ничего не удаляем"


def test_clear_with_yes_removes_all_sessions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _save_session(tmp_path, "alpha", "Привет")
    _save_session(tmp_path, "beta", "Привет")
    config_path = _write_config(tmp_path)

    code = main(["memory", "clear", "--yes", "-c", str(config_path)])

    captured = capsys.readouterr()
    assert code == 0
    assert list((tmp_path / "mem").glob("*.json")) == []
    assert "Удалено сессий: 2" in captured.out


def test_clear_on_empty_storage_is_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["memory", "clear", "--yes", "-c", str(_write_config(tmp_path))])

    captured = capsys.readouterr()
    assert code == 0, "удалять нечего — не ошибка"
    assert "Память пуста" in captured.out


# --- разбор аргументов --------------------------------------------------


def test_memory_requires_action(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["memory"])

    capsys.readouterr()
    assert exc_info.value.code == 2


def test_explicit_missing_config_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["memory", "list", "-c", str(tmp_path / "nope.toml")])

    captured = capsys.readouterr()
    assert code == 2, "опечатка в явном пути не должна оставаться незамеченной"
    assert "не найден" in captured.err
