import json
import unittest
from copilot_agent.discovery_store import Store
from copilot_agent.knowledge_health import check_knowledge_health
from copilot_agent.knowledge_notes import execute_note
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.site_knowledge import _hash
from copilot_agent.tools import ToolRegistry
from tests.test_protocol_state import make_fixture
from tests.test_orchestrator import MockBrowser, final_response, tool_response


class KnowledgeRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_compatible_newer_store_is_readable_and_zero_version_migrates(self):
        _, _, _, app = self.fixture()
        store = Store(app.base_context, persistent=True)
        store.save_site_knowledge('a' * 64, 0, {'revision': 1, 'ordinary': 'data'})
        store.db.execute('PRAGMA user_version=99')
        store.close()
        store = Store(app.base_context, persistent=True, readonly=True)
        self.assertEqual('data', store.site_knowledge('a' * 64)['ordinary'])
        store.close()
        # A known older version migrates without dropping retained content.
        import sqlite3
        from copilot_agent.discovery_store import directory
        with sqlite3.connect(directory(app.base_context) / 'ledger.sqlite3') as db:
            db.execute('PRAGMA user_version=0')
        store = Store(app.base_context, persistent=True)
        self.assertEqual(1, store.db.execute('PRAGMA user_version').fetchone()[0])
        self.assertEqual('data', store.site_knowledge('a' * 64)['ordinary'])
        store.close()

    def fixture(self, responders=()):
        root, config, state, _ = make_fixture('knowledge-repair-')
        config.knowledge_directory = root / 'Discoveries'
        config._local_navigation_confirmed = True
        config._knowledge_capability = check_knowledge_health({'config': config})
        app = Orchestrator(config, MockBrowser(responders), ToolRegistry(), state,
                           approval_decider=lambda *args: self.fail('Unexpected repeated approval'), display=lambda text: None)
        return root, config, state, app

    async def test_single_confirmation_saves_file_and_reads_verified_knowledge(self):
        root, config, state, app = self.fixture([final_response,
            lambda message: tool_response(message, 'save-note', 'knowledge.note',
                {'title': 'Reusable local discovery', 'content': 'Refresh the directory listing before opening an item.'}),
            final_response])
        await app.initialize()
        await app.turn('Save the verified discovery')
        receipt = state.data['calls']['save-note']['result']['result']
        self.assertTrue(receipt['verified'])
        self.assertTrue(receipt['indexed'])
        self.assertTrue((config.knowledge_directory / 'notes' / (receipt['note_id'] + '.json')).is_file())
        result = execute_note('knowledge.lookup', {'note_id': receipt['note_id']}, app.base_context)
        self.assertIn('Refresh the directory', result['knowledge']['content'])
        message = app.browser.sent[0]['message']
        self.assertEqual('healthy', message['highest_priority_operational_finding']['status'])
        self.assertNotIn(str(root), message['local_capability'])
        self.assertEqual('Local knowledge storage capability', app.findings.data['findings'][0]['key'])
        catalogue = json.loads(app.prompts.catalogue.read_text())
        recovery = [t for t in catalogue['tools'] if t['name'] in {'operation.reconcile', 'operation.quarantine'}]
        self.assertTrue(all(t['availability']['available'] for t in recovery))

    async def test_corrupt_uncertain_save_quarantines_and_next_note_succeeds(self):
        _, _, state, app = self.fixture()
        namespace = 'a' * 64
        store = Store(app.base_context, persistent=True)
        store.save_site_knowledge(namespace, 0, {'revision': 1})
        store.db.execute('UPDATE site_knowledge SET payload=? WHERE namespace=?', ('corrupted', namespace))
        store.close()
        call = {'call_id': 'uncertain-save', 'name': 'site_knowledge.save', 'version': '1.0', 'arguments': {}}
        state.begin_call(call, reconciliation_baseline={'kind': 'knowledge_save', 'namespace_id': namespace})
        state.finish_call(call['call_id'], {'ok': False, 'error': {'code': 'timeout'}})
        outcomes = app._recover_uncertain_knowledge()
        self.assertEqual('abandoned_unverifiable', outcomes[call['call_id']]['status'])
        self.assertFalse(outcomes[call['call_id']]['completion_credited'])
        store = Store(app.base_context, persistent=True)
        self.assertIsNone(store.site_knowledge(namespace))
        self.assertEqual(1, store.db.execute('SELECT COUNT(*) FROM site_knowledge_quarantine').fetchone()[0])
        store.close()
        receipt = execute_note('knowledge.note', {'title': 'Recovered discovery', 'content': 'Verified alternate knowledge.'},
                               dict(app.base_context, approved=True))
        self.assertTrue(receipt['verified'])
        self.assertEqual({}, app._recover_uncertain_knowledge())

    async def test_committed_save_reconciles_without_live_browser(self):
        _, _, state, app = self.fixture()
        namespace = 'b' * 64
        knowledge = {'ordinary': [{'label': 'Any ordinary knowledge'}]}
        value = {'namespace_id': namespace, 'revision': 1, 'knowledge': knowledge,
                 'payload_sha256': _hash(knowledge), 'consent': {'approval_hash': 'c' * 64, 'review_sha256': 'd' * 64},
                 'provenance': {'request': 'e' * 64}}
        store = Store(app.base_context, persistent=True)
        store.save_site_knowledge(namespace, 0, value)
        store.close()
        call = {'call_id': 'committed', 'name': 'site_knowledge.save', 'version': '1.0', 'arguments': {}}
        baseline = {'kind': 'knowledge_save', 'namespace_id': namespace, 'before_sha256': None,
                    'revision': 1, 'payload_sha256': value['payload_sha256'], 'approval_sha256': 'c' * 64,
                    'review_sha256': 'd' * 64, 'request_sha256': 'e' * 64}
        state.begin_call(call, reconciliation_baseline=baseline)
        state.finish_call('committed', {'ok': False, 'error': {'code': 'timeout'}})
        self.assertEqual('completed', app._recover_uncertain_knowledge()['committed']['status'])

    async def test_note_fallback_survives_newer_ledger_and_detects_corruption(self):
        _, config, _, app = self.fixture()
        store = Store(app.base_context, persistent=True)
        store.db.execute('PRAGMA user_version=99')
        store.close()
        receipt = execute_note('knowledge.note', {'title': 'Fallback', 'content': 'Retained verified observation.'},
                               dict(app.base_context, approved=True))
        self.assertTrue(receipt['verified'])
        self.assertFalse(receipt['indexed'])
        self.assertEqual('verified', execute_note('knowledge.lookup', {'note_id': receipt['note_id']}, app.base_context)['status'])
        (config.knowledge_directory / 'notes' / (receipt['note_id'] + '.json')).write_text('corrupt')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            execute_note('knowledge.lookup', {'note_id': receipt['note_id']}, app.base_context)
