"""Regression tests for startup temporary-storage recovery."""
import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot_agent.temp_storage import (
    _candidate_directories,
    _probe_directory,
    configure_temp_directory,
    select_temp_directory,
)


class TempStorageTests(unittest.TestCase):
    def test_multiple_locations_are_tried_after_enospc(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            environment = {
                'LOCALAPPDATA': str(root / 'local'),
                'TEMP': str(root / 'temp-one'),
                'TMP': str(root / 'temp-two'),
                'SystemRoot': str(root / 'windows'),
            }
            storage = root / 'S' / 'Discoveries knowledge'
            candidates = _candidate_directories(environment, storage_root=storage, home=root / 'home', platform='nt')
            attempted = []

            def probe(path):
                attempted.append(path)
                if path == candidates[0]:
                    raise OSError(errno.ENOSPC, 'No space left on device')
                if path == candidates[1]:
                    path.mkdir(parents=True, exist_ok=True)

            selected = select_temp_directory(
                environment, storage_root=storage, home=root / 'home', platform='nt', probe=probe)

            self.assertEqual(candidates[1], selected)
            self.assertEqual(candidates[:2], attempted)

    def test_temp_candidates_remain_under_s_discoveries_storage(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            storage = root / 'Discoveries knowledge'
            candidates = _candidate_directories(
                {'LOCALAPPDATA': str(root / 'local'),
                 'TEMP': str(root / 'temp'),
                 'TMP': str(root / 'temp')},
                storage_root=storage,
                home=root / 'home', platform='nt')
            self.assertEqual(storage.resolve() / 'runtime' / 'temp', candidates[0])
            self.assertFalse(any(str(path).startswith(str(root / 'local')) for path in candidates))
            self.assertGreaterEqual(len(candidates), 3)

    def test_all_candidate_failures_report_retries_and_chain_last_error(self):
        with tempfile.TemporaryDirectory() as root:
            environment = {'LOCALAPPDATA': str(Path(root) / 'local'),
                           'TEMP': str(Path(root) / 'temp')}
            failure = OSError(errno.ENOSPC, 'No space left on device')
            with self.assertRaisesRegex(OSError, r'location\(s\) tested') as caught:
                select_temp_directory(environment, storage_root=Path(root) / 'S' / 'Discoveries knowledge', home=root, platform='nt',
                                      probe=lambda path: (_ for _ in ()).throw(failure))
            self.assertIs(failure, caught.exception.__cause__)
            self.assertIn('No space left on device', str(caught.exception.__cause__))

    def test_probe_performs_verified_io_and_removes_only_its_probe_file(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            _probe_directory(directory)
            self.assertEqual([], list(directory.iterdir()))

    def test_configured_temp_updates_python_and_child_environment(self):
        with tempfile.TemporaryDirectory() as root:
            environment = {'LOCALAPPDATA': root}
            with patch.object(tempfile, 'tempdir', None):
                selected = configure_temp_directory(Path(root) / 'S' / 'Discoveries knowledge', environment, home=root, platform='nt')
                self.assertEqual(str(selected), environment['TEMP'])
                self.assertEqual(str(selected), environment['TMP'])
                self.assertEqual(str(selected), environment['TMPDIR'])
                self.assertEqual(str(selected), tempfile.gettempdir())


if __name__ == '__main__':
    unittest.main()
