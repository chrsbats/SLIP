# test_parser.py
import unittest
import json
from koine import Parser
import yaml

class TestSlipParser(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        grammar_path='slip_grammar.yaml'
        """Load the grammar and instantiate the parser once for all tests."""
        with open(grammar_path, 'r') as f:
            grammar = yaml.safe_load(f)
        cls.parser = Parser(grammar)

    def _assert_parses_to(self, source, expected_ast):
        """Helper method to parse and compare ASTs."""
        result = self.parser.parse(source.strip())
        self.assertEqual(result['status'], 'success', f"Parsing failed for: {source}\nMessage: {result.get('message')}")
        
        # The final AST is under the 'ast' key in the result
        actual_ast = result.get('ast')

        self.assertEqual(actual_ast, expected_ast, 
                         f"\n\n--- For Input ---\n{source}"
                         f"\n\n--- Expected AST ---\n{json.dumps(expected_ast, indent=2)}"
                         f"\n\n--- Got AST ---\n{json.dumps(actual_ast, indent=2)}")

    def test_simple_assignment(self):
        source = "x: 10"
        expected = {
            'tag': 'code',
            'expressions': [
                [ # This is the assignment_expression (a flat list)
                    {'tag': 'set-path', 'children': [{'tag': 'segment', 'text': 'x'}]}, # 'x' is now a structured path
                    {'tag': 'number', 'text': '10', 'value': 10}
                ]
            ]
        }
        self._assert_parses_to(source, expected)

    def test_prefix_call(self):
        source = "add 1 2"
        expected = {
            'tag': 'code',
            'expressions': [{
                'tag': 'call',
                'function': {'tag': 'path', 'children': [{'tag': 'segment', 'text': 'add'}]}, # 'add' is a structured path
                'arguments': [
                    {'tag': 'number', 'text': '1', 'value': 1},
                    {'tag': 'number', 'text': '2', 'value': 2}
                ]
            }]
        }
        self._assert_parses_to(source, expected)

    def test_infix_chain_with_pipe(self):
        source = "data |map [x * 2]"
        expected = {
            'tag': 'code',
            'expressions': [
                [ # This is the call_chain (a flat list)
                    {'tag': 'path', 'children': [{'tag': 'segment', 'text': 'data'}]}, # 'data' is a structured path
                    {'tag': 'piped-path', 'text': '|map'}, # |map is now a piped-path leaf
                    {
                        'tag': 'code',
                        'expressions': [
                            [ # Inner call_chain (flat list)
                                {'tag': 'path', 'children': [{'tag': 'segment', 'text': 'x'}]}, # 'x' structured path
                                {'tag': 'piped-path', 'text': '*'}, # * is now a piped-path leaf
                                {'tag': 'number', 'text': '2', 'value': 2}
                            ]
                        ]
                    }
                ]
            ]
        }
        self._assert_parses_to(source, expected)

    def test_assignment_with_infix_chain(self):
        source = "result: 10 + 20"
        expected = {
            'tag': 'code',
            'expressions': [
                [ # The assignment_expression (flat list)
                    {'tag': 'set-path', 'children': [{'tag': 'segment', 'text': 'result'}]}, # 'result' structured path
                    {'tag': 'number', 'text': '10', 'value': 10},
                    {'tag': 'piped-path', 'text': '+'}, # + is now a piped-path leaf
                    {'tag': 'number', 'text': '20', 'value': 20}
                ]
            ]
        }
        self._assert_parses_to(source, expected)

    def test_destructuring_assignment(self):
        source = "[x, y]: #[10, 20]"
        expected = {
            'tag': 'code',
            'expressions': [
                [ # The assignment_expression (flat list)
                    {
                        'tag': 'multi-set',
                        'targets': [
                            {'tag': 'set-path', 'children': [{'tag': 'segment', 'text': 'x'}]},
                            {'tag': 'set-path', 'children': [{'tag': 'segment', 'text': 'y'}]}
                        ]
                    },
                    {
                        'tag': 'list',
                        'items': [
                            {'tag': 'number', 'text': '10', 'value': 10},
                            {'tag': 'number', 'text': '20', 'value': 20}
                        ]
                    }
                ]
            ]
        }
        self._assert_parses_to(source, expected)

    def test_function_definition_as_assignment(self):
        source = "double: fn [x] [x * 2]"
        expected = {
            'tag': 'code',
            'expressions': [
                [ # The assignment_expression (flat list)
                    {'tag': 'set-path', 'children': [{'tag': 'segment', 'text': 'double'}]},
                    {
                        'tag': 'call',
                        'function': {'tag': 'path', 'children': [{'tag': 'segment', 'text': 'fn'}]},
                        'arguments': [
                            {
                                'tag': 'code',
                                'expressions': [
                                    {'tag': 'path', 'children': [{'tag': 'segment', 'text': 'x'}]}
                                ]
                            },
                            {
                                'tag': 'code',
                                'expressions': [
                                    [ # Inner call_chain (flat list)
                                        {'tag': 'path', 'children': [{'tag': 'segment', 'text': 'x'}]},
                                        {'tag': 'piped-path', 'text': '*'},
                                        {'tag': 'number', 'text': '2', 'value': 2}
                                    ]
                                ]
                            }
                        ]
                    }
                ]
            ]
        }
        self._assert_parses_to(source, expected)

    def test_path_with_segment(self):
        source = "user.name: \"John\""
        expected = {
            'tag': 'code',
            'expressions': [
                [
                    {
                        'tag': 'set-path',
                        'children': [
                            {'tag': 'segment', 'text': 'user'},
                            {'tag': 'segment', 'text': 'name'}
                        ]
                    },
                    {'tag': 'string', 'text': 'John'}
                ]
            ]
        }
        self._assert_parses_to(source, expected)

    def test_path_with_index_access(self):
        source = "items[0]: 100"
        expected = {
            'tag': 'code',
            'expressions': [
                [
                    {
                        'tag': 'set-path',
                        'children': [
                            {'tag': 'segment', 'text': 'items'},
                            {
                                'tag': 'index_access',
                                'index_value': {'tag': 'number', 'text': '0', 'value': 0}
                            }
                        ]
                    },
                    {'tag': 'number', 'text': '100', 'value': 100}
                ]
            ]
        }
        self._assert_parses_to(source, expected)

    def test_path_with_nested_access(self):
        source = "users[idx].settings: {theme: 'dark'}"
        expected = {
            'tag': 'code',
            'expressions': [
                [
                    {
                        'tag': 'set-path',
                        'children': [
                            {'tag': 'segment', 'text': 'users'},
                            {
                                'tag': 'index_access',
                                'index_value': {'tag': 'path', 'children': [{'tag': 'segment', 'text': 'idx'}]}
                            },
                            {'tag': 'segment', 'text': 'settings'}
                        ]
                    },
                    {
                        'tag': 'dict',
                        'pairs': [{
                            'tag': 'pair',
                            'key': {'tag': 'path', 'children': [{'tag': 'segment', 'text': 'theme'}]},
                            'value': {'tag': 'string', 'text': 'dark'}
                        }]
                    }
                ]
            ]
        }
        self._assert_parses_to(source, expected)

    def test_comment_is_ignored(self):
        source = "x: 10 // this is a comment"
        expected = {
            'tag': 'code',
            'expressions': [
                [
                    {'tag': 'set-path', 'children': [{'tag': 'segment', 'text': 'x'}]},
                    {'tag': 'number', 'text': '10', 'value': 10}
                ]
            ]
        }
        self._assert_parses_to(source, expected)

    def test_multi_line_expressions(self):
        source = """
        x: 1
        y: "hello"
        """
        expected = {
            'tag': 'code',
            'expressions': [
                [
                    {'tag': 'set-path', 'children': [{'tag': 'segment', 'text': 'x'}]},
                    {'tag': 'number', 'text': '1', 'value': 1}
                ],
                [
                    {'tag': 'set-path', 'children': [{'tag': 'segment', 'text': 'y'}]},
                    {'tag': 'string', 'text': 'hello'}
                ]
            ]
        }
        self._assert_parses_to(source, expected)

    def test_simple_value_expression(self):
        source = "true"
        expected = {
            'tag': 'code',
            'expressions': [
                {'tag': 'path', 'children': [{'tag': 'segment', 'text': 'true'}]}
            ]
        }
        self._assert_parses_to(source, expected)

    def test_empty_program(self):
        source = ""
        expected = {
            'tag': 'code',
            'expressions': []
        }
        self._assert_parses_to(source, expected)


if __name__ == '__main__':
    # This allows running the tests directly from the command line
    unittest.main(argv=['first-arg-is-ignored'], exit=False)