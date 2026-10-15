"""Authorized filesystem coordinates remain useful without retaining credentials."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copilot_agent.policy import PathPolicy
from copilot_agent.rea import _execute_python, _public_diagnostic, _restore_source_paths, _save


class REAFullPathTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rea_coordinates_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_diagnostics_preserve_exact_drive_unc_and_posix_paths_without_credentials(self):
        diagnostic = {'repository': r'S:\Research\REA',
                      'node': r'\\server\share\Portable Node\node.exe',
                      'reason': 'Cannot read C:\\Company\\REA\\package.json',
                      'fallback': '/opt/company/rea',
                      'authorization': 'Bearer fixture-secret',
                      'url': 'https://user:pass@example.com/page?token=fixture-secret#hidden'}
        actual = _public_diagnostic(diagnostic)
        for key in ('repository', 'node', 'reason', 'fallback'):
            self.assertEqual(diagnostic[key], actual[key])
        self.assertNotIn('fixture-secret', json.dumps(actual))
        self.assertEqual('https://example.com/page', actual['url'])

    def test_saved_evidence_has_resolvable_full_path_and_original_input_identity(self):
        source = r'\\server\share\Company\investigation.har'
        result = _save({'execution_id': 'fixture', 'status': 'completed',
                        'target': source, 'target_type': 'har', 'backend': 'python_native',
                        'provenance': {'input': {'path': source, 'sha256': 'input-hash'}},
                        'locations': [source + '#entry:0'], 'cookie': 'fixture-secret'},
                       {'session_dir': str(self.root / 'session')})
        evidence = Path(result['evidence_path'])
        self.assertTrue(evidence.is_absolute())
        self.assertTrue(evidence.is_file())
        self.assertEqual(hashlib.sha256(evidence.read_bytes()).hexdigest(), result['evidence_sha256'])
        retained = json.loads(evidence.read_text(encoding='utf-8'))
        self.assertEqual(source, result['target'])
        self.assertEqual(source, retained['provenance']['input']['path'])
        self.assertEqual(source + '#entry:0', retained['locations'][0])
        self.assertEqual('input-hash', retained['provenance']['input']['sha256'])
        self.assertNotIn('fixture-secret', evidence.read_text(encoding='utf-8'))

    def test_source_coordinates_restored_in_locations_and_diagnostic_prose(self):
        staged = r'C:\Temp\rea\artifact.js'
        original = r'\\server\share\Company\artifact.js'
        actual = _restore_source_paths({'location': staged + '#line:4',
                                       'reason': 'Inspect ' + staged + ' for details'},
                                      {'target': staged, 'original': original})
        self.assertEqual(original + '#line:4', actual['location'])
        self.assertEqual('Inspect ' + original + ' for details', actual['reason'])

    async def test_python_output_restores_source_paths_before_snapshot_cleanup(self):
        source = self.root / 'app.js'
        source.write_text('export const answer = 42;', encoding='utf-8')
        original_bytes = source.read_bytes()
        context = {'config': {'rea_backend': 'python_native', 'rea_timeout_seconds': 20},
                   'session_dir': str(self.root / 'session')}
        snapshots = []

        async def analyze(command, **kwargs):
            snapshot = command[8]
            snapshots.append(snapshot)
            self.assertNotEqual(str(source), snapshot)
            return {'stdout': json.dumps({'status': 'partial',
                     'findings': {'file': {'path': snapshot}},
                     'locations': [snapshot + '#line:1'],
                     'limitations': ['Conservative static analysis.']}).encode(),
                    'stderr': b'', 'returncode': 0}

        with patch('copilot_agent.rea._run', side_effect=analyze):
            result = await _execute_python('rea.analyze_artifact',
                {'path': str(source), 'kind': 'javascript'}, context, PathPolicy([self.root]))
        self.assertEqual('partial', result['status'], result)
        self.assertEqual(str(source), result['findings']['file']['path'])
        self.assertEqual(str(source) + '#line:1', result['locations'][0])
        self.assertEqual(str(source), result['provenance']['input']['path'])
        self.assertEqual(original_bytes, source.read_bytes())
        self.assertFalse(Path(snapshots[0]).exists())


if __name__ == '__main__':
    unittest.main()
