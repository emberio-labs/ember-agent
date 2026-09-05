"""Командная строка ember-agent.

Команда ``run`` читает TOML-конфигурацию и запускает агента:
в интерактивном диалоге (по умолчанию) или с разовым запросом ``--message``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ember_agent import __version__
from ember_agent.config import DEFAULT_CONFIG_FILE, ConfigError, load_config
from ember_agent.factory import build_agent

_QUIT_COMMANDS = frozenset({"exit", "quit", "выход"})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ember-agent",
        description=(
            "Готовый к запуску агент на базе ember: настройка в TOML, "
            "запуск одной командой."
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
    return parser


def _print_error(message: str) -> None:
    print(f"ошибка: {message}", file=sys.stderr)


def _run_repl(agent: Any) -> int:
    """Интерактивный диалог с агентом."""
    print("Диалог с агентом. Выход: 'exit', 'quit', 'выход' или Ctrl+D/Ctrl+C.")
    while True:
        try:
            line = input("\nвы: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.lower() in _QUIT_COMMANDS:
            return 0
        if not line:
            continue
        try:
            print(f"агент: {agent.run(line)}")
        except Exception as exc:  # показываем ошибку и продолжаем диалог
            _print_error(str(exc))


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        config = load_config(Path(args.config))
    except ConfigError as exc:
        _print_error(str(exc))
        return 2

    try:
        with build_agent(config) as agent:
            if args.message:
                print(agent.run(args.message))
                return 0
            return _run_repl(agent)
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
