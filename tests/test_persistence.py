"""Persistence on Windows shares with legacy path-length limits."""
import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from copilot_agent.persistence import write_preserving

class PersistencePathTests(unittest.TestCase):
    def test_long_unc_approval_preview_uses_extended_io_paths(self):
        if os.name != 'nt':
            self.skipTest('Windows UNC semantics')
        path = Path('\\\\server\\share\\' + ('folder-name\\' * 15) + 'Discoveries knowledge\\runtime\\sessions\\' + 'a'*32 + '\\approvals\\' + 'b'*64 + '.json')
        opened = []
        replaced = []
        def legacy_open(target, *args, **kwargs):
            if not str(target).startswith('\\\\?\\UNC\\'):
                raise FileNotFoundError(errno.ENOENT, 'No such file or directory', str(target))
            opened.append(str(target))
            return tempfile.TemporaryFile(mode='w+', encoding='utf-8')
        with patch.object(Path, 'mkdir'), patch.object(Path, 'exists', return_value=False), patch.object(Path, 'open', legacy_open), patch('copilot_agent.persistence.os.replace', side_effect=lambda src, dst: replaced.append((str(src), str(dst)))):
            write_preserving(path, '{"approved": false}')
        self.assertEqual(1, len(opened))
        self.assertEqual(1, len(replaced))
        self.assertTrue(all(value.startswith('\\\\?\\UNC\\') for value in replaced[0]))


    def test_long_windows_write_retains_previous_version_and_atomic_destination(self):
        if os.name != 'nt':
            self.skipTest('Windows long path semantics')
        from copilot_agent.config import PROJECT_ROOT
        import uuid
        root = PROJECT_ROOT / 'runtime' / 'test-runs' / ('long-write-' + uuid.uuid4().hex)
        path = root / ('nested-' + 'a'*65) / ('nested-' + 'b'*65) / ('c'*64 + '.json')
        write_preserving(path, 'before')
        write_preserving(path, 'after')
        extended = Path('\\\\?\\' + str(path.absolute()))
        self.assertEqual('after', extended.read_text(encoding='utf-8'))
        backups = list((extended.parent / '.history' / extended.name).glob('*.bak'))
        self.assertEqual(1, len(backups))
        self.assertEqual('before', backups[0].read_text(encoding='utf-8'))
        self.assertEqual([], list(extended.parent.glob('*.pending')))
