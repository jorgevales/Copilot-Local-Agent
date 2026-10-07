"""Contract/state checks with retained artifacts and no external tools."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import os
import unittest
from unittest.mock import patch

from copilot_agent.approvals import ApprovalManager
from copilot_agent.config import Config, PROJECT_ROOT
from copilot_agent.findings import Findings
from copilot_agent.prompts import PromptBuilder
from copilot_agent.protocol import BEGIN, END, ProtocolError, parse_response, validate_schema
from copilot_agent.state import SessionState, canonical_hash


def retained_root(prefix):
    base = Path(os.environ.get('COPILOT_TEST_ROOT', str(PROJECT_ROOT / 'runtime' / 'test-runs')))
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=base))


def envelope(session='session', request='request', **changes):
    value = {'protocol_version': '1.0', 'session_id': session, 'request_id': request,
             'response_id': 'response-' + request, 'response_type': 'final',
             'user_response': 'Verified answer.', 'task_interpretation': 'Answer the synthetic request.',
             'decision_summary': 'No local tool is needed.', 'assumptions': [],
             'action_plan': [{'step': 1, 'action': 'Provide the answer.', 'verification': 'Check requested wording.'}],
             'tools_required': False, 'tool_requests': [], 'approval_required': False,
             'code_runner_proposal': None, 'risk_summary': 'No external side effects.',
             'continuation_state': 'complete', 'clarification': None, 'useful_findings': [],
             'completion_status': 'complete', 'recoverable_errors': []}
    value.update(changes)
    return value


def encoded(value):
    return BEGIN + '\n' + json.dumps(value) + '\n' + END


class FixtureRegistry:
    def __init__(self):
        self.calls = []

    def definitions(self):
        return [
            {'name': 'synthetic.read', 'version': '1.0', 'approval_policy': 'read_only', 'timeout': .1,
             'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['path'],
                              'properties': {'path': {'type': 'string', 'minLength': 1}}}},
            {'name': 'synthetic.write', 'version': '1.0', 'approval_policy': 'user_approval', 'timeout': .1,
             'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['path'],
                              'properties': {'path': {'type': 'string', 'minLength': 1}}}},
            {'name': 'code_runner', 'version': '1.0', 'approval_policy': 'immutable_plan_approval', 'timeout': .1,
             'input_schema': {'type': 'object'}}]

    async def execute(self, name, arguments, context):
        self.calls.append((name, copy.deepcopy(arguments), dict(context)))
        return {'ok': True, 'result': {'evidence': 'Synthetic mock observation.'}}


def make_fixture(prefix='contract-'):
    root = retained_root(prefix)
    (root / 'workspace').mkdir()
    (root / 'guidance').mkdir()
    (root / 'schemas').mkdir()
    for source in (PROJECT_ROOT / 'guidance').glob('0[1-8]-*.md'):
        (root / 'guidance' / source.name).write_bytes(source.read_bytes())
    (root / 'schemas' / 'response-v1.schema.json').write_bytes(
        (PROJECT_ROOT / 'schemas' / 'response-v1.schema.json').read_bytes())
    config = Config(root=root, profile_dir=root / 'profile', allowed_roots=[str(root / 'workspace')],
                    max_corrections=1, max_tool_rounds=3)
    config.validate()
    state = SessionState(root / 'session')
    return root, config, state, FixtureRegistry()


class ProtocolTests(unittest.TestCase):
    def assert_rejected(self, value, code=None, registry=None):
        with self.assertRaises(ProtocolError) as caught:
            parse_response(encoded(value), 'session', 'request', registry)
        if code:
            self.assertEqual(code, caught.exception.code)

    def test_documented_no_tool_example(self):
        import re
        text = (PROJECT_ROOT / 'guidance' / '02-response-protocol.md').read_text(encoding='utf-8')
        value = json.loads(re.search(r'```json\n(.*?)\n```', text, re.S).group(1))
        self.assertEqual('final', parse_response(encoded(value), value['session_id'], value['request_id'])['response_type'])

    def test_unique_envelope_and_duplicate_json_keys(self):
        valid = encoded(envelope())
        for raw in (valid + valid, END + json.dumps(envelope()) + BEGIN,
                    BEGIN + '{"protocol_version":"1.0","protocol_version":"1.0"}' + END):
            with self.subTest(raw=raw[:60]), self.assertRaises(ProtocolError):
                parse_response(raw, 'session', 'request')

    def test_nonfinite_truncated_and_unknown_values_rejected(self):
        for raw in (BEGIN + '{"value":NaN}' + END, BEGIN + '{"value":Infinity}' + END,
                    BEGIN + json.dumps(envelope())[:-5] + END):
            with self.subTest(raw=raw[:50]), self.assertRaises(ProtocolError):
                parse_response(raw, 'session', 'request')
        self.assert_rejected(envelope(unregistered=True), 'missing_required_fields')
        self.assert_rejected(envelope(protocol_version='99'), 'wrong_schema_version')

    def test_stale_identity_and_seen_response_are_rejected(self):
        self.assert_rejected(envelope(session_id='other'), 'stale_response')
        self.assert_rejected(envelope(request_id='old'), 'stale_response')
        with self.assertRaises(ProtocolError):
            parse_response(encoded(envelope()), 'session', 'request', seen_response_ids=['response-request'])

    def test_inconsistent_state_and_boolean_step_are_rejected(self):
        for changed in ({'tools_required': True}, {'continuation_state': 'continue'},
                        {'completion_status': 'in_progress'}, {'clarification': 'Unexpected question'},
                        {'action_plan': [{'step': True, 'action': 'Answer', 'verification': 'Check'}]},
                        {'action_plan': [{'step': 2, 'action': 'Answer', 'verification': 'Check'}]}):
            with self.subTest(changed=changed):
                self.assert_rejected(envelope(**changed))

    def test_catalogue_input_validation_and_distinct_call_ids(self):
        call = {'call_id': 'one', 'name': 'synthetic.read', 'version': '1.0',
                'arguments': {'path': 'synthetic.txt'}, 'expected_result': 'Read synthetic text.'}
        response = envelope(response_type='tool_request', tool_requests=[call], tools_required=True,
                            continuation_state='continue', completion_status='in_progress')
        registry = FixtureRegistry()
        self.assertEqual('tool_request', parse_response(encoded(response), 'session', 'request', registry)['response_type'])
        invalid = copy.deepcopy(response)
        invalid['tool_requests'][0]['arguments']['extra'] = 'unsupported'
        self.assert_rejected(invalid, 'unsafe_tool_arguments', registry)
        invalid = copy.deepcopy(response)
        invalid['tool_requests'][0]['name'] = 'invented.execute'
        self.assert_rejected(invalid, 'unsupported_tool', registry)
        invalid = copy.deepcopy(response)
        invalid['tool_requests'].append(copy.deepcopy(call))
        self.assert_rejected(invalid, 'contradictory_execution_state', registry)

    def test_schema_validator_fails_closed_for_unsupported_vocabulary(self):
        self.assertTrue(validate_schema('text', {'type': 'string', 'unevaluatedProperties': False}))


class StateAndPromptTests(unittest.TestCase):
    def setUp(self):
        output = patch('builtins.print')
        output.start()
        self.addCleanup(output.stop)

    def test_submission_only_counts_after_identity_confirmation(self):
        state = SessionState(retained_root('count-'))
        state.begin_submission('one', 'Synthetic input')
        self.assertEqual(0, state.message_count)
        with self.assertRaises(RuntimeError):
            state.begin_submission('two', 'Do not duplicate uncertain send')
        with self.assertRaises(RuntimeError):
            state.confirm_submission('wrong')
        state.reconcile_submission(False)
        self.assertEqual(0, state.message_count)
        state.begin_submission('two', 'Verified submission')
        state.confirm_submission('two')
        self.assertEqual(1, state.message_count)
        with self.assertRaises(RuntimeError):
            state.confirm_submission('two')

    def test_resume_records_uncertainty_and_clears_grants(self):
        root = retained_root('resume-')
        state = SessionState(root)
        call = {'call_id': 'pending', 'name': 'synthetic.write', 'version': '1.0', 'arguments': {'path': 'new.txt'}}
        state.begin_call(call)
        state.grant('immutable-hash', 'plan')
        state.begin_submission('pending-request', 'Uncertain submission')
        resumed = SessionState(root, resume=True)
        self.assertEqual('submission_uncertain', resumed.data['status'])
        self.assertEqual('uncertain', resumed.data['calls']['pending']['status'])
        self.assertEqual({}, resumed.data['approvals'])
        with self.assertRaises(RuntimeError):
            resumed.begin_call(call)
        self.assertEqual(0, resumed.message_count)

    def test_findings_save_immediately_deduplicate_and_filter(self):
        manager = Findings(retained_root('findings-'))
        item = {'key': 'synthetic-path', 'content': 'The synthetic fixture uses a retained workspace.', 'provenance': 'Synthetic fixture inspection.'}
        self.assertEqual(1, manager.accept([item], 'first')['accepted'])
        stored = json.loads(manager.path.read_text(encoding='utf-8'))
        self.assertEqual(1, len(stored['findings']))
        self.assertIn('retained workspace', manager.attachment.read_text(encoding='utf-8'))
        self.assertEqual(1, manager.accept([dict(item, content='  THE SYNTHETIC FIXTURE USES A RETAINED WORKSPACE. ')], 'second')['duplicate'])
        self.assertEqual(1, manager.accept([dict(item, content='authentication token: never retain this')], 'third')['rejected'])
        for ordinal in range(1, 22):
            self.assertEqual(ordinal in (10, 20), manager.attachment_due(ordinal))

    def test_prompt_keeps_authoritative_requirements_in_reference(self):
        root, config, state, registry = make_fixture('context-')
        config.max_context_chars = 300
        builder = PromptBuilder(config, registry, state, Findings(state.directory))
        state.data['requirements'] = ['Preserve this requirement: ' + 'synthetic ' * 200]
        state.data['decisions'] = [{'outcome': 'Keep prior verified outcome.'}]
        state.data['unresolved_questions'] = ['Which synthetic variant?']
        state.data['current_plan'] = [{'step': 1, 'action': 'Retain context', 'verification': 'Read attachment'}]
        text, attachments = builder.build('user_turn', 'Continue.', 'current-request')
        message = json.loads(text)
        self.assertEqual('session-context.md', message['context']['reference_attachment'])
        self.assertIn(builder.context_file, attachments)
        reference = builder.context_file.read_text(encoding='utf-8')
        self.assertIn(state.data['requirements'][0], reference)
        self.assertIn('Keep prior verified outcome.', reference)
        self.assertIn('Which synthetic variant?', reference)
        self.assertIn('Never delete files', reference)

    def test_reference_snapshot_retains_approval_and_pending_safety_state(self):
        root, config, state, registry = make_fixture('safety-context-')
        config.max_context_chars = 300
        builder = PromptBuilder(config, registry, state, Findings(state.directory))
        state.grant('synthetic-immutable-plan-hash', 'plan')
        call = {'call_id': 'uncertain-call', 'name': 'synthetic.write', 'version': '1.0', 'arguments': {'path': 'evidence.txt'}}
        state.begin_call(call)
        state.finish_call(call['call_id'], {'ok': False, 'error': {'code': 'timeout', 'message': 'Possible partial effect.'}})
        builder.build('user_turn', 'Keep restrictions and pending decisions.', 'safety-request')
        reference = builder.context_file.read_text(encoding='utf-8')
        self.assertIn('synthetic-immutable-plan-hash', reference)
        self.assertIn('uncertain-call', reference)
        self.assertIn('uncertain', reference)

    def test_uncertain_action_cannot_replay_with_a_new_call_id(self):
        state = SessionState(retained_root('uncertain-replay-'))
        original = {'call_id': 'original', 'name': 'synthetic.write', 'version': '1.0', 'arguments': {'path': 'evidence.txt'}}
        state.begin_call(original)
        state.finish_call('original', {'ok': False, 'error': {'code': 'timeout', 'message': 'Potential partial effect.'}})
        self.assertEqual('uncertain', state.data['calls']['original']['status'])
        with self.assertRaises(RuntimeError):
            state.begin_call(dict(original, call_id='renamed'))

    def test_uncertainty_blocks_alias_and_other_writes_but_allows_inspection(self):
        state = SessionState(retained_root('uncertain-global-gate-'))
        original = {'call_id': 'original', 'name': 'synthetic.write', 'version': '1.0', 'arguments': {'path': 'evidence.txt'}}
        state.begin_call(original)
        state.finish_call('original', {'ok': False, 'error': {'code': 'timeout', 'message': 'Possible partial effect.'}})
        for path in ('./evidence.txt', 'another-output.txt'):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                state.begin_call(dict(original, call_id='alias-' + path, arguments={'path': path}))
        inspection = {'call_id': 'inspect', 'name': 'synthetic.read', 'version': '1.0', 'arguments': {'path': 'evidence.txt'}}
        state.begin_call(inspection, state_changing=False)
        state.finish_call('inspect', {'ok': True, 'result': {'evidence': 'Synthetic read-only observation.'}})
        state.reconcile_call('original', 'not_executed')
        state.begin_call(dict(original, call_id='reviewed-next-write'))
        self.assertEqual('executing', state.data['calls']['reviewed-next-write']['status'])

    def test_initial_guidance_catalogue_and_schema_fit_observed_attachment_capacity(self):
        root, config, state, registry = make_fixture('initial-attachments-')
        builder = PromptBuilder(config, registry, state, Findings(state.directory))
        text, attachments = builder.build('initialize', 'Synthetic initialization.', 'initial-request')
        names = [path.name for path in attachments]
        self.assertEqual(8, len(names))
        self.assertEqual([path.name for path in builder.guidance[:6]], names[:6])
        from copilot_agent.bundle import read_bundle_components
        recovered = {path.name: path.read_bytes() for path in builder.guidance[:6]}
        for group in builder.bundle['group_records']:
            recovered.update(read_bundle_components(group['path'], group))
        self.assertEqual(10, len(recovered))
        for source in builder.component_paths:
            self.assertEqual(source.read_bytes(), recovered[source.name])
        self.assertEqual(10, json.loads(text)['startup_references']['component_count'])
        self.assertLessEqual(len(names), 20)
        # Restored initialization can coincide with a findings boundary and a context reference.
        state.data['message_count'] = 9
        config.max_context_chars = 300
        text, attachments = builder.build('initialize', 'Restore guidance.', 'restore-request')
        self.assertEqual(10, len(attachments))
        self.assertIn(builder.findings.attachment, attachments)
        self.assertIn(builder.context_file, attachments)
        self.assertLessEqual(len(attachments), 20)

    def test_catalogue_advertises_effective_code_runner_timeout_limit(self):
        root, config, state, registry = make_fixture('runner-timeout-catalogue-')
        from copilot_agent.tools import ToolRegistry
        config.tool_timeout = 7
        builder = PromptBuilder(config, ToolRegistry(), state, Findings(state.directory))
        catalogue = json.loads(builder.catalogue.read_text(encoding='utf-8'))
        runner = next(item for item in catalogue['tools'] if item['name'] == 'code_runner')
        self.assertEqual(7, runner['input_schema']['properties']['timeout_seconds']['maximum'])
        self.assertEqual(7, runner['limits']['timeout_seconds'])
        self.assertIn('configured limit of 7 seconds', runner['description'])

    def test_plan_grant_covers_exact_plan_and_once_is_not_persistent(self):
        async def exercise():
            state = SessionState(retained_root('approval-'))
            decisions = []
            def decide(preview):
                decisions.append(preview)
                return 'plan' if len(decisions) == 1 else 'once'
            manager = ApprovalManager(state, decide)
            call = {'call_id': 'one', 'name': 'synthetic.write', 'arguments': {'path': 'one.txt'}}
            plan = {'tool_requests': [call], 'risk_summary': 'Create a synthetic output.'}
            allowed, digest = await manager.request(plan, call)
            self.assertTrue(allowed)
            self.assertEqual(canonical_hash(plan), digest)
            self.assertTrue((await manager.request(copy.deepcopy(plan), call))[0])
            self.assertEqual(1, len(decisions))
            changed = copy.deepcopy(plan)
            changed['tool_requests'][0]['arguments']['path'] = 'changed.txt'
            await manager.request(changed, changed['tool_requests'][0])
            await manager.request(changed, changed['tool_requests'][0])
            self.assertEqual(3, len(decisions))
        asyncio.run(exercise())

    def _prepared_code_plan_fixture(self):
        from copilot_agent.code_runner import CodeRunner
        from copilot_agent.policy import PathPolicy
        state = SessionState(retained_root('prepared-plan-'))
        runner = CodeRunner(PathPolicy([state.directory]),state.directory)
        arguments = {'script':'print(1)', 'language':'python_subset', 'purpose':'Print a synthetic value.',
                     'working_directory':str(state.directory), 'read_paths':[], 'create_paths':[],
                     'expected_outputs':[], 'commands':[], 'subprocesses':[], 'network_destinations':[],
                     'permissions':[], 'risk_summary':'No external effects.', 'recovery_notes':'No file changes.'}
        first = {'call_id':'first', 'name':'code_runner', 'version':'1.0', 'arguments':arguments}
        second = copy.deepcopy(first)
        second['call_id'] = 'second'
        second['arguments']['script'] = 'print(2)'
        plan = {'tool_requests':[first,second], 'risk_summary':'Two separate synthetic calculations.'}
        prepared = {call['call_id']:runner.prepare(call['arguments']) for call in plan['tool_requests']}
        return state,runner,plan,prepared

    def test_complete_prepared_code_plan_grant_covers_both_exact_proposals(self):
        async def exercise():
            state,runner,plan,prepared = self._prepared_code_plan_fixture()
            decisions = []
            manager = ApprovalManager(state,lambda preview:decisions.append(preview) or 'plan')
            first,second = plan['tool_requests']
            allowed,digest = await manager.request(plan,first,prepared['first'],prepared_plan=prepared)
            self.assertTrue(allowed)
            allowed_again,digest_again = await manager.request(copy.deepcopy(plan),second,
                runner.prepare(second['arguments']),prepared_plan=copy.deepcopy(prepared))
            self.assertTrue(allowed_again)
            self.assertEqual(digest,digest_again)
            self.assertEqual(len(decisions),1)
            self.assertEqual(decisions[0]['prepared_pending_plan'],prepared)
            self.assertEqual(decisions[0]['prepared_code'],prepared['first'])
            self.assertEqual(set(decisions[0]['prepared_pending_plan']),{'first','second'})
        with patch('builtins.print'):
            asyncio.run(exercise())

    def test_changed_script_or_prepared_metadata_requires_new_plan_decision(self):
        async def exercise():
            state,runner,plan,prepared = self._prepared_code_plan_fixture()
            decisions = []
            manager = ApprovalManager(state,lambda preview:decisions.append(preview) or ('plan' if len(decisions)==1 else 'deny'))
            first,second = plan['tool_requests']
            _,original_hash = await manager.request(plan,first,prepared['first'],prepared_plan=prepared)
            changed_plan = copy.deepcopy(plan)
            changed_plan['tool_requests'][1]['arguments']['script'] = 'print(3)'
            changed = {call['call_id']:runner.prepare(call['arguments']) for call in changed_plan['tool_requests']}
            allowed,changed_hash = await manager.request(changed_plan,changed_plan['tool_requests'][1],changed['second'],prepared_plan=changed)
            self.assertFalse(allowed)
            self.assertNotEqual(decisions[0]['plan_hash'],decisions[1]['plan_hash'])
            changed_metadata = copy.deepcopy(prepared)
            changed_metadata['second']['limitations'] = 'Changed execution boundary.'
            allowed,_ = await manager.request(plan,second,changed_metadata['second'],prepared_plan=changed_metadata)
            self.assertFalse(allowed)
            self.assertEqual(len(decisions),3)
            self.assertNotEqual(original_hash,decisions[2]['plan_hash'])
        with patch('builtins.print'):
            asyncio.run(exercise())

    def test_once_prepared_plan_approval_never_approves_other_script(self):
        async def exercise():
            state,runner,plan,prepared = self._prepared_code_plan_fixture()
            decisions = []
            manager = ApprovalManager(state,lambda preview:decisions.append(preview) or ('once' if len(decisions)==1 else 'deny'))
            first,second = plan['tool_requests']
            self.assertTrue((await manager.request(plan,first,prepared['first'],prepared_plan=prepared))[0])
            self.assertFalse((await manager.request(plan,second,prepared['second'],prepared_plan=prepared))[0])
            self.assertEqual(len(decisions),2)
            self.assertEqual(decisions[0]['plan_hash'],decisions[1]['plan_hash'])
            self.assertNotEqual(decisions[0]['call_hash'],decisions[1]['call_hash'])
        with patch('builtins.print'):
            asyncio.run(exercise())

    def test_partial_mixed_or_changed_current_preparation_never_uses_plan_grant(self):
        async def exercise():
            state,runner,plan,prepared = self._prepared_code_plan_fixture()
            decisions = []
            manager = ApprovalManager(state,lambda preview:decisions.append(preview) or 'plan')
            first,second = plan['tool_requests']
            await manager.request(plan,first,prepared['first'],prepared_plan=prepared)
            with self.assertRaises(ValueError):
                await manager.request(plan,second,prepared['second'],prepared_plan={'second':prepared['second']})
            mixed = copy.deepcopy(plan)
            mixed['tool_requests'][1]['name'] = 'copilot.download'
            with self.assertRaises(ValueError):
                await manager.request(mixed,first,prepared['first'],prepared_plan=prepared)
            changed_current = copy.deepcopy(prepared['second'])
            changed_current['proposal_hash'] = '0'*64
            with self.assertRaises(ValueError):
                await manager.request(plan,second,changed_current,prepared_plan=prepared)
            self.assertEqual(len(decisions),1)
        with patch('builtins.print'):
            asyncio.run(exercise())

    def test_default_per_call_preparation_does_not_inherit_complete_plan_binding(self):
        async def exercise():
            state,runner,plan,prepared = self._prepared_code_plan_fixture()
            decisions = []
            manager = ApprovalManager(state,lambda preview:decisions.append(preview) or ('plan' if len(decisions)==1 else 'deny'))
            first,second = plan['tool_requests']
            self.assertTrue((await manager.request(plan,first,prepared['first']))[0])
            self.assertFalse((await manager.request(plan,second,prepared['second']))[0])
            self.assertEqual(len(decisions),2)
            self.assertNotIn('prepared_pending_plan',decisions[0])
        with patch('builtins.print'):
            asyncio.run(exercise())

    def test_config_rejects_bad_types_and_unknown_settings(self):
        for changed in ({'debug_port': True}, {'visible': 'false'}, {'max_corrections': 13},
                        {'max_tool_rounds': 0}, {'allowed_roots': []}, {'poll_interval': float('nan')}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                Config(**changed).validate()
        root = retained_root('config-')
        path = root / 'bad.json'
        path.write_text('{"unregistered_setting":true}', encoding='utf-8')
        with self.assertRaises(ValueError):
            Config.load(path)
