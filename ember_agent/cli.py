"""Командная строка ember-agent.

Команда ``run`` читает TOML-конфигурацию и запускает агента:
в интерактивном диалоге (по умолчанию) или с разовым запросом ``--message``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ember_agent import __version__
from ember_agent.config import DEFAULT_CONFIG_FILE, ConfigError, load_config
from ember_agent.factory import build_agent
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
    return parser


def _print_error(message: str) -> None:
    print(f"ошибка: {message}", file=sys.stderr)


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        config = load_config(Path(args.config))
    except ConfigError as exc:
        _print_error(str(exc))
        return 2

    try:
        if args.message:
            with build_agent(config) as agent:
                print(agent.run(args.message))
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
