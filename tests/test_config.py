"""Тесты чтения и валидации конфигурации."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from ember_agent.config import (
    AgentConfig,
    ConfigError,
    load_config,
)


def test_defaults_use_mock_provider() -> None:
    config = AgentConfig()

    assert config.provider.type == "mock"
    assert config.provider.model is None
    assert config.provider.api_key_env == "OPENAI_API_KEY"
    assert config.system_prompt
    assert config.mcp_servers == []


def test_load_full_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        textwrap.dedent(
            """\
            [agent]
            system_prompt = "Бот поддержки"

            [provider]
            type = "openai"
            model = "gpt-4o-mini"
            base_url = "https://api.example.com/v1"

            [[mcp.servers]]
            transport = "stdio"
            command = "python"
            args = ["server.py"]

            [[mcp.servers]]
            transport = "http"
            url = "https://mcp.example.com/mcp"
            headers = { Authorization = "Bearer token" }
            """
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.system_prompt == "Бот поддержки"
    assert config.provider.type == "openai"
    assert config.provider.model == "gpt-4o-mini"
    assert config.provider.api_key_env == "OPENAI_API_KEY"
    assert config.provider.base_url == "https://api.example.com/v1"
    assert len(config.mcp_servers) == 2

    stdio, http = config.mcp_servers
    assert stdio.transport == "stdio"
    assert stdio.command == "python"
    assert stdio.args == ["server.py"]
    assert http.transport == "http"
    assert http.url == "https://mcp.example.com/mcp"
    assert http.headers == {"Authorization": "Bearer token"}


def test_empty_file_means_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")

    config = load_config(config_path)

    assert config.provider.type == "mock"
    assert config.system_prompt == "Ты полезный и краткий помощник."


def test_invalid_provider_type_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[provider]\ntype = "unknown"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="Неизвестный тип провайдера"):
        load_config(config_path)


def test_invalid_mcp_transport_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[[mcp.servers]]\ntransport = "ssh"\ncommand = "echo"\n', encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="transport"):
        load_config(config_path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="не найден"):
        load_config(tmp_path / "absent.toml")


def test_invalid_toml_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("это [не t[[oml\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="TOML"):
        load_config(config_path)
