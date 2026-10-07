"""Mock transport/registry tests; no browser, network or deletion."""
import copy
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from copilot_agent.browser import CaptureTimeoutError, SubmissionAmbiguousError
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.policy import PolicyError
from copilot_agent.protocol import BEGIN, END, ProtocolError
from copilot_agent.tools import ToolRegistry
from tests.test_protocol_state import encoded, envelope, make_fixture


class MockBrowser:
    def __init__(self, responders):
        self.responders = list(responders)
        self.sent = []
        self.closed = False

    async def exchange(self, text, request_id, attachments=(), on_submitted=None):
        message = json.loads(text)
        record = {'message': message, 'attachments': list(attachments),
                  'attachment_text': {p.name: p.read_text(encoding='utf-8') for p in attachments}}
        self.sent.append(record)
        response = self.responders.pop(0)
        if isinstance(response, Exception):
            raise response
        on_submitted()
        result = response(message) if callable(response) else response
        return result if isinstance(result, str) else encoded(result)

    async def close(self, *, preserve_browser_process=False):
        self.closed = True


def final_response(message, **changes):
    return envelope(message['session_id'], message['request_id'], **changes)


def tool_response(message, call_id='read-one', name='synthetic.read', arguments=None):
    call = {'call_id': call_id, 'name': name, 'version': '1.0',
            'arguments': arguments or {'path': 'synthetic.txt'}, 'expected_result': 'Observe synthetic output.'}
    return final_response(message, response_type='tool_request', tools_required=True, tool_requests=[call],
                          continuation_state='continue', completion_status='in_progress',
                          approval_required=name != 'synthetic.read')


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows desktop capability')
    async def test_planner_approval_worker_import_display_and_artifact_progress_end_to_end(self):
        root, config, state, _ = make_fixture('desktop-e2e-')
        registry = ToolRegistry()
        output = root / 'workspace' / 'display-evidence.json'
        script = ("import json\nfrom pathlib import Path\n"
                  "from copilot_agent.desktop import enumerate_displays\n"
                  "displays=enumerate_displays()\n"
                  "Path('display-evidence.json').write_text(json.dumps(displays),encoding='utf-8')\n"
                  "print(json.dumps({'display_count':len(displays)}))\n")
        arguments = {'script':script, 'purpose':'Validate the approved desktop capability chain.',
                     'language':'local_python', 'working_directory':str(output.parent),
                     'read_paths':[], 'create_paths':['display-evidence.json'], 'modify_paths':[],
                     'expected_outputs':['display-evidence.json'], 'commands':[], 'subprocesses':[],
                     'network_destinations':[], 'permissions':['create_files','desktop_capture'],
                     'risk_summary':'Enumerate display metadata and create one evidence file.',
                     'recovery_notes':'No dependent action runs if capability validation fails.',
                     'interpreter':sys.executable, 'arguments':[],
                     'imports':['json','pathlib','copilot_agent.desktop'], 'timeout_seconds':10,
                     'max_output_chars':4000,
                     'expected_effects':['Enumerate displays','Create verified display evidence'],
                     'viewer_windows':[]}
        def planned(message):
            return tool_response(message, 'desktop-capability-e2e', 'code_runner', arguments)
        def finished(message):
            self.assertEqual('tool_results', message['kind'])
            outcome = message['content']['results'][0]
            self.assertTrue(outcome['ok'], outcome)
            self.assertTrue(outcome['result']['outputs'][0]['readable'])
            return final_response(message, user_response='Desktop capability chain verified.')
        browser = MockBrowser([final_response, planned, finished])
        approvals = []
        app = Orchestrator(config, browser, registry, state,
                           approval_decider=lambda preview: approvals.append(preview) or 'once',
                           display=lambda text: None)
        await app.initialize()
        result = await app.turn('Validate the available desktop capability and continue from its actual result.')
        self.assertEqual('Desktop capability chain verified.', result['user_response'])
        self.assertEqual(1, len(approvals))
        self.assertEqual('completed', state.data['calls']['desktop-capability-e2e']['result']['result']['status'])
        self.assertGreaterEqual(len(json.loads(output.read_text(encoding='utf-8'))), 1)

    async def test_complete_prepared_code_plan_asks_once_for_two_scripts(self):
        previews = []
        def approve_plan(preview):
            previews.append(preview)
            return 'plan'
        def request_both(message):
            calls = []
            for number in (1, 2):
                arguments = {'script': 'print(' + str(number) + ')', 'purpose': 'Synthetic script ' + str(number),
                             'language': 'python_subset', 'working_directory': str(root / 'workspace'),
                             'read_paths': [], 'create_paths': [], 'expected_outputs': [], 'commands': [],
                             'network_destinations': [], 'permissions': [], 'risk_summary': 'Print only.',
                             'recovery_notes': 'Retain execution report.'}
                calls.append({'call_id': 'code-' + str(number), 'name': 'code_runner', 'version': '1.0',
                              'arguments': arguments, 'expected_result': 'Print the approved value.'})
            return final_response(message, response_type='tool_request', tools_required=True, tool_requests=calls,
                                  approval_required=True, continuation_state='continue', completion_status='in_progress')
        root, config, state, registry, browser, app = self.fixture([final_response, request_both, final_response], approve_plan)
        await app.initialize()
        await app.turn('Run this exact displayed two-script plan.')
        self.assertEqual(1, len(previews))
        self.assertEqual({'code-1', 'code-2'}, set(previews[0]['prepared_pending_plan']))
        self.assertEqual(2, len(registry.calls))
        self.assertEqual(2, len(state.data['calls']))

    async def test_attachment_plan_cannot_approve_a_later_upload_batch(self):
        previews = []
        def decide(preview):
            previews.append(preview)
            return 'plan' if len(previews) == 1 else 'deny'
        root, config, state, registry, browser, app = self.fixture([final_response, final_response], decide)
        source = root / 'workspace' / 'context.txt'
        source.write_text('Synthetic request context.', encoding='utf-8')
        await app.initialize()
        await app.turn('Use this file.', attachments=[source])
        denied = await app.turn('Use this file.', attachments=[source])
        self.assertEqual('clarification', denied['response_type'])
        self.assertEqual(2, len(previews))
        self.assertNotEqual(previews[0]['complete_pending_plan']['upload_id'], previews[1]['complete_pending_plan']['upload_id'])
        self.assertEqual(2, len(browser.sent))

    async def test_selected_code_file_is_exact_text_without_expanding_tool_roots(self):
        from copilot_agent.attachments import AttachmentQueue
        root, config, state, registry, browser, app = self.fixture([final_response, final_response], decide=lambda preview: 'once')
        source = root / 'context.py'
        original = b'\xef\xbb\xbf# user context\r\nprint("never executed")'
        source.write_bytes(original)
        app.attachment_queue = lambda: AttachmentQueue(config, root)
        with self.assertRaises(PolicyError):
            app.policy.resolve(source, True)
        await app.initialize()
        await app.turn('Use the supplied code as context only.', attachments=[source])
        staged = browser.sent[-1]['attachments'][0]
        self.assertEqual('context.py.txt', staged.name)
        self.assertEqual(original, staged.read_bytes())
        self.assertEqual(original, source.read_bytes())
        self.assertEqual('context.py', browser.sent[-1]['message']['user_attachment_manifest'][0]['name'])
        self.assertEqual([], registry.calls)
        with self.assertRaises(PolicyError):
            app.policy.resolve(source, True)

    async def test_twenty_one_assembled_attachments_never_start_submission(self):
        root, config, state, registry, browser, app = self.fixture([final_response])
        await app.initialize()
        paths = [root / 'workspace' / ('item-' + str(number) + '.txt') for number in range(21)]
        with self.assertRaises(PolicyError):
            await app._send('user_turn', 'Do not send oversized batch.', paths)
        self.assertEqual(1, state.message_count)
        self.assertEqual(1, len(browser.sent))
        self.assertIsNone(state.data['pending_submission'])

    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 10
        output = patch('builtins.print')
        output.start()
        self.addCleanup(output.stop)

    def fixture(self, responders, decide=None):
        root, config, state, registry = make_fixture('orchestrator-')
        browser = MockBrowser(responders)
        app = Orchestrator(config, browser, registry, state, approval_decider=decide, display=lambda text: None)
        return root, config, state, registry, browser, app

    async def test_immediate_findings_save_and_tenth_attachment_include_corrections(self):
        finding = {'key': 'synthetic-fact', 'content': 'The synthetic session uses a verified fixture.', 'provenance': 'Synthetic test response.'}
        responders = [final_response, lambda msg: final_response(msg, useful_findings=[finding])]
        responders += [final_response] * 7
        responders += ['intentionally invalid response', final_response]
        root, config, state, registry, browser, app = self.fixture(responders)
        await app.initialize()
        await app.turn('Record a synthetic durable fact.')
        self.assertEqual(2, state.message_count)
        stored = json.loads(app.findings.path.read_text(encoding='utf-8'))
        self.assertEqual(1, len(stored['findings']))
        for ordinal in range(3, 10):
            await app.turn('Synthetic follow-up ' + str(ordinal))
        await app.turn('Exercise correction at boundary.')
        self.assertEqual(11, state.message_count)
        self.assertEqual('correction', browser.sent[-1]['message']['kind'])
        findings_uploads = [(entry['message']['copilot_message_number'], entry['attachment_text'].get('useful-findings.md'))
                            for entry in browser.sent if 'useful-findings.md' in entry['attachment_text']]
        self.assertEqual([10], [item[0] for item in findings_uploads])
        self.assertIn('verified fixture', findings_uploads[0][1])
        self.assertEqual([10], [entry['ordinal'] for entry in state.data['findings_sync']])
        self.assertEqual([], registry.calls)

    async def test_malformed_call_never_executes_and_correction_can_finish(self):
        def malformed(message):
            result = tool_response(message)
            result['tool_requests'][0]['arguments']['unsupported'] = True
            return result
        root, config, state, registry, browser, app = self.fixture([final_response, malformed, final_response])
        await app.initialize()
        result = await app.turn('Inspect a synthetic file.')
        self.assertEqual('final', result['response_type'])
        self.assertEqual([], registry.calls)
        self.assertEqual('correction', browser.sent[-1]['message']['kind'])
        self.assertEqual('unsafe_tool_arguments', state.data['retry_records'][0]['reason'])

    async def test_same_call_id_cannot_execute_again(self):
        root, config, state, registry, browser, app = self.fixture(
            [final_response, tool_response, tool_response, final_response])
        await app.initialize()
        await app.turn('Inspect without replay.')
        self.assertEqual(1, len(registry.calls))
        self.assertIn('read-one', state.data['calls'])
        self.assertEqual('correction', browser.sent[-1]['message']['kind'])
        self.assertIn('must not be replayed', state.data['retry_records'][0]['errors'][0])

    async def test_denied_code_runner_never_executes_or_creates_output(self):
        previews = []
        def deny(preview):
            previews.append(preview)
            return 'deny'
        root, config, state, registry, browser, app = self.fixture([], deny)
        output = root / 'workspace' / 'must-not-exist.txt'
        proposal = {'script': "write_file('must-not-exist.txt', 'synthetic')", 'purpose': 'Create synthetic evidence.',
                    'language': 'python_subset', 'working_directory': str(root / 'workspace'),
                    'read_paths': [], 'create_paths': ['must-not-exist.txt'], 'expected_outputs': ['must-not-exist.txt'],
                    'commands': [], 'subprocesses': [], 'network_destinations': [], 'permissions': ['create_files'],
                    'risk_summary': 'Create a new synthetic file only.', 'recovery_notes': 'Retain any existing artifact.'}
        browser.responders = [final_response, lambda msg: tool_response(msg, 'code-one', 'code_runner', proposal), final_response]
        await app.initialize()
        await app.turn('Request a reviewed synthetic script.')
        self.assertEqual(1, len(previews))
        self.assertEqual(proposal['script'], previews[0]['prepared_code']['plan']['script'])
        self.assertEqual([], registry.calls)
        self.assertFalse(output.exists())
        self.assertEqual('approval_denied', state.data['calls']['code-one']['result']['error']['code'])
        self.assertEqual('tool_results', browser.sent[-1]['message']['kind'])

    async def test_running_downloaded_source_does_not_request_artifact_delivery_again(self):
        """Offline source/approval/turn regression; registry execution is mocked."""
        previews = []
        root,config,state,registry,browser,app = self.fixture([],lambda preview:previews.append(preview) or 'once')
        source = root / 'workspace' / 'synthetic-download-run.py'
        script = "print('download-run-test')\n"
        source.write_bytes(script.encode('utf-8'))
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        arguments = {'script':script,'purpose':'Run the already downloaded synthetic-download-run.py and report actual execution.',
                     'language':'python_subset','working_directory':str(source.parent),
                     'source_path':str(source),'source_sha256':original_hash,
                     'read_paths':[str(source)],'create_paths':[],'expected_outputs':[],
                     'commands':[],'subprocesses':[],'network_destinations':[],'permissions':['read_files'],
                     'risk_summary':'Read and print the exact reviewed synthetic source only.',
                     'recovery_notes':'Preserve the downloaded source; no new files or network actions.'}
        browser.responders = [final_response,
            lambda message:tool_response(message,'execute-downloaded-source','code_runner',arguments),
            final_response]
        await app.initialize()
        request = ('Request exactly one code_runner call using downloaded synthetic-download-run.py bytes. '
                   'After actual outcome report the result; do not generate or download another artifact. Arguments:\n'+
                   json.dumps(arguments,ensure_ascii=False))
        response = await app.turn(request)
        self.assertEqual(response['completion_status'],'complete')
        self.assertEqual(state.data['status'],'ready')
        self.assertEqual([record['message']['kind'] for record in browser.sent],
                         ['initialize','user_turn','tool_results'])
        self.assertEqual(state.message_count,3)
        self.assertEqual(len(registry.calls),1)
        self.assertEqual(registry.calls[0][0],'code_runner')
        self.assertEqual(registry.calls[0][1],arguments)
        self.assertTrue(registry.calls[0][2]['approved'])
        self.assertEqual(len(previews),1)
        prepared = previews[0]['prepared_code']['plan']
        self.assertEqual(prepared['source_sha256'],original_hash)
        self.assertEqual(Path(prepared['source_path']),source)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original_hash)
        self.assertEqual(state.data['retry_records'],[])

    async def test_denial_stops_dependent_remaining_calls(self):
        def two_calls(message):
            result = tool_response(message, 'write-one', 'synthetic.write')
            result['tool_requests'].append({'call_id': 'dependent-read', 'name': 'synthetic.read', 'version': '1.0',
                                           'arguments': {'path': 'synthetic.txt'}, 'expected_result': 'Read newly created content.'})
            return result
        root, config, state, registry, browser, app = self.fixture([final_response, two_calls, final_response], lambda preview: 'deny')
        await app.initialize()
        await app.turn('Deny the prerequisite.')
        self.assertEqual([], registry.calls)
        self.assertNotIn('dependent-read', state.data['calls'])
        result_payload = browser.sent[-1]['message']['content']
        self.assertEqual(['write-one'], [item['call_id'] for item in result_payload['results']])
        self.assertEqual('approval_denied', result_payload['results'][0]['error']['code'])
        self.assertFalse(result_payload['results'][0]['ok'])

    async def test_read_only_result_returns_evidence_and_session_continues(self):
        root, config, state, registry, browser, app = self.fixture([final_response, tool_response, final_response, final_response])
        await app.initialize()
        await app.turn('Inspect permitted synthetic data.')
        self.assertEqual(1, len(registry.calls))
        self.assertFalse(registry.calls[0][2]['approved'])
        result_message = browser.sent[2]['message']
        self.assertEqual('tool_results', result_message['kind'])
        self.assertEqual('Synthetic mock observation.', result_message['content']['results'][0]['result']['evidence'])
        await app.turn('Continue the same session.')
        self.assertEqual('ready', state.data['status'])
        self.assertEqual(4, state.message_count)
        await app.close()
        self.assertTrue(browser.closed)

    async def test_correction_budget_stops_without_execution(self):
        root, config, state, registry, browser, app = self.fixture([final_response, 'bad one', 'bad two'])
        await app.initialize()
        with self.assertRaises(ProtocolError):
            await app.turn('Invalid response must stop safely.')
        self.assertEqual(2, len(state.data['retry_records']))
        self.assertEqual('blocked', state.data['status'])
        self.assertEqual([], registry.calls)

    async def test_twelfth_completed_correction_can_succeed(self):
        def completed_invalid(message):
            return (BEGIN + '\n{"request_id":' + json.dumps(message['request_id']) +
                    ',"completed_but_invalid":}\n' + END)
        responders = [final_response] + [completed_invalid] * 12 + [final_response]
        root, config, state, registry, browser, app = self.fixture(responders)
        config.max_corrections = 12
        await app.initialize()
        result = await app.turn('Use every allowed completed-response correction if needed.')
        self.assertEqual('final', result['response_type'])
        self.assertEqual(12, len(state.data['retry_records']))
        self.assertEqual(12, [item['message']['kind'] for item in browser.sent].count('correction'))
        self.assertEqual([], registry.calls)

    async def test_uncertain_submission_blocks_resend_without_counting(self):
        root, config, state, registry, browser, app = self.fixture(
            [final_response, SubmissionAmbiguousError('Delivery uncertain')])
        await app.initialize()
        with self.assertRaises(SubmissionAmbiguousError):
            await app.turn('Submission uncertainty.')
        self.assertEqual(1, state.message_count)
        self.assertEqual('submission_uncertain', state.data['status'])
        with self.assertRaises(RuntimeError):
            await app.turn('Do not blindly resend.')
        self.assertEqual(2, len(browser.sent))

    async def test_changed_guidance_cannot_send_under_stale_verified_hash(self):
        root, config, state, registry, browser, app = self.fixture([final_response, final_response])
        await app.initialize()
        path = app.prompts.guidance[0]
        path.write_text(path.read_text(encoding='utf-8') + '\nChanged after verification.\n', encoding='utf-8')
        with self.assertRaises((PolicyError, ValueError, RuntimeError)):
            await app.turn('Do not transmit under a stale trusted manifest.')
        self.assertEqual(1, len(browser.sent))

    async def test_tool_exception_remains_uncertain_instead_of_claiming_completed(self):
        root, config, state, registry, browser, app = self.fixture(
            [final_response, lambda msg: tool_response(msg, 'uncertain-write', 'synthetic.write'), final_response],
            lambda preview: 'once')
        async def partial_failure(name, arguments, context):
            registry.calls.append((name, arguments, context))
            raise OSError('Failure after possible side effect')
        registry.execute = partial_failure
        await app.initialize()
        await app.turn('Record uncertain side effects honestly.')
        self.assertEqual('uncertain', state.data['calls']['uncertain-write']['status'])

    async def test_uncertain_write_cannot_replay_through_renamed_call(self):
        root, config, state, registry, browser, app = self.fixture(
            [final_response, lambda msg: tool_response(msg, 'first-write', 'synthetic.write'),
             lambda msg: tool_response(msg, 'renamed-write', 'synthetic.write'), final_response],
            lambda preview: 'once')
        async def partial_failure(name, arguments, context):
            registry.calls.append((name, arguments, context))
            raise OSError('Failure after possible side effect')
        registry.execute = partial_failure
        await app.initialize()
        await app.turn('Do not replay uncertain side effects under a new ID.')
        self.assertEqual(1, len(registry.calls))
        self.assertEqual('uncertain', state.data['calls']['first-write']['status'])
        self.assertNotIn('renamed-write', state.data['calls'])
        self.assertEqual('correction', browser.sent[-1]['message']['kind'])

    async def test_verified_failed_method_allows_materially_different_approved_recovery(self):
        root, config, state, registry, browser, app = self.fixture(
            [final_response, lambda msg: tool_response(msg, 'failed-first', 'synthetic.write', {'path':'first.txt'}),
             lambda msg: tool_response(msg, 'different-recovery', 'synthetic.write', {'path':'second.txt'}),
             final_response], lambda preview: 'once')
        async def execute(name, arguments, context):
            registry.calls.append((name, copy.deepcopy(arguments), dict(context)))
            if arguments['path'] == 'first.txt':
                return {'ok':False, 'result':{'status':'failed', 'side_effects_uncertain':False},
                        'error':{'code':'operation_failed', 'message':'Verified no declared effect.'}}
            return {'ok':True, 'result':{'evidence':'Different recovery completed.'}}
        registry.execute = execute
        await app.initialize()
        result = await app.turn('Recover continuously with a different safe method.')
        self.assertEqual('Verified answer.', result['user_response'])
        self.assertEqual(['first.txt', 'second.txt'], [item[1]['path'] for item in registry.calls])
        self.assertEqual('completed', state.data['calls']['failed-first']['status'])

    async def test_alias_write_blocked_while_read_only_inspection_remains_available(self):
        root, config, state, registry, browser, app = self.fixture(
            [final_response, lambda msg: tool_response(msg, 'first-write', 'synthetic.write'),
             lambda msg: tool_response(msg, 'aliased-write', 'synthetic.write', {'path': './synthetic.txt'}),
             lambda msg: tool_response(msg, 'safe-inspection', 'synthetic.read'), final_response],
            lambda preview: 'once')
        async def observed_execute(name, arguments, context):
            registry.calls.append((name, copy.deepcopy(arguments), dict(context)))
            if name == 'synthetic.write':
                raise OSError('Possible partial write')
            return {'ok': True, 'result': {'evidence': 'Read-only inspection completed.'}}
        registry.execute = observed_execute
        await app.initialize()
        await app.turn('Inspect before any further state-changing step.')
        self.assertEqual(['synthetic.write', 'synthetic.read'], [call[0] for call in registry.calls])
        self.assertNotIn('aliased-write', state.data['calls'])
        self.assertEqual('uncertain', state.data['calls']['first-write']['status'])
        self.assertIn('only inspection is allowed', state.data['retry_records'][0]['errors'][0])

    async def test_approved_attachment_hash_and_actual_upload_are_bound(self):
        previews = []
        def approve(preview):
            previews.append(preview)
            return 'once'
        root, config, state, registry, browser, app = self.fixture([final_response, final_response], approve)
        path = root / 'workspace' / 'approved.txt'
        path.write_text('Synthetic approved bytes.', encoding='utf-8')
        expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        await app.initialize()
        await app.turn('Attach the reviewed synthetic document.', attachments=[path])
        record = previews[0]['complete_pending_plan']['files'][0]
        self.assertEqual(str(path), record['path'])
        self.assertEqual(expected_hash, record['sha256'])
        self.assertEqual(path.stat().st_size, record['size'])
        upload = next(item for item in browser.sent[-1]['attachments'] if item.name == path.name)
        self.assertEqual(expected_hash, hashlib.sha256(upload.read_bytes()).hexdigest())
        self.assertIn('approved_uploads', str(upload))
        uploaded = [item for item in state.data['attachments'] if item['path'] == str(path)]
        self.assertEqual(1, len(uploaded))
        self.assertEqual(expected_hash, uploaded[0]['sha256'])

    async def test_upload_snapshot_keeps_reviewed_bytes_when_source_changes_during_exchange(self):
        root, config, state, registry, browser, app = self.fixture([final_response, final_response], lambda preview: 'once')
        path = root / 'workspace' / 'immutable.txt'
        path.write_text('Reviewed synthetic bytes.', encoding='utf-8')
        await app.initialize()
        normal_exchange = browser.exchange
        async def exchange_after_source_change(text, request_id, attachments=(), on_submitted=None):
            path.write_text('Changed after upload staging.', encoding='utf-8')
            return await normal_exchange(text, request_id, attachments, on_submitted)
        browser.exchange = exchange_after_source_change
        await app.turn('Upload the reviewed immutable snapshot.', attachments=[path])
        self.assertEqual('Reviewed synthetic bytes.', browser.sent[-1]['attachment_text'][path.name])
        self.assertEqual('Changed after upload staging.', path.read_text(encoding='utf-8'))

    async def test_user_attachment_is_hashed_with_bounded_streaming_reads(self):
        root, config, state, registry, browser, app = self.fixture([final_response, final_response], lambda preview: 'once')
        path = root / 'workspace' / 'streamed.txt'
        path.write_text('Synthetic bounded streaming payload.', encoding='utf-8')
        await app.initialize()
        original_read_bytes = Path.read_bytes
        def refuse_unbounded_user_read(candidate):
            if candidate == path:
                raise AssertionError('Arbitrary user attachments must not use unbounded read_bytes hashing.')
            return original_read_bytes(candidate)
        with patch.object(Path, 'read_bytes', refuse_unbounded_user_read):
            await app.turn('Use bounded hashing of approved document.', attachments=[path])
        self.assertEqual(2, state.message_count)

    async def test_attachment_changed_during_approval_cannot_upload(self):
        root, config, state, registry, browser, app = self.fixture([final_response, final_response])
        path = root / 'workspace' / 'changed.txt'
        path.write_text('Original synthetic bytes.', encoding='utf-8')
        def change_then_approve(preview):
            path.write_text('Different bytes after review.', encoding='utf-8')
            return 'once'
        app.approvals.decide = change_then_approve
        await app.initialize()
        with self.assertRaises(PolicyError):
            await app.turn('Do not upload changed reviewed content.', attachments=[path])
        self.assertEqual(1, len(browser.sent))
        self.assertEqual(1, state.message_count)
        self.assertIsNone(state.data['pending_submission'])

    async def test_directory_unsupported_oversized_and_secret_text_attachments_rejected_before_approval(self):
        previews = []
        root, config, state, registry, browser, app = self.fixture([final_response], lambda preview: previews.append(preview) or 'once')
        await app.initialize()
        directory = root / 'workspace' / 'directory.txt'
        directory.mkdir()
        unsupported = root / 'workspace' / 'unsupported.exe'
        unsupported.write_text('Synthetic text only.', encoding='utf-8')
        oversized = root / 'workspace' / 'oversized.txt'
        oversized.write_text('x' * 65, encoding='utf-8')
        secret = root / 'workspace' / 'secret.txt'
        secret.write_text('password=synthetic-never-upload', encoding='utf-8')
        config.max_attachment_bytes = 64
        for path in (directory, unsupported, oversized, secret):
            with self.subTest(path=path.name), self.assertRaises(PolicyError):
                await app.turn('Reject unsafe attachment candidate.', attachments=[path])
        self.assertEqual([], previews)
        self.assertEqual(1, len(browser.sent))
        self.assertEqual(1, state.message_count)

    async def test_capture_timeout_after_submission_preserves_count_outbound_and_findings_upload(self):
        def interrupted(message):
            raise CaptureTimeoutError('Generation interrupted after proven submission.')
        root, config, state, registry, browser, app = self.fixture([final_response, interrupted])
        await app.initialize()
        # Simulate earlier independently confirmed messages so this committed send is boundary 10.
        state.data['message_count'] = 9
        state.save()
        with self.assertRaises(CaptureTimeoutError):
            await app.turn('Preserve committed message evidence on interruption.')
        self.assertEqual(10, state.message_count)
        self.assertIsNone(state.data['pending_submission'])
        self.assertEqual('capture_failed', state.data['status'])
        outbound = [item for item in state.data['messages'] if item['role'] == 'copilot_outbound']
        self.assertEqual(10, outbound[-1]['ordinal'])
        self.assertIn('Preserve committed message evidence', outbound[-1]['content'])
        self.assertEqual([10], [entry['ordinal'] for entry in state.data['findings_sync']])
        persisted = json.loads(state.path.read_text(encoding='utf-8'))
        self.assertEqual(10, persisted['message_count'])
        self.assertEqual('capture_failed', persisted['status'])
        self.assertEqual([], registry.calls)
        self.assertEqual([], state.data['retry_records'])
        self.assertEqual(['initialize', 'user_turn'], [item['message']['kind'] for item in browser.sent])

    async def test_completed_malformed_reply_uses_plain_error_and_correction(self):
        root, config, state, registry, browser, app = self.fixture(
            [final_response, BEGIN + '\n{"genuinely":"completed",}\n' + END, final_response])
        lines = []
        app.feedback.sink = lines.append
        await app.initialize()
        result = await app.turn('Exercise a genuine completed-format correction.')
        self.assertEqual('final', result['response_type'])
        error_lines = [line for line in lines if '[Error]' in line]
        self.assertEqual(1, len(error_lines))
        self.assertIn('response format was invalid', error_lines[0])
        self.assertIn('No local action ran', error_lines[0])
        self.assertNotIn('missing_envelope', error_lines[0])
        self.assertEqual('correction', browser.sent[-1]['message']['kind'])
        self.assertEqual('invalid_json', state.data['retry_records'][0]['reason'])

    async def test_final_after_uncertain_effect_does_not_mark_session_ready(self):
        root, config, state, registry, browser, app = self.fixture(
            [final_response, lambda msg: tool_response(msg, 'uncertain-effect', 'synthetic.write'), final_response],
            lambda preview: 'once')
        async def uncertain_execute(name, arguments, context):
            raise OSError('Possible state change requires reconciliation.')
        registry.execute = uncertain_execute
        await app.initialize()
        await app.turn('Do not mark unresolved side effects ready.')
        self.assertEqual('uncertain', state.data['calls']['uncertain-effect']['status'])
        self.assertNotEqual('ready', state.data['status'])

    async def test_invalid_responses_each_capture_one_correlated_diagnostic(self):
        root, config, state, registry, browser, app = self.fixture(
            [final_response, 'first malformed response', 'second malformed response', final_response])
        config.max_corrections = 2
        captured = []
        async def diagnostics(reason):
            path = root / ('synthetic-ui-evidence-' + str(len(captured) + 1) + '.json')
            path.write_text(json.dumps({'synthetic': True, 'reason': reason}), encoding='utf-8')
            captured.append((reason, path))
            return path
        browser.diagnostics = diagnostics
        await app.initialize()
        result = await app.turn('Recover safely with correlated local UI diagnostics.')
        self.assertEqual('final', result['response_type'])
        self.assertEqual(['protocol_missing_envelope', 'protocol_missing_envelope'], [item[0] for item in captured])
        events = [json.loads(line) for line in state.log.path.read_text(encoding='utf-8').splitlines()]
        evidence = [item for item in events if item['event'] == 'protocol_ui_evidence']
        self.assertEqual(2, len(evidence))
        from copilot_agent.web_privacy import audit_evidence
        for event, (_, artifact), index in zip(evidence, captured, (1, 2)):
            self.assertTrue(artifact.is_file())
            details = {'request_id': browser.sent[index]['message']['request_id'], 'artifact': str(artifact)}
            self.assertEqual(event['evidence'], audit_evidence(details))
            self.assertNotIn('artifact', event)
        self.assertEqual([browser.sent[index]['message']['request_id'] for index in (1, 2)],
                         [item['request_id'] for item in evidence])
        self.assertEqual(['initialize', 'user_turn', 'correction', 'correction'],
                         [item['message']['kind'] for item in browser.sent])
        self.assertEqual([], registry.calls)

    async def test_diagnostic_failure_is_recorded_without_suppressing_bounded_recovery(self):
        root, config, state, registry, browser, app = self.fixture([final_response, 'malformed response', final_response])
        captured = []
        async def diagnostics(reason):
            captured.append(reason)
            raise OSError('Synthetic diagnostic capture unavailable.')
        browser.diagnostics = diagnostics
        await app.initialize()
        result = await app.turn('Continue bounded correction if diagnostic capture fails.')
        self.assertEqual('final', result['response_type'])
        self.assertEqual(['protocol_missing_envelope'], captured)
        self.assertEqual('correction', browser.sent[-1]['message']['kind'])
        self.assertEqual(3, state.message_count)
        self.assertEqual(1, len(state.data['retry_records']))
        self.assertEqual('ready', state.data['status'])
        events = [json.loads(line) for line in state.log.path.read_text(encoding='utf-8').splitlines()]
        unavailable = [item for item in events if item['event'] == 'protocol_ui_evidence_unavailable']
        self.assertEqual(1, len(unavailable))
        self.assertEqual(browser.sent[1]['message']['request_id'], unavailable[0]['request_id'])
        from copilot_agent.web_privacy import audit_evidence
        details = {'request_id': browser.sent[1]['message']['request_id'],
                   'error': 'Synthetic diagnostic capture unavailable.'}
        self.assertEqual(unavailable[0]['evidence'], audit_evidence(details))
        self.assertNotIn('error', unavailable[0])
        self.assertNotIn('Synthetic diagnostic capture unavailable', json.dumps(unavailable[0]))
        self.assertEqual([], registry.calls)
