import os
import pickle
import subprocess
import sys
from dataclasses import fields, is_dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

DIRECTORY = Path(__file__).resolve().parents[1]
from slip import ScriptRunner, slip_syntax as syntax, slip_cache  # noqa: E402
from slip.slip_core import Code, Scope, execute  # noqa: E402
from slip.slip_resources import read_file  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SLIP_CACHE_DIR", str(tmp_path / "cache"))
    slip_cache.compiled.cache_clear()
    yield
    slip_cache.compiled.cache_clear()


def assert_unbound(value):
    assert not callable(value) and not isinstance(value, Scope)
    if isinstance(value, Code):
        assert value.stacks is None
    if isinstance(value, list):
        for item in value:
            assert_unbound(item)
    elif is_dataclass(value):
        for field in fields(value):
            assert_unbound(getattr(value, field.name))


def count_parses(monkeypatch):
    calls = []
    original = syntax.parse

    def counted(source):
        calls.append(source)
        return original(source)

    monkeypatch.setattr(syntax, "parse", counted)
    return calls


def test_repeated_reads_parse_once_and_recursively_isolate_syntax(
    tmp_path, monkeypatch,
):
    source = """
        f: fn {x: `number` |where x > 0} [x + 1]
        data: #{items: #[1, 2]}
        query: [data.items[.hp > 1][1:5]]
        configured: [file://data.json#(encoding: 'utf-8')]
        text: "hello {{f 1}}"
    """
    path = tmp_path / "syntax.slip"
    path.write_text(source)
    calls = count_parses(monkeypatch)
    first = read_file(path, {})
    cold_calls = list(calls)
    second = read_file(path, {})
    assert isinstance(first, Code) and isinstance(second, Code)
    assert calls == cold_calls and calls.count(source) == 1
    assert first == second and first is not second
    assert_unbound(first)
    original = syntax.format_source(second)
    first[0][2].parameters[0].annotation.path.keys[0] = "string"
    first[0][3][0][1].keys[0] = "-"
    first[1][1].code.clear()
    first[2][1][0][0].keys[-1].end[0][0] = 9
    first[3][1][0][0].options.clear()
    first[4][1].parts[1].clear()
    assert syntax.format_source(second) == original
    third = read_file(path, {})
    assert syntax.format_source(third) == original
    assert_unbound(third)
    assert first.source_path == second.source_path == str(path.resolve())


def test_cached_code_binds_in_each_receiving_runner(
    tmp_path, monkeypatch,
):
    path = tmp_path / "capture.slip"
    path.write_text("read: fn {x} [host-number + x]\n")
    calls = count_parses(monkeypatch)
    with ScriptRunner() as first, ScriptRunner() as second:
        first.source_dir = second.source_dir = str(tmp_path)
        first.root_scope["host-number"] = lambda: 10
        second.root_scope["host-number"] = lambda: 20
        source = "m: import `file://capture.slip`; m.read 3"
        one = first.handle_script(source)
        two = second.handle_script(source)
        assert one.status == two.status == "ok", (
            one.error_message, two.error_message,
        )
        assert (one.value, two.value) == (13, 23)
        assert calls.count(path.read_text()) == 1
        assert_unbound(read_file(path, {}))


def test_concurrent_file_reads_share_cold_compilation(
    tmp_path, monkeypatch,
):
    path = tmp_path / "concurrent.slip"
    source = "value: 7\n"
    path.write_text(source)
    calls = count_parses(monkeypatch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        reads = [pool.submit(read_file, path, {}) for _ in range(4)]
        copies = [read.result(timeout=30) for read in reads]
    assert calls == [source]
    assert len({id(code) for code in copies}) == 4
    assert all(code == copies[0] for code in copies)


def test_content_changes_invalidate_despite_unchanged_file_stats(
    tmp_path,
):
    path = tmp_path / "changing.slip"
    path.write_text("value: 7\nvalue\n")
    previous = path.stat()
    first = read_file(path, {})
    path.write_text("value: 9\nvalue\n")
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    second = read_file(path, {})
    assert execute(first, Scope()) == 7
    assert execute(second, Scope()) == 9
    assert path.stat().st_size == previous.st_size
    assert path.stat().st_mtime_ns == previous.st_mtime_ns


@pytest.mark.parametrize("mode", ["disabled", "unavailable"])
def test_disk_cache_failure_keeps_isolated_memory_caching(
    tmp_path, monkeypatch, mode,
):
    root = tmp_path / "not-a-directory"
    root.write_text("occupied")
    monkeypatch.setenv(
        "SLIP_CACHE_DIR", "" if mode == "disabled" else str(root),
    )
    source = f"value: '{mode}'\n"
    path = tmp_path / "memory.slip"
    path.write_text(source)
    calls = count_parses(monkeypatch)
    first, second = read_file(path, {}), read_file(path, {})
    assert calls == [source]
    assert first == second and first is not second
    first.clear()
    assert second
    assert root.read_text() == "occupied"
    assert not (tmp_path / "cache").exists()


def test_source_errors_propagate_and_encoding_override_returns_text(tmp_path):
    missing = tmp_path / "missing.slip"
    with pytest.raises(FileNotFoundError):
        read_file(missing, {})
    broken = tmp_path / "broken.slip"
    broken.write_text("[unterminated")
    with pytest.raises(SyntaxError):
        read_file(broken, {})
    assert read_file(broken, {"encoding": "utf-8"}) == "[unterminated"


WORKER = """
import os
import sys
from pathlib import Path
from slip import slip_syntax
from slip.slip_resources import read_file
from slip.slip_core import Code
parses = []
original = slip_syntax.parse
def parse(source):
    if os.environ.get('NO_PARSER'):
        raise AssertionError('parser used on a persistent hit')
    parses.append(source)
    return original(source)
slip_syntax.parse = parse
if os.environ.get('NO_PARSER'):
    def forbidden():
        raise AssertionError('parser constructed on a persistent hit')
    slip_syntax.parser = forbidden
if os.environ.get('WAIT_FOR_START'):
    print('ready', flush=True)
    assert input() == 'start'
path = Path(sys.argv[1])
code = read_file(path, {})
assert isinstance(code, Code) and code.stacks is None and code
assert code.source_path == str(path.resolve())
assert 'slip.slip_runtime' not in sys.modules
assert 'slip.slip_interpreter' not in sys.modules
print(len(parses), flush=True)
"""


def worker_command(path):
    return [sys.executable, "-c", WORKER, str(path)]


def load_in_process(path, *, no_parser=False):
    result = subprocess.run(
        worker_command(path), env={**os.environ,
                                   "NO_PARSER": "1" if no_parser else "",
                                   "WAIT_FOR_START": ""},
        cwd=path.parent, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return int(result.stdout)


def test_new_process_reuses_content_across_paths_and_reattaches_path(tmp_path):
    first, second = tmp_path / "first.slip", tmp_path / "second.slip"
    first.write_text("f: fn {x} [x + 1]\n")
    second.write_text(first.read_text())
    assert load_in_process(first) == 1
    assert load_in_process(second, no_parser=True) == 0
    cache = tmp_path / "cache/transformed"
    assert len(list((cache / "artifacts").glob("*.pickle"))) == 1
    indexes = list((cache / "paths").glob("*.index"))
    assert len(indexes) == 2
    assert len({index.read_text() for index in indexes}) == 1


@pytest.mark.parametrize("payload", [b"not a pickle", pickle.dumps(None)])
def test_corrupt_artifacts_reparse_and_repair(tmp_path, payload):
    path = tmp_path / "corrupt.slip"
    path.write_text("value: 7\n")
    assert load_in_process(path) == 1
    artifact = next((tmp_path / "cache").rglob("*.pickle"))
    artifact.write_bytes(payload)
    assert load_in_process(path) == 1
    assert artifact.read_bytes() != payload
    assert load_in_process(path, no_parser=True) == 0


def test_last_updated_path_releases_superseded_artifact(tmp_path):
    first, second = tmp_path / "first.slip", tmp_path / "second.slip"
    first.write_text("value: 7\n")
    second.write_text(first.read_text())
    load_in_process(first)
    load_in_process(second, no_parser=True)
    artifacts = tmp_path / "cache/transformed/artifacts"
    shared = next(artifacts.glob("*.pickle"))
    first.write_text("value: 9\n")
    assert load_in_process(first) == 1
    assert shared.exists() and len(list(artifacts.glob("*.pickle"))) == 2
    second.write_text(first.read_text())
    assert load_in_process(second, no_parser=True) == 0
    assert not shared.exists() and len(list(artifacts.glob("*.pickle"))) == 1


def test_revisiting_old_content_republishes_collected_memory_entry(tmp_path):
    path = tmp_path / "revisit.slip"
    path.write_text("value: 1\n")
    read_file(path, {})
    path.write_text("value: 2\n")
    read_file(path, {})
    path.write_text("value: 1\n")
    read_file(path, {})
    assert load_in_process(path, no_parser=True) == 0


def test_failed_artifact_publication_still_loads_and_can_recover(tmp_path):
    path = tmp_path / "publication.slip"
    path.write_text("value: 7\n")
    original = read_file(path, {})
    artifact = next((tmp_path / "cache").rglob("*.pickle"))
    artifact.unlink()
    artifact.mkdir()
    assert read_file(path, {}) == original
    artifact.rmdir()
    assert read_file(path, {}) == original
    assert artifact.is_file()
    assert load_in_process(path, no_parser=True) == 0


def test_pipeline_change_invalidates_and_obsolete_directories_are_removed(
    tmp_path, monkeypatch,
):
    old = tmp_path / "cache/transformed-v2"
    old.mkdir(parents=True)
    (old / "old.pickle").write_bytes(b"obsolete")
    path = tmp_path / "pipeline.slip"
    path.write_text("value: 7\n")
    calls = count_parses(monkeypatch)
    read_file(path, {})
    assert not old.exists()
    previous = slip_cache.pipeline_fingerprint()
    try:
        with monkeypatch.context() as changed:
            changed.setattr(slip_cache, "version", lambda name: "new-version")
            slip_cache.pipeline_fingerprint.cache_clear()
            assert slip_cache.pipeline_fingerprint() != previous
            read_file(path, {})
        assert calls == [path.read_text(), path.read_text()]
    finally:
        slip_cache.pipeline_fingerprint.cache_clear()


def test_cache_uses_xdg_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SLIP_CACHE_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    path = tmp_path / "default.slip"
    path.write_text("value: 7\n")
    read_file(path, {})
    assert list((tmp_path / "xdg/slip/transformed/artifacts").glob("*.pickle"))


def test_concurrent_processes_compile_shared_cold_content_once(tmp_path):
    first, second = tmp_path / "first.slip", tmp_path / "second.slip"
    first.write_text("\n".join(f"value-{i}: {i}" for i in range(100)))
    second.write_text(first.read_text())
    workers = []
    try:
        for path in (first, second):
            workers.append(subprocess.Popen(
                worker_command(path), cwd=tmp_path,
                env={**os.environ, "WAIT_FOR_START": "1"},
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            ))
        for worker in workers:
            assert worker.stdout.readline() == "ready\n"
        for worker in workers:
            worker.stdin.write("start\n")
            worker.stdin.flush()
        counts = []
        for worker in workers:
            output, error = worker.communicate(timeout=30)
            assert worker.returncode == 0, error
            counts.append(int(output))
        assert sorted(counts) == [0, 1]
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.wait(timeout=5)
