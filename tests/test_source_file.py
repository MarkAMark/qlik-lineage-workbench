import json
import unittest

from backend.source_file import json_locations


def selected_text(text, location):
    lines = text.split('\n')
    start = sum(len(line) + 1 for line in lines[:location['line'] - 1])
    finish = sum(len(line) + 1 for line in lines[:location['endLine'] - 1])
    # Match the browser's UTF-16 column offsets, including non-BMP Unicode.
    first = lines[location['line'] - 1].encode('utf-16-le')[:(location['column'] - 1) * 2].decode('utf-16-le')
    last = lines[location['endLine'] - 1].encode('utf-16-le')[:(location['endColumn'] - 1) * 2].decode('utf-16-le')
    return text[start + len(first):finish + len(last)]


class SourceLocationTests(unittest.TestCase):
    def test_pretty_json_locates_repeated_expressions_by_path(self):
        value = {'qChildren': [{'qDef': 'SUM(数量)'}, {'qDef': 'SUM(数量)'}]}
        text = json.dumps(value, ensure_ascii=False, indent=2)
        locations = json_locations(text, {'/qChildren/0/qDef', '/qChildren/1/qDef', '/qChildren/1'})
        first, second = locations['/qChildren/0/qDef'], locations['/qChildren/1/qDef']
        self.assertLess(first['line'], second['line'])
        self.assertEqual(json.loads(selected_text(text, second)), 'SUM(数量)')
        self.assertEqual(json.loads(selected_text(text, locations['/qChildren/1'])), value['qChildren'][1])

    def test_pointer_escapes_empty_key_and_array_indices(self):
        value = {'a/b': {'x~y': [{'': True}, None, 4]}, '': 'empty key'}
        text = json.dumps(value, indent=2)
        pointers = {'', '/', '/a~1b/x~0y/0/', '/a~1b/x~0y/1', '/a~1b/x~0y/2'}
        locations = json_locations(text, pointers)
        expected = {'': value, '/': 'empty key', '/a~1b/x~0y/0/': True, '/a~1b/x~0y/1': None, '/a~1b/x~0y/2': 4}
        for pointer, result in expected.items():
            self.assertEqual(json.loads(selected_text(text, locations[pointer])), result)

    def test_minified_json_columns_match_browser_utf16_offsets(self):
        text = '{"label":"车辆🚗","target":{"qDef":"SUM(数量)"}}'
        locations = json_locations(text, {'/target', '/target/qDef'})
        target = locations['/target']
        self.assertEqual((target['line'], target['endLine']), (1, 1))
        expected_column = len(text[:text.index('{', 1)].encode('utf-16-le')) // 2 + 1
        self.assertEqual(target['column'], expected_column)
        self.assertEqual(json.loads(selected_text(text, target)), {'qDef': 'SUM(数量)'})

    def test_crlf_and_escaped_braces_do_not_change_real_line_numbers(self):
        text = '{\r\n  "ignored": "quote \\\" { ] \\n",\r\n  "target": [\r\n    "value"\r\n  ]\r\n}'
        location = json_locations(text, {'/target/0'})['/target/0']
        self.assertEqual(location['line'], 4)
        self.assertEqual(json.loads(selected_text(text, location)), 'value')

    def test_unresolved_paths_do_not_choose_a_similar_expression(self):
        text = '{"values":["same", "same"], "nested": {"name": "same"}}'
        self.assertEqual(json_locations(text, {'/missing', '/values/01', '/values/4', '/nested/name/child', 'invalid', '/bad~2key'}), {})


if __name__ == '__main__':
    unittest.main()
