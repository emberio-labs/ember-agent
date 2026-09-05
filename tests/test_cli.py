"""Тесты CLI ember-agent (на MockProvider, без сети и ключей)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from ember_agent.cli import main


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
