"""The pre-request guide follows public schemas and does no runtime discovery."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from copilot_agent.rea import REA_SPECS
from copilot_agent.rea_guidance import rea_usage_guidance


class REAGuidanceTests(unittest.TestCase):
    def test_initial_catalogue_contains_guidance_before_any_request(self):
        from copilot_agent.findings import Findings
        from copilot_agent.policy import PolicyError
        from copilot_agent.prompts import PromptBuilder
        from copilot_agent.tools import ToolRegistry
        from tests.test_protocol_state import make_fixture
        with patch('copilot_agent.policy.mapped_s_drive_root', side_effect=PolicyError('offline fixture')), \
             patch('copilot_agent.config.mapped_s_drive_root', side_effect=PolicyError('offline fixture')):
            root, config, state, _ = make_fixture('rea-initial-guide-')
            config._automation_test_mode = True
            config.rea_backend = 'python_native'
            builder = PromptBuilder(config, ToolRegistry(config), state, Findings(state.directory))
            initial = json.loads(builder.build('initialize', 'Read the contract.', 'guide-initial')[0])
            catalogue = json.loads(builder.catalogue.read_text(encoding='utf-8'))
        self.assertEqual(rea_usage_guidance(config), catalogue['rea_usage_guidance'])
        definitions = {item['name']: item for item in catalogue['tools']}
        for name in REA_SPECS:
            self.assertEqual(REA_SPECS[name][0], definitions[name]['usage_guidance']['input_schema'])
        self.assertIn('rea_usage_guidance', initial['research_routing']['instruction'])

    def test_exact_three_schemas_and_json_serializable(self):
        guide = rea_usage_guidance()
        json.dumps(guide, allow_nan=False)
        self.assertEqual(set(guide['methods']), set(REA_SPECS))
        for name, method in guide['methods'].items():
            self.assertEqual(method['input_schema'], REA_SPECS[name][0])
            Draft202012Validator(method['input_schema']).validate(method['example']['arguments'])

    def test_readiness_not_probed_and_configured_limits_visible(self):
        with patch('copilot_agent.rea.rea_health', side_effect=AssertionError('No probes in guidance')):
            guide = rea_usage_guidance({'rea_backend': 'node_cli', 'rea_timeout_seconds': 71,
                                        'rea_max_output_bytes': 333333,
                                        'rea_max_transport_bytes': 22222222,
                                        'rea_fallback_timeout_seconds': 19})
        self.assertEqual(guide['backend_rules']['configured'], 'node_cli')
        self.assertEqual(guide['limits']['analysis_timeout_seconds'], 71)
        self.assertEqual(guide['limits']['output_bytes'], 333333)
        self.assertEqual(guide['limits']['transport_bytes'], 22222222)
        self.assertEqual(guide['limits']['fallback_timeout_seconds'], 19)

    def test_mutation_does_not_change_authoritative_schema(self):
        guide = rea_usage_guidance()
        guide['methods']['rea.inspect_page']['input_schema']['properties']['observation_ms']['maximum'] = 5000
        self.assertEqual(REA_SPECS['rea.inspect_page'][0]['properties']['observation_ms']['maximum'], 3000)
        self.assertEqual(rea_usage_guidance()['methods']['rea.inspect_page']['input_schema']['properties']['observation_ms']['maximum'], 3000)

    def test_invalid_guessed_parameters_are_explicitly_rejected(self):
        schema = rea_usage_guidance()['methods']['rea.inspect_page']['input_schema']
        validator = Draft202012Validator(schema)
        self.assertTrue(list(validator.iter_errors({'max_nodes': 10000})))
        self.assertTrue(list(validator.iter_errors({'observation_ms': 5000})))
        validator.validate({'observation_ms': 0})
        validator.validate({'tab_id': 'owned-tab-from-previous-tool', 'observation_ms': 3000})

    def test_fallback_and_node_ceiling_cannot_be_confused(self):
        guide = rea_usage_guidance()
        self.assertEqual(guide['limits']['python_page']['dom_elements'], 2000)
        self.assertFalse(guide['limits']['python_page']['configurable'])
        self.assertIn('not an upstream REA DOM limit', guide['limits']['python_page']['reason'])
        self.assertIn('not a replacement status enum', guide['status_meanings']['fallback_condition'])
        self.assertIn('prior_backend_attempt', guide['status_meanings']['fallback_condition'])
        self.assertIn('No Python substitution', guide['backend_rules']['node_cli'])

    def test_files_are_templates_not_claims_of_real_inputs(self):
        guide = rea_usage_guidance()
        for name in ('rea.analyze_capture', 'rea.analyze_artifact'):
            self.assertIn('Template only', guide['methods'][name]['example']['condition'])
        self.assertIn('never send this placeholder', guide['methods']['rea.analyze_capture']['example']['condition'])
        invocation = guide['manual_comparison']['invocation']
        self.assertEqual(invocation[:2], ['<NODE_ROOT>\\node.exe', '<REA_RUNTIME_ROOT>\\scripts\\rea.mjs'])
        self.assertNotIn(str(Path.home()), json.dumps(guide))

    def test_upstream_source_and_output_controls_identified(self):
        guide = rea_usage_guidance()
        self.assertEqual(guide['authority']['version'], 'rea-agents 6.5.0')
        self.assertIn('src/cliOutput.ts', guide['authority']['upstream'])
        self.assertIn('--filter-output <comma-delimited paths/slices>', guide['upstream_output']['supported'])
        self.assertIn('--token-limit/--token-offset', guide['upstream_output']['structured_output'])


if __name__ == '__main__':
    unittest.main()
