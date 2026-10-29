"""Synchronous script execution and an interactive, persistent REPL."""

import argparse
import sys
from pathlib import Path

from . import ScriptRunner
from .slip_core import is_function
from .slip_syntax import format_source


def display(value):
    if is_function(value):
        return '<function>'
    try:
        return format_source(value)
    except (TypeError, ValueError):
        # Native handles need a display representation, not a source literal.
        return repr(value)


def print_result(result):
    reported = False
    for effect in result.side_effects:
        topics = effect.get('topics', [])
        message = effect.get('message', '')
        if 'stdout' in topics:
            print(message)
        if 'stderr' in topics:
            print(message, file=sys.stderr)
            reported |= message == result.error_message
    if result.status == 'err':
        if not reported:
            print(result.error_message, file=sys.stderr)
    elif result.value is not None:
        print(display(result.value))


def run_script_file(file_path):
    path = Path(file_path).resolve()
    try:
        source = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as error:
        print(f'Error reading {file_path}: {error}', file=sys.stderr)
        return 1
    with ScriptRunner() as runner:
        result = runner.handle_script(source, source_path=path)
        print_result(result)
        return int(result.status == 'err')


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='slip', description='Run SLIP scripts.',
    )
    parser.add_argument(
        'script', nargs='?', help='script file; omit for a REPL',
    )
    args = parser.parse_args(argv)
    try:
        if args.script is not None:
            return run_script_file(args.script)
        print('SLIP REPL')
        print("Type 'exit' or press Ctrl+D to quit.")
        with ScriptRunner() as runner:
            while True:
                try:
                    line = input('>> ').strip()
                except EOFError:
                    print('\nExiting.')
                    break
                if line == 'exit':
                    break
                if line:
                    print_result(runner.handle_script(line))
        return 0
    except KeyboardInterrupt:
        print('\nExiting.')
        return 130
