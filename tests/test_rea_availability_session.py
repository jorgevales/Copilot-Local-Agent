"""Fresh-session REA availability agrees across model metadata and dispatch."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from copilot_agent.findings import Findings
from copilot_agent.policy import PathPolicy
from copilot_agent.prompts import PromptBuilder
from copilot_agent.session_mode import configure_session
from copilot_agent.state import SessionState
from copilot_agent.tools import ToolRegistry
from tests.test_protocol_state import make_fixture


REA_TOOLS = ('rea.inspect_page', 'rea.analyze_capture', 'rea.analyze_artifact')


class REAAvailabilitySessionTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        root, config, state, _ = make_fixture('rea-session-availability-')
        config._automation_test_mode = True
        config.max_context_chars = 100000
        config.allowed_domains = ['example.com']
        configure_session(config, True)
        state.approve_domain('example.com')
        return root, config, state, ToolRegistry(config)

    def messages(self, config, state, registry):
        builder = PromptBuilder(config, registry, state, Findings(state.directory))
        initialized = json.loads(builder.build('initialize', 'Read the contract.', 'init-fixture')[0])
        task = json.loads(builder.build('user_turn', 'Investigate https://example.com/', 'task-fixture')[0])
        catalogue = json.loads(builder.catalogue.read_text(encoding='utf-8'))
        return initialized, task, catalogue

    def assert_authoritative(self, initialized, task, catalogue):
        authoritative = initialized['research_routing']['rea']
        self.assertEqual(authoritative, task['research_routing']['rea'])
        definitions = {item['name']: item for item in catalogue['tools']}
        for name in REA_TOOLS:
            self.assertEqual(authoritative, definitions[name]['availability'], name)
        self.assertEqual(authoritative, task['research_routing']['current_request'][0]['rea'])
        return authoritative

    def test_one_authoritative_snapshot_survives_changing_probe_results(self):
        _, config, state, registry = self.fixture()
        calls = []

        def changed_health(_):
            calls.append(1)
            return {'available': len(calls) == 1,
                    'status': 'available' if len(calls) == 1 else 'unavailable',
                    'reason': 'synthetic probe ' + str(len(calls)),
                    'capabilities': list(REA_TOOLS)}

        probe = Mock(side_effect=changed_health)
        with patch('copilot_agent.tools.rea_health', probe), \
             patch('copilot_agent.rea.rea_health', probe), \
             patch('copilot_agent.research_routing.rea_health', probe):
            initialized, task, catalogue = self.messages(config, state, registry)
        health = self.assert_authoritative(initialized, task, catalogue)
        self.assertTrue(health['available'])
        self.assertEqual('rea.inspect_page', task['research_routing']['current_request'][0]['preferred'])

    async def test_fresh_session_discovers_real_package_files_and_routes_to_rea(self):
        root, config, state, registry = self.fixture()
        package = root / 'rea-package'
        package.mkdir()
        (package / 'package.json').write_text(json.dumps({'name': 'rea-agents', 'version': '6.5.0'}))
        dependency = package / 'node_modules' / 'zod' / 'package.json'
        dependency.parent.mkdir(parents=True)
        dependency.write_text('{}')
        for relative in ('scripts/rea.mjs', 'dist/cli-runtime/cli.js',
                         'dist/cli-runtime/cliOutput.js', 'dist/cli-runtime/cliResultOutput.js'):
            path = package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('// Synthetic REA layout; never executed.\n')
        native = package / 'native' / 'windows' / 'build'
        native.mkdir(parents=True)
        addon = native / 'rea-windows-x64.node'
        addon.write_bytes(b'Synthetic artifact identity; never loaded.')
        (native / 'manifest.json').write_text(json.dumps({
            'packageVersion': '6.5.0', 'platform': 'win32', 'architecture': 'x64',
            'artifactSha256': hashlib.sha256(addon.read_bytes()).hexdigest()}))
        config.rea_repository = str(package)
        config.rea_node_executable = sys.executable
        node_version = subprocess.CompletedProcess([], 0, 'v24.13.0\n', '')
        with patch('copilot_agent.rea.subprocess.run', return_value=node_version):
            initialized, task, catalogue = self.messages(config, state, registry)
            context = {'config': config, 'session_state': state, 'session_dir': state.directory,
                       'approved_domains': ['example.com'], 'path_policy': PathPolicy([root])}
            outcome = await registry.execute('research.route', {
                'target': 'https://example.com/', 'target_type': 'website',
                'objective': 'investigate'}, context)
        health = self.assert_authoritative(initialized, task, catalogue)
        self.assertTrue(health['available'], health)
        self.assertEqual(str(package.resolve()), health['repository'])
        self.assertTrue(outcome['ok'], outcome)
        self.assertEqual('rea.inspect_page', outcome['result']['preferred'])
        self.assertEqual(health, outcome['result']['rea'])

    def test_new_session_rechecks_previously_unavailable_installation(self):
        root, config, old_state, registry = self.fixture()
        current = {'available': False, 'status': 'unavailable', 'reason': 'Synthetic missing package'}
        with patch('copilot_agent.tools.rea_health', side_effect=lambda _: dict(current)):
            old_messages = self.messages(config, old_state, registry)
            self.assertFalse(self.assert_authoritative(*old_messages)['available'])
            current.update(available=True, status='available', reason='Synthetic repaired installation')
            fresh_state = SessionState(root / 'fresh-session')
            fresh_state.approve_domain('example.com')
            fresh_messages = self.messages(config, fresh_state, registry)
        self.assertNotEqual(old_state.session_id, fresh_state.session_id)
        self.assertTrue(self.assert_authoritative(*fresh_messages)['available'])
        self.assertEqual('rea.inspect_page',
                         fresh_messages[1]['research_routing']['current_request'][0]['preferred'])


if __name__ == '__main__':
    unittest.main()
