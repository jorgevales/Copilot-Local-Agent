"""Lossless bundle tests with retained local fixtures; no ZIP/network/browser."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from copilot_agent.bundle import MAX_BUNDLE_BYTES, build_bundle, build_startup_attachments, read_bundle_components
from copilot_agent.config import PROJECT_ROOT


class BundleTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('COPILOT_TEST_ROOT', str(PROJECT_ROOT / 'runtime' / 'test-runs')))
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='bundle-', dir=base))
        self.paths = []
        for ordinal in range(1, 9):
            path = self.root / f'{ordinal:02}-guidance.md'
            value = (f'# Original guidance {ordinal}\r\n\r\n'.encode('utf-8') + 'Exact café 日本語 content.\r\n'.encode('utf-8'))
            if ordinal == 1:
                value = b'\xef\xbb\xbf' + value
            if ordinal == 2:
                value += b'```json\n{"literal":"```"}\n```'  # No final newline.
            path.write_bytes(value)
            self.paths.append(path)
        for name, payload in [('response-v1.schema.json', {'type': 'object', 'description': 'literal ``` fence'}),
                              ('tool-catalogue.json', {'schema_version': '1.0', 'tools': []})]:
            path = self.root / name
            path.write_bytes(json.dumps(payload, ensure_ascii=False).encode('utf-8') + b'\r\n')
            self.paths.append(path)
        self.manifest = [{'name': path.name, 'version': '1.0',
                          'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in self.paths]
        self.target = self.root / 'copilot-reference.md'

    def test_all_ten_original_byte_streams_recover_exactly_with_correct_offsets(self):
        record = build_bundle(self.paths, self.manifest, self.target, MAX_BUNDLE_BYTES)
        content = self.target.read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), record['sha256'])
        self.assertEqual(len(content), record['byte_length'])
        recovered = read_bundle_components(self.target, record)
        self.assertEqual({path.name: path.read_bytes() for path in self.paths}, recovered)
        self.assertEqual(10, len(record['component_manifest']))
        for component in record['component_manifest']:
            source = next(path for path in self.paths if path.name == component['name'])
            self.assertEqual(source.read_bytes(), content[component['start_byte']:component['end_byte']])
            self.assertEqual(len(source.read_bytes()), component['byte_length'])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), component['sha256'])

    def test_source_bom_crlf_and_no_final_newline_are_preserved(self):
        record = build_bundle(self.paths, self.manifest, self.target)
        values = read_bundle_components(self.target, record)
        self.assertTrue(values['01-guidance.md'].startswith(b'\xef\xbb\xbf'))
        self.assertIn(b'\r\n', values['01-guidance.md'])
        self.assertFalse(values['02-guidance.md'].endswith(b'\n'))

    def test_missing_or_duplicate_components_and_manifest_are_rejected(self):
        for paths, manifest in ((self.paths[:-1], self.manifest),
                                (self.paths[:-1] + [self.paths[0]], self.manifest),
                                (self.paths, self.manifest[:-1])):
            with self.subTest(count=len(paths)), self.assertRaises(ValueError):
                build_bundle(paths, manifest, self.target)
        self.assertFalse(self.target.exists())

    def test_missing_source_and_post_verification_source_tamper_fail_before_write(self):
        missing = self.paths.copy()
        missing[0] = self.root / 'missing' / self.paths[0].name
        with self.assertRaises(ValueError):
            build_bundle(missing, self.manifest, self.target)
        self.paths[0].write_bytes(self.paths[0].read_bytes() + b'Changed after verification.')
        with self.assertRaises(ValueError):
            build_bundle(self.paths, self.manifest, self.target)
        self.assertFalse(self.target.exists())

    def test_full_bundle_headers_count_towards_limit(self):
        source_size = sum(path.stat().st_size for path in self.paths)
        with self.assertRaises(ValueError):
            build_bundle(self.paths, self.manifest, self.target, max_bytes=source_size)
        self.assertFalse(self.target.exists())
        for limit in (0, True, MAX_BUNDLE_BYTES + 1):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                build_bundle(self.paths, self.manifest, self.target, max_bytes=limit)

    def test_bundle_tamper_and_record_offset_tamper_are_detected(self):
        record = build_bundle(self.paths, self.manifest, self.target)
        wrong = copy.deepcopy(record)
        wrong['component_manifest'][0]['start_byte'] += 1
        with self.assertRaises(ValueError):
            read_bundle_components(self.target, wrong)
        self.target.write_bytes(self.target.read_bytes() + b'Tampered.')
        with self.assertRaises(ValueError):
            read_bundle_components(self.target, record)

    def test_same_bundle_is_not_rewritten_and_changed_bundle_preserves_prior_version(self):
        first = build_bundle(self.paths, self.manifest, self.target)
        previous = self.target.read_bytes()
        repeated = build_bundle(self.paths, self.manifest, self.target)
        self.assertEqual(first, repeated)
        history = self.root / '.history' / self.target.name
        self.assertFalse(history.exists())
        self.paths[3].write_bytes(self.paths[3].read_bytes() + b'New approved version.\n')
        self.manifest[3]['sha256'] = hashlib.sha256(self.paths[3].read_bytes()).hexdigest()
        changed = build_bundle(self.paths, self.manifest, self.target)
        self.assertNotEqual(first['sha256'], changed['sha256'])
        self.assertEqual([previous], [path.read_bytes() for path in history.glob('*.bak')])

    def test_never_replace_source_and_never_write_zip(self):
        for destination in (self.paths[0], self.root / 'bundle.zip'):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                build_bundle(self.paths, self.manifest, destination)

    def test_invalid_utf8_is_rejected_without_lossy_repair(self):
        self.paths[0].write_bytes(b'\xff\xfeinvalid')
        self.manifest[0]['sha256'] = hashlib.sha256(self.paths[0].read_bytes()).hexdigest()
        with self.assertRaises(UnicodeDecodeError):
            build_bundle(self.paths, self.manifest, self.target)
        self.assertFalse(self.target.exists())

    def test_eight_startup_attachments_preserve_six_originals_and_all_ten_exact_bytes(self):
        originals = {path.name: path.read_bytes() for path in self.paths}
        result = build_startup_attachments(self.paths, self.manifest, self.root / 'startup')
        self.assertEqual(8, len(result['paths']))
        self.assertEqual([str(path) for path in self.paths[:6]], result['paths'][:6])
        self.assertEqual(self.manifest, result['component_manifest'])
        self.assertEqual(2, len(result['group_records']))
        recovered = {Path(path).name: Path(path).read_bytes() for path in result['paths'][:6]}
        for group in result['group_records']:
            recovered.update(read_bundle_components(group['path'], group))
            self.assertEqual(2, len(group['component_manifest']))
            text = Path(group['path']).read_text(encoding='utf-8')
            self.assertIn('complete current', text.lower())
            self.assertIn('approval', text)
        self.assertEqual(originals, recovered)
        self.assertEqual(originals, {path.name: path.read_bytes() for path in self.paths})
        for path in result['paths']:
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), result['sha256_by_path'][path])
        self.assertEqual({'07-guidance.md', '08-guidance.md'},
                         set(read_bundle_components(result['group_records'][0]['path'], result['group_records'][0])))
        self.assertEqual({'response-v1.schema.json', 'tool-catalogue.json'},
                         set(read_bundle_components(result['group_records'][1]['path'], result['group_records'][1])))

    def test_startup_order_is_stable_when_source_order_changes(self):
        result = build_startup_attachments(list(reversed(self.paths)), list(reversed(self.manifest)), self.root / 'startup')
        self.assertEqual([str(path) for path in self.paths[:6]], result['paths'][:6])
        self.assertEqual(list(reversed(self.manifest)), result['component_manifest'])

    def test_startup_checks_separate_and_grouped_source_hashes_before_any_write(self):
        for index in (0, 5, 6, 7, 8, 9):
            with self.subTest(index=index):
                original = self.paths[index].read_bytes()
                self.paths[index].write_bytes(original + b'changed')
                destination = self.root / ('startup-' + str(index))
                with self.assertRaises(ValueError):
                    build_startup_attachments(self.paths, self.manifest, destination)
                self.assertFalse(destination.exists())
                self.paths[index].write_bytes(original)

    def test_startup_full_eight_attachment_size_and_completeness_guard(self):
        destination = self.root / 'startup'
        total_original = sum(path.stat().st_size for path in self.paths)
        with self.assertRaises(ValueError):
            build_startup_attachments(self.paths, self.manifest, destination, max_bytes=total_original)
        with self.assertRaises(ValueError):
            build_startup_attachments(self.paths[:-1], self.manifest, destination)
        missing = self.paths.copy()
        missing[5] = self.root / 'missing' / self.paths[5].name
        with self.assertRaises(ValueError):
            build_startup_attachments(missing, self.manifest, destination)
        self.assertFalse(destination.exists())

    def test_startup_generated_group_tamper_is_detected(self):
        result = build_startup_attachments(self.paths, self.manifest, self.root / 'startup')
        group = result['group_records'][1]
        Path(group['path']).write_bytes(Path(group['path']).read_bytes() + b'changed')
        with self.assertRaises(ValueError):
            read_bundle_components(group['path'], group)

    def test_startup_group_changes_retain_prior_version_without_replacing_sources(self):
        directory = self.root / 'startup'
        first = build_startup_attachments(self.paths, self.manifest, directory)
        previous = Path(first['group_records'][0]['path']).read_bytes()
        repeated = build_startup_attachments(self.paths, self.manifest, directory)
        self.assertEqual(first, repeated)
        self.paths[6].write_bytes(self.paths[6].read_bytes() + b'Approved version.\r\n')
        self.manifest[6]['sha256'] = hashlib.sha256(self.paths[6].read_bytes()).hexdigest()
        changed = build_startup_attachments(self.paths, self.manifest, directory)
        self.assertNotEqual(first['group_records'][0]['sha256'], changed['group_records'][0]['sha256'])
        self.assertEqual(first['group_records'][1]['sha256'], changed['group_records'][1]['sha256'])
        history = directory / '.history' / Path(first['group_records'][0]['path']).name
        self.assertEqual([previous], [path.read_bytes() for path in history.glob('*.bak')])
