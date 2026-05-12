from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import cast

from codeseam.cli.commands.analyze import (
    analyze_command,
    profile_command,
)
from codeseam.cli.commands.cache import cache_clear_command, cache_stats_command
from codeseam.cli.commands.explain import explain_command
from codeseam.cli.commands.init import init_command
from codeseam.cli.exit_codes import (
    CONFIG_ERROR,
    INTERNAL_ERROR,
    INTERRUPTED,
    OK,
    USER_INPUT_ERROR,
)
from codeseam.cli.models import CliOutput, cli_output
from codeseam.cli.output import render_cli_output
from codeseam.cli.spec import ArgumentSpec, CommandSpec, command_specs
from codeseam.platform import CodeseamError, ConfigError


class CodeseamArgumentParser(argparse.ArgumentParser):
    pass


class ParserError(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except ParserError as exc:
        output = cli_output(
            "parser_error",
            parser=parser,
            message=str(exc),
            exit_code=USER_INPUT_ERROR,
        )
        render_cli_output(output)
        return output.exit_code
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else USER_INPUT_ERROR
    if not hasattr(args, "handler"):
        output = cli_output("help", parser=parser, exit_code=OK)
    else:
        output = _run_handler(args)
    render_cli_output(output)
    return output.exit_code


def _run_handler(args: argparse.Namespace) -> CliOutput:
    try:
        return cast(CliOutput, args.handler(args))
    except KeyboardInterrupt:
        return cli_output("cancelled", exit_code=INTERRUPTED)
    except ConfigError as exc:
        return cli_output("error", message=str(exc), prefix="config error", exit_code=CONFIG_ERROR)
    except CodeseamError as exc:
        return cli_output("error", message=str(exc), exit_code=int(exc.exit_code))
    except Exception as exc:
        return cli_output(
            "error",
            message=str(exc),
            prefix="internal error",
            exit_code=INTERNAL_ERROR,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = CodeseamArgumentParser(
        prog="codeseam",
        description=(
            "Analyze a repository for structural refactor opportunities and write "
            "agent-focused report artifacts."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    for name, spec in command_specs().items():
        _add_command(subparsers, name, spec)
    return parser


def _add_command(
    subparsers: argparse._SubParsersAction[CodeseamArgumentParser],
    name: str,
    spec: CommandSpec,
) -> None:
    parser = subparsers.add_parser(
        name,
        description=str(spec["description"]),
        help=str(spec["help"]),
    )
    _add_arguments(parser, spec.get("arguments", ()))
    if handler := spec.get("handler"):
        parser.set_defaults(handler=_handler(str(handler)))
    if subcommands := spec.get("subcommands"):
        nested = parser.add_subparsers(dest=str(spec["subcommand_dest"]))
        for child_name, child_spec in cast(dict[str, CommandSpec], subcommands).items():
            _add_command(nested, child_name, child_spec)


def _add_arguments(parser: argparse.ArgumentParser, arguments: object) -> None:
    for spec in cast(tuple[ArgumentSpec, ...], arguments):
        names = cast(tuple[str, ...], spec["names"])
        kwargs = {key: value for key, value in spec.items() if key != "names"}
        parser.add_argument(*names, **kwargs)


def _handler(name: str) -> Callable[[argparse.Namespace], CliOutput]:
    handlers: dict[str, Callable[[argparse.Namespace], CliOutput]] = {
        "analyze": analyze_command,
        "profile": profile_command,
        "init": init_command,
        "explain": explain_command,
        "cache_stats": cache_stats_command,
        "cache_clear": cache_clear_command,
    }
    return handlers[name]
