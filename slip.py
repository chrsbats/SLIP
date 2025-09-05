import asyncio
import sys
from pathlib import Path

from slip.slip_runtime import ScriptRunner
from slip.slip_printer import Printer

# A basic awaitable input prompt.
async def ainput(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    sys.stdout.write(prompt)
    sys.stdout.flush()
    return await loop.run_in_executor(None, sys.stdin.readline)

async def run_script_file(file_path: str):
    """Run a SLIP script file non-interactively and exit with appropriate status."""
    runner = ScriptRunner()
    printer = Printer()
    p = Path(file_path)
    try:
        source = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Error: file not found: {file_path}", file=sys.stderr)
        raise SystemExit(1)
    runner.source_dir = str(p.parent.resolve())
    result = await runner.handle_script(source)
    # Print side effects (from `emit`)
    for effect in result.side_effects:
        if effect.get('topics') == ['stdout']:
            print(effect.get('message', ''))
    if result.status == 'error':
        print(result.format_error(), file=sys.stderr)
        raise SystemExit(1)
    if result.value is not None:
        print(printer.pformat(result.value))

async def main():
    """Run a script file when provided, otherwise start the interactive REPL."""
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        # Treat argv[1] as a script file when it's not a flag; run_script_file handles missing files
        if not arg.startswith("-"):
            await run_script_file(arg)
            return

    print("SLIP REPL v0.1")
    print("Type 'exit' or press Ctrl+D to quit.")

    # Setup
    runner = ScriptRunner()
    printer = Printer()
    runner.source_dir = str(Path.cwd())
    await runner._initialize()

    # REPL Loop
    while True:
        try:
            raw = await ainput(">> ")
            if raw == "":
                raise EOFError
            line = raw.strip()

            if not line:
                continue
            if line == "exit":
                break

            # Parse, run through ScriptRunner
            result = await runner.handle_script(line)

            if result.status == 'error':
                # Pretty, location-aware message
                print(result.format_error(), file=sys.stderr)
                continue

            # Print side effects (from `emit`)
            for effect in result.side_effects:
                if effect.get('topics') == ['stdout']:
                    print(effect.get('message', ''))

            # Print final result
            if result.value is not None:
                print(printer.pformat(result.value))

        except EOFError:
            print("\nExiting.")
            break
        except Exception as e:
            # Catch evaluation errors and print them nicely
            print(f"Error: {e}", file=sys.stderr)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting.")
