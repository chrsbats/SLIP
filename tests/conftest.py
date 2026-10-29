import pytest

from slip import ScriptRunner


@pytest.fixture
def runner():
    with ScriptRunner() as value:
        yield value
