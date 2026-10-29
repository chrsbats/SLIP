import json

import httpx

from slip import ScriptRunner


def test_resource_get_default_and_full():
    def respond(request):
        return httpx.Response(201, json={'ok': True}, headers={'X-Test': '1'})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script('''
                r: resource `http://example.com/data`
                get r
            ''')
            assert result.status == 'ok', result.error_message
            assert result.value == {'ok': True}
            result = runner.handle_script('''
                r: resource `http://example.com/data#(response-mode: `full`)`
                get r
            ''')
            assert result.status == 'ok', result.error_message
            assert isinstance(result.value, dict)
            assert result.value['status'] == 201
            assert result.value['value'] == {'ok': True}
            assert result.value['meta']['headers']['x-test'] == '1'


def test_put_with_content_type_serialization():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(204)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ScriptRunner(http_client=client) as runner:
            result = runner.handle_script(
                'r: resource `http://example.com/items#('
                'content-type: "application/json")`; '
                'put r #{a: 1, b: 2}',
            )
            assert result.status == 'ok', result.error_message
            request, = requests
            text = request.content.decode()
            assert '"a": 1' in text and '"b": 2' in text
            assert json.loads(text) == {'a': 1, 'b': 2}
            assert request.headers['content-type'] == 'application/json'


def test_import_file_module_and_caching(tmp_path, runner):
    (tmp_path / 'mod.slip').write_text('x: 2\ny: 3\n')
    runner.source_dir = str(tmp_path)
    result = runner.handle_script('''
        m1: import `file://./mod.slip`
        #[m1.x, m1.y]
    ''')
    assert result.status == 'ok', result.error_message
    assert result.value == [2, 3]
    result = runner.handle_script('''
        m1: import `file://./mod.slip`
        m2: import `file://./mod.slip`
        m1.x: 100
        #[m1.x != m2.x, eq m1 m2]
    ''')
    assert result.status == 'ok', result.error_message
    assert result.value == [True, False]
    result = runner.handle_script("m: import 'file://./mod.slip'; m.x")
    assert result.status == 'ok', result.error_message
    assert result.value == 2
