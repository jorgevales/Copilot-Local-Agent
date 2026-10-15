"""Portable Node identity normalization and redirected S: recovery."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from copilot_agent import node_runtime, rea


class NodeRuntimeTests(unittest.TestCase):
    def test_extracted_directory_named_node_selects_its_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'node'
            folder.mkdir()
            self.assertEqual([folder / 'node.exe'], node_runtime.node_path_candidates(folder))

    @unittest.skipUnless(os.name == 'nt', 'Windows S:/UNC path contract')
    def test_quoted_extended_unc_folder_normalizes_to_native_executable(self):
        supplied = r'  "\\?\UNC\server\share\portable node"  '
        expected = Path(r'\\server\share\portable node\node.exe')
        self.assertEqual([expected], node_runtime.node_path_candidates(supplied))
        with self.assertRaisesRegex(ValueError, 'absolute|full'):
            node_runtime.node_path_candidates(r'S:node.exe')

    @unittest.skipUnless(os.name == 'nt', 'Windows S:/UNC path contract')
    def test_redirected_s_path_uses_live_mapping_when_realpath_fails(self):
        with patch.object(node_runtime.os.path, 'realpath', side_effect=OSError('direct S unavailable')), \
             patch('copilot_agent.policy.mapped_s_drive_root', return_value=Path(r'\\server\share')):
            candidates = node_runtime.node_path_candidates(r'S:\tools\portable node')
        self.assertEqual([Path(r'\\server\share\tools\portable node\node.exe'),
                          Path(r'S:\tools\portable node\node.exe')], candidates)

    def test_health_tries_next_node_candidate_after_missing_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / 'node.exe'
            executable.write_bytes(b'fixture executable; subprocess is mocked')
            missing = root / 'missing-alias' / 'node.exe'
            with patch.object(rea, '_node_candidates', return_value=[missing, executable]), \
                 patch.object(rea, '_check_repository', return_value={'version': '6.5.0'}), \
                 patch.object(rea.subprocess, 'run', return_value=SimpleNamespace(
                     returncode=0, stdout='v24.13.0\n', stderr='')):
                health = rea.rea_health({'root': root})
            self.assertTrue(health['available'])
            self.assertEqual(str(executable.resolve()), health['node'])
            attempts = health['diagnostics']['node_candidates']
            self.assertEqual('node_missing', attempts[0]['code'])
            self.assertEqual('ready', attempts[1]['code'])


if __name__ == '__main__':
    unittest.main()
