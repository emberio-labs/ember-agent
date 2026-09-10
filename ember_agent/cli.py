"""Командная строка ember-agent.

Команда ``run`` читает TOML-конфигурацию и запускает агента:
в интерактивном диалоге (по умолчанию) или с разовым запросом ``--message``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from ember_agent import __version__
from ember_agent.config import DEFAULT_CONFIG_FILE, AgentConfig, ConfigError, load_config
from ember_agent.factory import build_agent, resolve_session_id
from ember_agent.repl import run_repl


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ember-agent",
        description=(
            "Готовый к запуску агент на базе ember: настройка в TOML, запуск одной командой."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    run = subparsers.add_parser("run", help="запустить агента из конфигурации")
    run.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_FILE,
        help=f"путь к TOML-конфигурации (по умолчанию: {DEFAULT_CONFIG_FILE})",
    )
    run.add_argument(
        "-m",
        "--message",
        help="разовый запрос без интерактивного диалога",
    )
    memory_group = run.add_mutually_exclusive_group()
    memory_group.add_argument(
        "--session",
        metavar="ID",
        help="включить межсессионную память и продолжить диалог в сессии ID",
    )
    memory_group.add_argument(
        "--no-memory",
        action="store_true",
        help="выключить память, даже если она включена в конфигурации",
    )
    return parser


def _apply_memory_overrides(config: AgentConfig, args: argparse.Namespace) -> AgentConfig:
    """Учесть CLI-флаги памяти: они перекрывают секцию ``[memory]`` из TOML.

    ``--no-memory`` выключает память независимо от конфигурации; ``--session ID``
    включает её и переключает на указанную сессию (явно выбранная сессия —
    достаточное намерение пользователя, даже если ``enabled = false``).
    """
    memory = config.memory
    if args.no_memory:
        memory = replace(memory, enabled=False)
    elif args.session:
        memory = replace(memory, enabled=True, session_id=args.session)
    return replace(config, memory=memory)


def _resolve_memory_session(config: AgentConfig) -> tuple[AgentConfig, str | None]:
    """Зафиксировать id сессии памяти на этот запуск.

    Если ``session_id`` не задан, он генерируется здесь, а не только в фабрике:
    так CLI знает id и может подсказать команду продолжения диалога.
    Возвращается конфигурация (с уже явным id) и сам id либо ``None``, если
    память выключена.
    """
    session_id = resolve_session_id(config.memory)
    if session_id is None or session_id == config.memory.session_id:
        return config, session_id
    return replace(config, memory=replace(config.memory, session_id=session_id)), session_id


def _print_session_hint(session_id: str, directory: str) -> None:
    """Подсказать id сессии после разового запуска.

    Пишем в stderr: stdout остаётся чистым ответом агента (удобно для скриптов).
    """
    message = f"🗂 сессия памяти: {session_id} ({directory}) — продолжить: --session {session_id}"
    print(message, file=sys.stderr)


def _print_error(message: str) -> None:
    print(f"ошибка: {message}", file=sys.stderr)


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        config = _apply_memory_overrides(load_config(Path(args.config)), args)
    except ConfigError as exc:
        _print_error(str(exc))
        return 2

    try:
        if args.message:
            config, session_id = _resolve_memory_session(config)
            with build_agent(config) as agent:
                print(agent.run(args.message))
            if session_id is not None:
                _print_session_hint(session_id, config.memory.directory)
            return 0
        # Интерактивный диалог живёт в ember_agent.repl: там же создаётся
        # агент с колбэками показа вызовов инструментов.
        return run_repl(config)
    except ConfigError as exc:
        _print_error(str(exc))
        return 2
    except Exception as exc:
        _print_error(str(exc))
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return _cmd_run(args)
    except KeyboardInterrupt:
        return 130
    return 0  # недостижимо: subparser обязателен
