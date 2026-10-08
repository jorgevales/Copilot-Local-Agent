"""NOT RUN in static staging. Contract/policy tests for a later authorised phase."""
from copy import deepcopy
import json
import unittest

from copilot_agent.discovery_contracts import (DiscoveryError, compile_manifest, parse_contract,
                                              schema, validate_contract)
from copilot_agent.discovery_http import retry_after
from copilot_agent.discovery_scope import Scope, public_address
from copilot_agent.protocol import validate_schema
from tests.discovery_fixtures import ORIGIN, manifest


class ContractTests(unittest.TestCase):
    def assert_rejected(self, value, code=None):
        with self.assertRaises(DiscoveryError) as caught:
            compile_manifest(value)
        if code:
            self.assertEqual(caught.exception.code, code)

    def test_valid_graph_is_immutable_and_ordered(self):
        m = manifest()
        graph = compile_manifest(m, 'dcurrent')
        m['tasks'][1]['operation'] = 'unsafe'
        self.assertEqual(graph.order, ('bootstrap', 'pages', 'structure', 'validate', 'aggregate'))
        self.assertEqual(graph.manifest['tasks'][1]['operation'], 'fetch')

    def test_duplicate_json_keys_zero_execution(self):
        with self.assertRaises(DiscoveryError) as caught:
            parse_contract('{"kind":1,"kind":2}')
        self.assertEqual(caught.exception.code, 'duplicate_key')

    def test_depth_and_input_byte_limits(self):
        for raw in ('[' * 33 + '0' + ']' * 33, ' ' * (256 * 1024 + 1)):
            with self.assertRaises(DiscoveryError):
                parse_contract(raw)

    def test_unknown_fields_wrong_version_and_unknown_operation(self):
        for mutate in (lambda m: m.update(extra='untrusted'), lambda m: m.update(version='2.0'),
                       lambda m: m['tasks'][1].update(operation='shell')):
            m = manifest(); mutate(m); self.assert_rejected(m)

    def test_stale_request(self):
        with self.assertRaises(DiscoveryError) as caught:
            compile_manifest(manifest(), 'dother')
        self.assertEqual(caught.exception.code, 'stale_request')

    def test_duplicate_task_missing_parent_cycle(self):
        m = manifest(); m['tasks'][1]['id'] = 'bootstrap'; self.assert_rejected(m)
        m = manifest(); m['tasks'][1]['depends_on'][0]['task_id'] = 'missing'; self.assert_rejected(m)
        m = manifest(); m['tasks'][1]['depends_on'][0]['task_id'] = 'validate'; self.assert_rejected(m, 'dependency_cycle')

    def test_mapping_and_typed_ancestor_reference(self):
        m = manifest(); m['tasks'][1]['output_type'] = 'scope_evidence'; self.assert_rejected(m, 'operation_mapping')
        m = manifest(); m['tasks'][2]['inputs']['evidence_from'] = ['aggregate']; self.assert_rejected(m, 'evidence_reference')

    def test_bootstrap_and_aggregate_terminal_sink(self):
        m = manifest(); m['tasks'][2]['depends_on'] = []; self.assert_rejected(m, 'graph_roots')
        m = manifest(); m['tasks'].append(deepcopy(m['tasks'][1])); m['tasks'][-1]['id'] = 'orphan'; self.assert_rejected(m, 'aggregate_sink')

    def test_browser_network_auth_and_no_remote_approval(self):
        m = manifest(); m['permitted_workers'].append('browser'); self.assert_rejected(m, 'capability_unavailable')
        m = manifest(); m['authentication'] = {'mode': 'approved_session', 'context_ref': 'model-cannot-grant'}; self.assert_rejected(m, 'authentication_unavailable')
        m = manifest(); m['tasks'][1]['approval_requirement'] = 'none'; self.assert_rejected(m, 'approval_required')

    def test_nested_budget_and_capability_limits(self):
        for change in ({'task_seconds': 50}, {'concurrency': 5}, {'browser_contexts': 1}, {'replans': 1}):
            m = manifest(); m['budgets'].update(change); self.assert_rejected(m)

    def test_segment_scope_exclusions_win_and_no_subdomains(self):
        m = manifest(); m['scope']['allow_paths'] = ['/documents']; m['scope']['exclude_paths'] = ['/documents/settings']
        scope = Scope(m['scope'])
        self.assertEqual(scope.resolve(ORIGIN + '/documents/reports').path, '/documents/reports')
        for url in (ORIGIN + '/documents/settings', ORIGIN + '/documentstore', 'https://sub.fixture.example/documents'):
            with self.assertRaises(DiscoveryError): scope.resolve(url)

    def test_generic_spanish_home_route_excludes_patient_identifiers(self):
        scope = Scope(manifest()['scope'])
        self.assertEqual('/inicio', scope.resolve(ORIGIN + '/inicio').path)
        with self.assertRaises(DiscoveryError):
            scope.resolve(ORIGIN + '/pacientes/cmrmcpaof000004ikeo3aql24')

    def test_encoded_separator_query_userinfo_literal_ip_and_writes(self):
        scope = Scope(manifest()['scope'])
        for url in (ORIGIN + '/documents%2fsettings', ORIGIN + '/documents/../settings', ORIGIN + '/?token=CANARY',
                    'https://user:secret@fixture.example/', 'https://127.0.0.1/', ORIGIN + '/delete', ORIGIN + '//documents'):
            with self.assertRaises(DiscoveryError): scope.resolve(url)

    def test_public_ip_proof_rejects_private_reserved_and_mapped(self):
        for value in ('127.0.0.1', '10.1.2.3', '169.254.169.254', '100.64.0.1', '192.0.2.1', '::1', '::ffff:127.0.0.1', 'ff02::1'):
            self.assertFalse(public_address(value), value)
        self.assertTrue(public_address('8.8.8.8'))

    def test_formats_and_unsupported_keywords_fail_closed(self):
        self.assertTrue(validate_schema('not-a-date', {'type': 'string', 'format': 'date-time'}))
        self.assertTrue(validate_schema('https://example.com', {'type': 'string', 'format': 'made-up'}))
        self.assertTrue(validate_schema({}, {'allOf': [{'type': 'object'}]}))
        self.assertFalse(validate_schema('2026-01-01T00:00:00Z', {'type': 'string', 'format': 'date-time'}))

    def test_retry_after_is_bounded_by_scheduler_not_silently_capped(self):
        self.assertEqual(retry_after('120'), 120)
        self.assertEqual(retry_after('not-a-delay'), 2)

    def test_testing_config_load_pins_selected_source_not_remembered_live_root(self):
        from unittest.mock import patch
        from copilot_agent.config import Config, PROJECT_ROOT
        from tests.discovery_fixtures import workspace
        with workspace() as (root, _):
            path = root / 'testing-config.json'
            path.write_text(json.dumps({'root': str(root / 'remembered-live-root')}))
            with patch.dict('os.environ', {'COPILOT_AGENT_EXECUTION_MODE': 'testing', 'COPILOT_AGENT_DISCOVERY_FLAGS': 'manifest_path'}), \
                    patch('copilot_agent.config.discover_onedrive_accounts', return_value=[]), \
                    patch('copilot_agent.config.saved_storage_choice', return_value=None):
                cfg = Config.load(path)
            self.assertEqual(cfg.root, PROJECT_ROOT.resolve())
            self.assertTrue(cfg.manifest_path)

    def test_testing_preferences_never_overwrite_live_settings(self):
        from copilot_agent.storage import read_user_settings, save_user_settings, SETTINGS_FILE, TESTING_SETTINGS_FILE
        from tests.discovery_fixtures import workspace
        with workspace() as (root, _):
            directory = root / 'preferences'
            save_user_settings(directory, {'config': {'root': 'remembered-live-root', 'model': 'live-model'}})
            live = (directory / SETTINGS_FILE).read_bytes()
            inherited = read_user_settings(directory, testing=True)
            self.assertEqual(inherited['config']['model'], 'live-model')
            save_user_settings(directory, {'config': {'model': 'testing-model'}}, testing=True)
            self.assertEqual((directory / SETTINGS_FILE).read_bytes(), live)
            self.assertTrue((directory / TESTING_SETTINGS_FILE).is_file())
            self.assertEqual(read_user_settings(directory)['config']['model'], 'live-model')
            self.assertEqual(read_user_settings(directory, testing=True)['config']['model'], 'testing-model')

    def test_all_seven_local_schema_assets_exist(self):
        from copilot_agent.discovery_contracts import KINDS
        self.assertEqual(len(KINDS), 7)
        for kind in KINDS:
            self.assertEqual(schema(kind)['properties']['kind']['const'], kind)
