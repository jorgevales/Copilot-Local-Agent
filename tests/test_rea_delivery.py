import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from bootstrap import rea_delivery as delivery


class PortableDeliveryTests(unittest.TestCase):
    def bundle(self, path, names=None):
        files = names or {'package.json': b'{"name":"rea-agents","version":"6.5.0"}'}
        manifest = {'format': 1, 'name': 'rea-agents', 'version': '6.5.0', 'files': {
            name: {'size': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
            for name, value in files.items()}}
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(delivery.MANIFEST, json.dumps(manifest))
            for name, value in files.items():
                archive.writestr('runtime/' + name, value)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_scratch_uses_verified_write_and_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'file'
            bad.write_text('not a directory')
            with patch.object(delivery, 'staging_candidates', return_value=[bad, Path(tmp) / 'good']):
                selected, failures = delivery.create_staging(tmp, {})
            self.assertEqual(selected.parent.name, 'good')
            self.assertEqual(len(failures), 1)
            self.assertEqual(list(selected.iterdir()), [])

    def test_archive_requires_separately_supplied_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'rea.zip'
            self.bundle(archive)
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                delivery.extract_runtime_archive(archive, Path(tmp) / 'out', expected_sha256='0' * 64)

    def test_verified_members_extract_then_upstream_validation_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, out = Path(tmp) / 'rea.zip', Path(tmp) / 'out'
            digest = self.bundle(archive)
            with patch.object(delivery, 'validate_delivery') as check:
                self.assertEqual(delivery.extract_runtime_archive(archive, out, expected_sha256=digest), out)
            check.assert_called_once_with(out)
            self.assertEqual(json.loads((out / 'package.json').read_text())['version'], '6.5.0')

    def test_parent_traversal_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, out = Path(tmp) / 'rea.zip', Path(tmp) / 'out'
            digest = self.bundle(archive, {'../escape.txt': b'unsafe'})
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                delivery.extract_runtime_archive(archive, out, expected_sha256=digest)
            self.assertFalse(out.exists())

    def test_windows_device_and_backslash_paths_rejected(self):
        for name in ('NUL.txt', 'a/COM1', 'a\\b', 'C:/a', 'a/../b', 'a. ', 'a//b', 'a/./b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                delivery._relative(name)

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, out = Path(tmp) / 'rea.zip', Path(tmp) / 'out'
            digest = self.bundle(archive)
            out.mkdir()
            (out / 'keep').write_text('keep')
            with self.assertRaisesRegex(ValueError, 'empty'):
                delivery.extract_runtime_archive(archive, out, expected_sha256=digest)
            self.assertEqual((out / 'keep').read_text(), 'keep')

    def test_export_output_cannot_be_included_in_source_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'outside'):
                delivery.export_runtime(tmp, Path(tmp) / 'own.zip')

    def test_export_only_published_upstream_files_and_filters_private_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, archive = Path(tmp) / 'source', Path(tmp) / 'transfer.zip'
            root.mkdir()
            paths = ('package.json', 'package-lock.json', 'dist/cli.js', 'dist/.env.production',
                     'dist/config.local.json', 'node_modules/zod/index.js', 'node_modules/zod/.npmrc',
                     'node_modules/zod/secret.pem', 'node_modules/zod/private.key', 'node_modules/zod/cert.pfx',
                     '.env', '.npmrc', 'notes/customer.txt', 'src/developer.ts', 'tests/private.json')
            for name in paths:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}')
            with patch.object(delivery, 'validate_delivery', return_value={'files': ['dist']}):
                delivery.export_runtime(root, archive)
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(set(bundle.namelist()), {delivery.MANIFEST, 'runtime/package.json',
                    'runtime/package-lock.json', 'runtime/dist/cli.js', 'runtime/node_modules/zod/index.js'})

    def test_unsafe_publish_declarations_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            root.mkdir()
            for entry in ('../notes', '/private', 'C:/private', '**', 'dist/./runtime'):
                with self.subTest(entry=entry), patch.object(delivery, 'validate_delivery', return_value={'files': [entry]}):
                    with self.assertRaises(ValueError):
                        delivery.export_runtime(root, Path(tmp) / 'transfer.zip')

    def test_manifest_member_digest_checked_before_runtime_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, out = Path(tmp) / 'rea.zip', Path(tmp) / 'out'
            manifest = {'format': 1, 'name': 'rea-agents', 'version': '6.5.0', 'files': {
                'package.json': {'size': 2, 'sha256': '0' * 64}}}
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr(delivery.MANIFEST, json.dumps(manifest))
                bundle.writestr('runtime/package.json', '{}')
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.object(delivery, 'validate_delivery') as check:
                with self.assertRaisesRegex(ValueError, 'integrity'):
                    delivery.extract_runtime_archive(archive, out, expected_sha256=digest)
            check.assert_not_called()

    def test_rejected_scratch_parent_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / 'first', Path(tmp) / 'second'
            with patch.object(delivery, 'staging_candidates', return_value=[first, second]):
                selected, failures = delivery.create_staging(tmp, {}, excluded=(first,))
            self.assertEqual(selected.parent, second)
            self.assertEqual(failures, [])

    def test_explicit_setup_scratch_is_prioritized(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = delivery.staging_candidates(tmp, {'COPILOT_SETUP_TEMP': tmp})
            self.assertEqual(result[0], Path(tmp) / 'Copilot Local Agent' / 'rea-setup')

    def test_archive_member_set_must_exactly_match_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, out = Path(tmp) / 'rea.zip', Path(tmp) / 'out'
            self.bundle(archive)
            with zipfile.ZipFile(archive, 'a') as bundle:
                bundle.writestr('runtime/extra.js', 'unlisted')
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, 'membership'):
                delivery.extract_runtime_archive(archive, out, expected_sha256=digest)


if __name__ == '__main__':
    unittest.main()
