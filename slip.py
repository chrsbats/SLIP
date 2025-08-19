import asyncio
import sys
import inspect
from pathlib import Path
import yaml

from koine import Parser
from slip.slip_runtime import StdLib
from slip.slip_datatypes import Scope, Code
from slip.slip_interpreter import Evaluator
from slip.slip_printer import Printer
from slip.slip_transformer import SlipTransformer

# A basic awaitable input prompt.
async def ainput(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    sys.stdout.write(prompt)
    sys.stdout.flush()
    return await loop.run_in_executor(None, sys.stdin.readline)

async def main():
    """The main REPL loop."""
    print("SLIP REPL v0.1")
    print("Type '.exit' or press Ctrl+D to quit.")

    # 1. Setup
    grammar_path = Path(__file__).parent / "slip_grammar.yaml"
    with grammar_path.open() as f:
        grammar_def = yaml.safe_load(f)
    parser = Parser(grammar_def)
    transformer = SlipTransformer()
    evaluator = Evaluator()
    printer = Printer()
    
    # 2. Create persistent scopeironment and load stdlib
    root_scope = Scope()
    stdlib = StdLib(evaluator)
    
    for name, member in inspect.getmembers(stdlib):
        if name.startswith('_') and not name.startswith('__') and callable(member):
            slip_name = name[1:].replace('_', '-')
            root_scope[slip_name] = member

    # 3. Load core.slip
    core_slip_path = Path(__file__).parent / "core.slip"
    if core_slip_path.exists():
        print("Loading core.slip...")
        try:
            core_source = core_slip_path.read_text()
            raw_ast = parser.parse(core_source)
            if raw_ast.get('status') == 'success':
                transformed_ast = transformer.transform(raw_ast['ast'])
                await evaluator.eval(transformed_ast.nodes, root_scope)
                print("Core library loaded.")
            else:
                print(f"Error parsing core.slip: {raw_ast.get('error_message')}", file=sys.stderr)

        except Exception as e:
            print(f"Error loading core.slip: {e}", file=sys.stderr)
            print("NOTE: Some primitives (while, foreach) may not be implemented yet.", file=sys.stderr)
    else:
        print("Warning: core.slip not found. Some standard functions will be missing.", file=sys.stderr)


    # 4. REPL Loop
    while True:
        try:
            # Reset side effects for each evaluation
            evaluator.side_effects.clear()

            line = (await ainput(">> ")).strip()

            if not line:
                continue
            if line == ".exit":
                break

            # Parse, Transform, Evaluate
            raw_ast = parser.parse(line)
            if raw_ast.get('status') != 'success':
                print(f"Parse Error: {raw_ast.get('error_message')}", file=sys.stderr)
                continue

            transformed_ast = transformer.transform(raw_ast['ast'])
            result = await evaluator.eval(transformed_ast.nodes, root_scope)
            
            # Print side effects (from `emit`)
            for effect in evaluator.side_effects:
                # Basic handler for REPL's 'print' alias
                if effect.get('topics') == ['stdout']:
                    print(effect.get('message', ''))

            # Print final result
            if result is not None:
                print(printer.pformat(result))

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
