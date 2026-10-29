"""Quoted strings share escapes/layout; double quotes add interpolation."""

import pytest

from slip import ScriptRunner
from slip.slip_core import IString
from slip.slip_syntax import format_source, parse


@pytest.mark.parametrize("delimiter", ["'", '"'])
@pytest.mark.parametrize(("content", "expected"), [
    (r"a\nb\tc\r\\d\'\"", "a\nb\tc\r\\d'\""),
    (r"\nHello.\n", "\nHello.\n"),
    (r"  Hello.\n    Welcome.  ", "  Hello.\n    Welcome.  "),
    ("  Hello.  ", "  Hello.  "),
    ("\n    Hello.\n    Welcome.\n", "Hello.\nWelcome."),
    ("\r\n    Hello.\r\n    Welcome.\r\n", "Hello.\nWelcome."),
    ("\r    Hello.\r    Welcome.\r", "Hello.\nWelcome."),
    ("\n\n    Hello.\n\n", "\nHello.\n"),
    ("\n    \\nHello.\\n\n", "\nHello.\n"),
    ("\n      Hello.  \n        Welcome.\n", "Hello.  \n  Welcome."),
])
def test_string_content_and_source_round_trip(delimiter, content, expected):
    source = delimiter + content + delimiter
    with ScriptRunner() as runner:
        result = runner.handle_script(source)
        assert result.status == "ok", result.error_message
        assert result.value == expected
        assert type(result.value) is (str if delimiter == "'" else IString)
        printed = format_source(parse(source))
        restored = runner.handle_script("run " + printed)
        assert restored.status == "ok", restored.error_message
        assert restored.value == expected


def test_single_quotes_disable_interpolation_while_sharing_escapes():
    with ScriptRunner() as runner:
        result = runner.handle_script(r"""
            name: 'Ada'
            #['\n{{name}}\n', "\n{{name}}\n"]
        """)
        assert result.status == "ok", result.error_message
        assert result.value == ["\n{{name}}\n", "\nAda\n"]


@pytest.mark.parametrize("string_type", [str, IString])
@pytest.mark.parametrize("text", [
    "\nHello.\n", "   first\n      second\n", "\n\n", "  ",
    "quote'\"\\\t\r", "\\n",
])
def test_printing_string_data_preserves_whitespace_and_type(string_type, text):
    value = string_type(text)
    with ScriptRunner() as runner:
        result = runner.handle_script(format_source(value))
        assert result.status == "ok", result.error_message
        assert result.value == value
        assert type(result.value) is string_type


def test_file_loaded_strings_preserve_layout_and_escapes_on_cached_reads(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("SLIP_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "strings.slip"
    source.write_text('''#[
    '\\n  padded\\n',
    "
        Hello.
        Welcome.
    "
]''')
    with ScriptRunner() as runner:
        runner.source_dir = tmp_path
        first = runner.handle_script("run file://strings.slip")
        second = runner.handle_script("run file://strings.slip")
        for result in (first, second):
            assert result.status == "ok", result.error_message
            assert result.value == ["\n  padded\n", "Hello.\nWelcome."]
