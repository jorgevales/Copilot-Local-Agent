import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from copilot_agent.rea_python_capture import analyze_capture, safe_url


class PythonCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def har(self, entries):
        path = self.root / 'input.har'
        path.write_text(json.dumps({'log': {'entries': entries}}), encoding='utf-8')
        return path

    def entry(self, suffix='123456', status=200, redirect=''):
        return {'request': {'method': 'POST', 'url': 'https://user:credential-secret@fixture.test/api/customers/' + suffix + '?token=query-secret#fragment-secret',
                            'headers': [{'name': 'Authorization', 'value': 'Bearer authorization-secret'}, {'name': 'Cookie', 'value': 'session=cookie-secret'}],
                            'postData': {'mimeType': 'application/json', 'text': '{"name":"customer-secret","password":"password-secret"}'}},
                'response': {'status': status, 'headers': [{'name': 'Set-Cookie', 'value': 'response-cookie-secret'}],
                             'redirectURL': redirect, 'content': {'mimeType': 'application/json', 'text': 'response-body-secret'}}, 'time': 12.5}

    def test_har_useful_structure_and_redaction(self):
        result = analyze_capture(self.har([self.entry(), self.entry('987654'), self.entry('alice-secret', 302, '/api/status?secret=redirect-secret')]), 'har')
        self.assertEqual('completed', result['status'])
        facts = result['findings']
        self.assertEqual(3, facts['analyzed_request_count'])
        self.assertEqual({'POST': 3}, facts['methods'])
        self.assertEqual({'2xx': 2, '3xx': 1}, facts['status_classes'])
        self.assertEqual(3, facts['repeated_request_shapes'][0]['count'])
        self.assertEqual(9, facts['redaction']['sensitive_header_fields_omitted'])
        self.assertEqual(3, facts['redaction']['payloads_omitted'])
        self.assertEqual(3, facts['redaction']['queries_omitted'])
        self.assertEqual(1, len(facts['redirect_chains']))
        self.assertEqual(3, len(facts['api_candidates']))
        serialized = json.dumps(result)
        for value in ('123456', '987654', 'alice-secret', 'query-secret', 'fragment-secret', 'authorization-secret', 'cookie-secret', 'customer-secret', 'password-secret', 'response-body-secret', 'redirect-secret', 'credential-secret'):
            self.assertNotIn(value, serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(['log.entries[0]', 'log.entries[1]', 'log.entries[2]'], result['locations'])

    def test_har_truncation_malformed_entries_and_budget(self):
        path = self.har([self.entry()] * 2001)
        calls = []
        result = analyze_capture(path, 'har', lambda: calls.append(True))
        self.assertEqual('partial', result['status'])
        self.assertEqual(2000, result['findings']['analyzed_request_count'])
        self.assertGreaterEqual(len(calls), 2000)
        self.assertEqual('partial', analyze_capture(self.har([None]), 'har')['status'])
        def exhausted():
            raise TimeoutError('Budget exhausted')
        with self.assertRaises(TimeoutError):
            analyze_capture(path, 'har', exhausted)

    def test_har_rejects_missing_shape_or_oversized_input(self):
        path = self.root / 'invalid.har'
        path.write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'log.entries'):
            analyze_capture(path, 'har')
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            analyze_capture(path, 'zip')

    def test_malformed_metadata_types_are_safe_partial_not_parser_crashes(self):
        entry = self.entry()
        entry['request']['headers'] = {'Authorization': 'malformed-secret'}
        entry['request']['postData'] = ['malformed-secret']
        entry['response']['content'] = 'malformed-secret'
        entry['response']['redirectURL'] = 'http://['
        entry['response']['status'] = 302
        result = analyze_capture(self.har([entry, {'request': [], 'response': {}}]), 'har')
        self.assertEqual('partial', result['status'])
        self.assertEqual(1, result['findings']['analyzed_request_count'])
        self.assertNotIn('malformed-secret', json.dumps(result))
        self.assertTrue(any('Malformed' in gap for gap in result['unknowns']))

    def test_url_templates_remove_all_unknown_path_segments_and_query(self):
        self.assertEqual('https://fixture.test/api/users/:segment/:segment', safe_url('https://someone:secret@fixture.test/api/users/Alice/8e3dc756-a397-44db-b4d5-84dc58c6eb44?key=secret#fragment'))
        self.assertIsNone(safe_url('file:///private/path'))
        self.assertIsNone(safe_url('https://fixture.test:invalid/'))
        self.assertIsNone(safe_url('https://bad%40host/'))

    def saz(self, members):
        path = self.root / 'input.saz'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in members:
                archive.writestr(name, data)
        return path

    def pair(self):
        return [('raw/1_c.txt', b'POST https://fixture.test/api/customer/123?token=query-secret HTTP/1.1\r\nAuthorization: Bearer authorization-secret\r\nContent-Type: application/json\r\n\r\n{"name":"customer-secret"}'),
                ('raw/1_s.txt', b'HTTP/1.1 302 Found\r\nContent-Type: application/json\r\nSet-Cookie: session=cookie-secret\r\nLocation: /api/status?key=redirect-secret\r\n\r\n{"name":"response-secret"}')]

    def test_saz_passive_analysis_and_redaction(self):
        result = analyze_capture(self.saz(self.pair()), 'saz')
        self.assertEqual(1, result['findings']['entry_count'])
        self.assertEqual('POST', result['findings']['api_candidates'][0]['method'])
        self.assertEqual(['raw/1_c.txt'], result['locations'])
        serialized = json.dumps(result)
        for secret in ('query-secret', 'authorization-secret', 'customer-secret', 'cookie-secret', 'redirect-secret', 'response-secret'):
            self.assertNotIn(secret, serialized)

    def test_saz_rejects_traversal_collisions_and_incomplete_pairs(self):
        for member in ('../escape', '/absolute', 'raw\\1_c.txt', 'raw/./1_c.txt', 'C:/escape'):
            with self.subTest(member=member), self.assertRaisesRegex(ValueError, 'unsafe'):
                analyze_capture(self.saz(self.pair() + [(member, b'bad')]), 'saz')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            analyze_capture(self.saz(self.pair() + [('RAW/1_C.TXT', b'bad')]), 'saz')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            analyze_capture(self.saz(self.pair()[:1]), 'saz')

    def test_saz_rejects_malformed_http_and_oversized_members(self):
        with self.assertRaisesRegex(ValueError, 'malformed'):
            analyze_capture(self.saz([('raw/1_c.txt', b'bad'), self.pair()[1]]), 'saz')
        with self.assertRaisesRegex(ValueError, 'size limit'):
            analyze_capture(self.saz(self.pair() + [('extra', b'x' * (4 * 1024 * 1024 + 1))]), 'saz')

    def test_saz_rejects_encrypted_members_and_symlinks(self):
        path = self.saz(self.pair())
        data = bytearray(path.read_bytes())
        # Encryption flags in both ZIP headers, without a real secret/password.
        data[6] |= 1
        central = data.index(b'PK\x01\x02')
        data[central + 8] |= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'encrypted'):
            analyze_capture(path, 'saz')
        path = self.root / 'symlink.saz'
        with zipfile.ZipFile(path, 'w') as archive:
            member = zipfile.ZipInfo('link')
            member.external_attr = 0o120777 << 16
            archive.writestr(member, 'elsewhere')
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            analyze_capture(path, 'saz')

    def test_saz_relative_url_needs_unambiguous_host(self):
        relative = b'GET /api/status?key=secret HTTP/1.1\r\nHost: fixture.test\r\n\r\n'
        result = analyze_capture(self.saz([('raw/1_c.txt', relative), self.pair()[1]]), 'saz')
        self.assertIn('http://fixture.test/api/status', result['findings']['route_templates'])
        with self.assertRaisesRegex(ValueError, 'Host'):
            analyze_capture(self.saz([('raw/1_c.txt', relative.replace(b'Host: fixture.test\r\n', b'')), self.pair()[1]]), 'saz')


if __name__ == '__main__':
    unittest.main()
