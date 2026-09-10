"""Тесты CLI ember-agent (на MockProvider, без сети и ключей)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from ember_agent.cli import main

#: Секция памяти для тестовых конфигураций: хранилище — рядом, в tmp_path.
MEMORY_SECTION = textwrap.dedent("""\
    [memory]
    enabled = true
    directory = "mem"
    session_id = "s1"
    """)


def _write_mock_config(tmp_path: Path, system_prompt: str = "Ты тестовый агент.") -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        textwrap.dedent(f"""\
            [agent]
            system_prompt = "{system_prompt}"
            """),
        encoding="utf-8",
    )
    return config_path


def test_run_single_message_with_mock(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run", "--config", str(_write_mock_config(tmp_path)), "--message", "Привет"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip(), "агент должен вернуть непустой ответ"
    assert captured.err == ""


def test_run_accepts_config_from_default_location(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_mock_config(tmp_path)

    code = main(["run", "--message", "Привет"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip()


def test_run_missing_config_returns_error_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["run", "--config", str(tmp_path / "nope.toml"), "--message", "Привет"])

    captured = capsys.readouterr()
    assert code == 2
    assert "не найден" in captured.err


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert "ember-agent" in capsys.readouterr().out


# --- память -------------------------------------------------------------


def test_memory_disabled_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_mock_config(tmp_path)

    code = main(["run", "--message", "Привет"])

    capsys.readouterr()
    assert code == 0
    assert not (tmp_path / ".ember").exists(), "без [memory] на диск ничего не пишем"


def test_run_with_memory_saves_session_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_mock_config(tmp_path)
    (tmp_path / "config.toml").write_text(MEMORY_SECTION, encoding="utf-8")

    code = main(["run", "--message", "Привет"])

    capsys.readouterr()
    assert code == 0
    assert (tmp_path / "mem" / "s1.json").is_file()


def test_memory_keeps_dialog_between_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(MEMORY_SECTION, encoding="utf-8")

    first = main(["run", "--message", "Первое сообщение"])
    capsys.readouterr()
    second = main(["run", "--message", "Второе сообщение"])
    capsys.readouterr()

    saved = (tmp_path / "mem" / "s1.json").read_text(encoding="utf-8")
    assert (first, second) == (0, 0)
    assert "Первое сообщение" in saved, "прошлая сессия должна быть на диске"
    assert "Второе сообщение" in saved, "новая сессия должна дописаться"


def test_session_flag_enables_memory_without_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_mock_config(tmp_path)

    code = main(["run", "--message", "Привет", "--session", "cli"])

    capsys.readouterr()
    assert code == 0
    assert (tmp_path / ".ember" / "memory" / "cli.json").is_file()


def test_session_flag_overrides_configured_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(MEMORY_SECTION, encoding="utf-8")

    code = main(["run", "--message", "Привет", "--session", "other"])

    capsys.readouterr()
    assert code == 0
    assert (tmp_path / "mem" / "other.json").is_file()
    assert not (tmp_path / "mem" / "s1.json").exists()


def test_no_memory_disables_configured_memory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(MEMORY_SECTION, encoding="utf-8")

    code = main(["run", "--message", "Привет", "--no-memory"])

    capsys.readouterr()
    assert code == 0
    assert not (tmp_path / "mem").exists()


def test_session_and_no_memory_are_mutually_exclusive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_mock_config(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(["run", "--session", "s", "--no-memory"])

    capsys.readouterr()
    assert exc_info.value.code == 2
