import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from copilot_agent.knowledge_health import check_knowledge_health
from copilot_agent.discovery_contracts import DiscoveryError


class KnowledgeHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'knowledge'
        self.context = {'knowledge_directory': self.root}

    def test_real_write_read_hash_schema_cleanup_and_sanitized_result(self):
        result = check_knowledge_health(self.context)
        self.assertEqual('healthy', result['status'])
        self.assertTrue(result['writable'])
        self.assertTrue(result['schema_compatible'])
        self.assertEqual([], list(self.root.glob('.knowledge-health-*')))
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertTrue((self.root / 'discovery-v1' / 'ledger.sqlite3').is_file())

    def test_read_only_and_failed_write(self):
        self.root.mkdir()
        with patch.object(Path, 'open', side_effect=PermissionError('private path')):
            result = check_knowledge_health(self.context)
        self.assertEqual('read_only', result['status'])
        self.assertFalse(result['writable'])
        self.assertNotIn('private path', json.dumps(result))

    def test_unavailable_root(self):
        with patch('copilot_agent.knowledge_health.knowledge_directory', side_effect=FileNotFoundError()):
            result = check_knowledge_health(self.context)
        self.assertEqual('mapped_shared_unavailable', result['status'])

    def test_corrupt_readback(self):
        with patch.object(Path, 'read_bytes', return_value=b'corrupted'):
            result = check_knowledge_health(self.context)
        self.assertEqual('integrity_failure', result['status'])
        self.assertFalse(result['writable'])

    def test_incompatible_version(self):
        with patch('copilot_agent.knowledge_health.Store', side_effect=DiscoveryError('store_version')):
            result = check_knowledge_health(self.context)
        self.assertEqual('incompatible_store_version', result['status'])
        self.assertFalse(result['writable'])

    def test_cleanup_failure_is_not_healthy(self):
        with patch.object(Path, 'unlink', side_effect=PermissionError()):
            result = check_knowledge_health(self.context)
        self.assertEqual('probe_cleanup_failed', result['diagnostic'])
        self.assertFalse(result['probe_cleanup'])
        self.assertFalse(result['writable'])

if __name__ == '__main__':
    unittest.main()
