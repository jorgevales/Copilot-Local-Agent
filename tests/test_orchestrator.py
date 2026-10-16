"""Mock transport/registry tests; no browser, network or deletion."""
import copy
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

from copilot_agent.browser import CaptureTimeoutError, SubmissionAmbiguousError
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.policy import PolicyError
from copilot_agent.protocol import BEGIN, END, ProtocolError, correction_message
from copilot_agent.state import SessionState, recoverable_capture_request_id
from copilot_agent.tools import ToolRegistry
from copilot_agent.web_privacy import private_session_snapshot
from tests.test_protocol_state import encoded, envelope, make_fixture


class MockBrowser:
    def __init__(self, responders):
        self.responders = list(responders)
        self.sent = []
        self.closed = False

    async def exchange(self, text, request_id, attachments=(), on_submitted=None):
        message = json.loads(text)
        wire_message = message
        attachment_text = {p.name: p.read_text(encoding='utf-8') for p in attachments}
        # Model Copilot reading the complete attached response before replying.
        if message.get('result_attachment_manifest'):
            parts = []
            for entry in message['result_attachment_manifest']:
                raw = attachment_text[entry['name']]
                if hashlib.sha256(raw.encode('utf-8')).hexdigest() != entry['sha256']:
                    raise AssertionError('Result attachment changed in transit')
                part = json.loads(raw)
                if part['request_id'] != request_id or part['session_id'] != message['session_id']:
                    raise AssertionError('Result attachment belongs to another exchange')
                parts.append(part)
            parts.sort(key=lambda part: part['part'])
            if [part['part'] for part in parts] != list(range(1, len(parts) + 1)):
                raise AssertionError('Missing result attachment part')
            if any(part['part_count'] != len(parts) for part in parts):
                raise AssertionError('Incomplete result attachment batch')
            content = (parts[0]['content'] if 'content' in parts[0] else
                       json.loads(''.join(part['content_segment'] for part in parts)))
            message = {**parts[0]['response_metadata'], 'content': content}
        record = {'message': message, 'wire_message': wire_message, 'wire_text': text,
                  'attachments': list(attachments), 'attachment_text': attachment_text}
        self.sent.append(record)
        response = self.responders.pop(0)
        if isinstance(response, Exception):
            raise response
        on_submitted()
        result = response(message) if callable(response) else response
        return result if isinstance(result, str) else encoded(result)

    async def close(self, *, preserve_browser_process=False):
        self.closed = True


class PreloadingBrowser(MockBrowser):
    def __init__(self, responders):
        super().__init__(responders)
        self.preloads = []
        self.attachment_preloads = []

    async def preload_exchange(self, text, request_id, attachments=()):
        self.preloads.append({'text': text, 'request_id': request_id,
                              'attachments': list(attachments)})

    async def preload_attachments(self, paths):
        paths = list(paths)
        self.attachment_preloads.append(paths)
        return {'status': 'prepared', 'count': len(paths),
                'names': [path.name for path in paths]}


def final_response(message, **changes):
    return envelope(message['session_id'], message['request_id'], **changes)


def tool_response(message, call_id='read-one', name='synthetic.read', arguments=None):
    call = {'call_id': call_id, 'name': name, 'version': '1.0',
            'arguments': arguments or {'path': 'synthetic.txt'}, 'expected_result': 'Observe synthetic output.'}
    return final_response(message, response_type='tool_request', tools_required=True, tool_requests=[call],
                          continuation_state='continue', completion_status='in_progress',
                          approval_required=name != 'synthetic.read')


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_s_path_display_helper_is_available_to_tool_preflight(self):
        root, config, state, registry, browser, app = self.fixture([final_response])
        mapped_share = root / 'mapped-share'
        mapped_share.mkdir()
        with patch('copilot_agent.policy.mapped_s_drive_root', return_value=mapped_share):
            display = app._display_s_path(mapped_share / 'proof-output')
            fallback = app._display_s_path(root / 'workspace' / 'proof-output')
        self.assertEqual('S:/proof-output', display.replace('\\', '/'))
        self.assertEqual(app.prompts.storage_paths['s_path'], fallback)

    async def test_visible_public_progress_is_printed_after_redaction(self):
        output = []
        root, config, state, registry, browser, app = self.fixture([final_response])
        app.feedback.sink = output.append
        app._live_feedback({'type': 'progress', 'request_id': 'progress-test',
                            'message': 'Building files. password=synthetic-value'})
        self.assertIn('Building files.', output[0])
        self.assertIn('[REDACTED]', output[0])
        self.assertNotIn('synthetic-value', output[0])

    async def test_package_review_prints_checked_items_failures_and_future_options(self):
        output = []
        _, _, _, _, _, app = self.fixture([final_response])
        app.feedback.sink = output.append
        review = {"status": "failed", "summary": "Two issues need attention; ZIP was reviewed but not run.",
                  "checks": [{"item": "File list matches", "status": "passed"},
                             {"item": "Workflow outputs", "status": "failed",
                              "detail": "The report files sit inside an allowed output folder."}],
                  "failures": [{"item": "Workflow outputs",
                                "detail": "The report files sit inside an allowed output folder.",
                                "next_step": "Allow output files inside declared folders."}],
                  "future_review_options": ["A later update can make a nonessential format preference a warning."]}

        app._emit_tool_result("automation.inspect", {"ok": False,
                                 "tool": "automation.inspect",
                                 "result": {"status": "failed", "review": review},
                                 "error": {"message": review["summary"]}})

        rendered = "\n".join(output)
        self.assertIn("What was checked", rendered)
        self.assertIn("What failed", rendered)
        self.assertIn("File list matches", rendered)
        self.assertIn("Workflow outputs", rendered)
        self.assertIn("Future review setting", rendered)
        self.assertIn("nonessential format preference", rendered)

    async def test_package_run_failure_is_shown_and_automatically_actionable(self):
        output = []
        root, _, state, _, _, app = self.fixture([final_response])
        app.feedback.sink = output.append
        state_path = root / 'workspace' / 'package-run' / 'state.json'
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            'stages': {'generate_data': {'status': 'failed', 'result': {
                'error': 'Dunder reflection is unavailable', 'side_effects_uncertain': False}}},
            'status': 'failed', 'run_id': 'run-local-package', 'archive_sha256': 'a' * 64,
            'validation': {'ok': False, 'errors': ['Missing expected output: reports/route_day.csv']}
        }), encoding='utf-8')
        state.data['package_run_failure_call_id'] = 'run-local-package'
        state.data['package_run_failure_state_path'] = str(state_path)
        state.data['package_run_failure_archive_sha256'] = 'a' * 64
        failed_run = {'call_id': 'run-local-package', 'tool': 'automation.run', 'ok': True,
                      'result': {'status': 'failed', 'state_path': str(state_path),
                                 'summary': 'Package run failed: no package steps completed. Failed step(s): generate_data. 1 expected output check did not pass.',
                                 'failed_stages': ['generate_data'],
                                 'validation': {'ok': False,
                                                'errors': ['Missing expected output: reports/route_day.csv']}}}

        repair = app._package_run_repair_instruction([failed_run])
        app._emit_tool_result('automation.run', failed_run)

        self.assertIn('Failed step generate_data', repair)
        self.assertIn('Dunder reflection is unavailable', repair)
        self.assertIn('fresh clickable ZIP', repair)
        self.assertIn('local orchestrator', repair)
        self.assertIn('do not ask the user to inspect', repair.lower())
        restored = Orchestrator._latest_failed_package_run({
            'run-local-package': {'request': {'name': 'automation.run'}, 'result': failed_run}
        })
        self.assertEqual('run-local-package', restored['call_id'])
        self.assertIn('Dunder reflection is unavailable',
                      app._package_run_repair_instruction([restored]))
        checkpoint_failure = app._recovered_package_run_failure()
        self.assertEqual('failed', checkpoint_failure['result']['status'])
        self.assertIn('Dunder reflection is unavailable',
                      app._package_run_repair_instruction([checkpoint_failure]))
        self.assertIsNone(Orchestrator._latest_failed_package_run({
            'run-local-package': {'request': {'name': 'automation.run'}, 'result': failed_run},
            'later-denial': {'request': {'name': 'automation.run'},
                             'result': {'ok': False, 'error': {'code': 'approval_denied'}}},
        }))
        rendered = '\n'.join(output)
        self.assertIn('Steps that failed', rendered)
        self.assertIn('Run summary', rendered)
        self.assertIn('no package steps completed', rendered)
        self.assertIn('Generate data', rendered)
        self.assertIn('Dunder reflection is unavailable', rendered)
        self.assertIn('Expected files still missing or unchecked', rendered)

    async def test_wrong_package_path_feedback_names_attempt_and_approved_folder(self):
        _, _, _, _, _, app = self.fixture([final_response])
        attempted = 'C:/proof/workspace/packages/hash/outputs/reports/route_day.csv'
        approved = 'C:/proof/workspace/runs/fresh/outputs'
        run = {'tool': 'automation.run', 'ok': True, 'result': {
            'status': 'failed', 'output_root': approved, 'failed_stages': ['generate_data'],
            'stage_results': [{'stage_id': 'generate_data', 'status': 'failed',
                               'error': 'File write is outside the approved create/modify scope: ' + attempted,
                               'side_effects_uncertain': False}],
            'validation': {'ok': False, 'errors': ['Missing expected output: reports/route_day.csv']}}}

        feedback = app._package_run_repair_instruction([run])

        self.assertIn(attempted, feedback)
        self.assertIn(approved, feedback)
        self.assertIn('final stage argument (`sys.argv[-1]`)', feedback)
        self.assertIn('Do not infer the output path from the working directory', feedback)
        self.assertIn('Do not', feedback)

    async def test_restarted_package_repair_recovers_approved_output_root(self):
        root, _, state, _, _, app = self.fixture([final_response])
        run_dir = root / 'workspace' / 'runs' / 'saved-run'
        run_dir.mkdir(parents=True)
        state_path = run_dir / 'state.json'
        attempted = str(root / 'workspace' / 'packages' / 'wrong' / 'outputs' / 'report.csv')
        state_path.write_text(json.dumps({
            'status': 'failed', 'run_id': 'saved-run', 'archive_sha256': 'a' * 64,
            'stages': {'generate': {'status': 'failed', 'result': {
                'error': 'File write is outside the approved create/modify scope: ' + attempted,
                'side_effects_uncertain': False}}},
            'validation': {'ok': False, 'errors': ['Missing report.csv']}}), encoding='utf-8')
        state.data['package_run_failure_state_path'] = str(state_path)
        state.data['package_run_failure_archive_sha256'] = 'a' * 64

        restored = app._recovered_package_run_failure()
        repair = app._package_run_repair_instruction([restored])

        self.assertEqual(str(run_dir / 'outputs'), restored['result']['output_root'])
        self.assertIn(attempted, repair)
        self.assertIn(str(run_dir / 'outputs'), repair)

    async def test_cancellation_never_becomes_package_repair(self):
        root, _, state, _, _, app = self.fixture([final_response])
        cancelled = {'tool': 'automation.run', 'ok': True,
                     'result': {'status': 'cancelled', 'run_id': 'retained-checkpoint',
                                'failed_stages': [], 'summary': 'Cancelled at a retained checkpoint.'}}
        self.assertIsNone(app._package_run_repair_instruction([cancelled]))
        self.assertIsNone(Orchestrator._latest_failed_package_run({
            'cancelled': {'request': {'name': 'automation.run'}, 'result': cancelled}}))
        checkpoint = root / 'workspace' / 'cancelled-run.json'
        checkpoint.write_text(json.dumps({'status': 'cancelled', 'run_id': 'retained-checkpoint',
                                          'archive_sha256': 'a' * 64}), encoding='utf-8')
        state.data['package_run_failure_state_path'] = str(checkpoint)
        state.data['package_run_failure_archive_sha256'] = 'a' * 64
        state.save()
        self.assertIsNone(app._recovered_package_run_failure())
        self.assertEqual('retained-checkpoint', json.loads(checkpoint.read_text(encoding='utf-8'))['run_id'])
        for status, detail in (('failed', 'stage execution failed'),
                               ('partial', 'output validation failed'),
                               ('failed', 'hash verification failed'),
                               ('partial', 'quality check failed')):
            with self.subTest(detail=detail):
                failure = {'tool': 'automation.run', 'ok': True, 'result': {
                    'status': status, 'failed_stages': ['stage-one'],
                    'stage_results': [{'stage_id': 'stage-one', 'status': 'failed', 'error': detail}],
                    'validation': {'ok': False, 'errors': [detail]}}}
                self.assertIn(detail, app._package_run_repair_instruction([failure]))

    async def test_recovered_package_turn_keeps_package_delivery_guard(self):
        root, _, state, _, _, app = self.fixture([final_response])
        state.data['task_routing'] = {'route': 'direct', 'score': 3.25}
        state.data['package_run_failure_call_id'] = 'failed-package-run'

        recovered = app._route_for_turn({'route': 'direct', 'score': 1.0}, ('response', 'request-id'))
        self.assertEqual('package', recovered['route'])
        self.assertTrue(recovered['recovered_package_workflow'])

        fresh = app._route_for_turn({'route': 'direct', 'score': 1.0}, None)
        self.assertEqual('direct', fresh['route'])
        self.assertNotIn('package_run_failure_call_id', state.data)

    async def test_not_started_download_sends_a_specific_delivery_repair(self):
        instruction = Orchestrator._download_recovery_instruction([
            {'ok': False, 'tool': 'copilot.download', 'result': {'status': 'not_started'},
             'error': {'code': 'link_unavailable', 'message': 'No unique current link was found.'}}
        ])
        self.assertIn('not a user denial', instruction)
        self.assertIn('same response', instruction)
        self.assertIn('exact visible link label', instruction)
        self.assertIn('automation.inspect', instruction)
        self.assertIsNone(Orchestrator._download_recovery_instruction([
            {'ok': True, 'tool': 'copilot.download', 'result': {'status': 'downloaded'}}
        ]))

    async def test_missing_download_label_correction_uses_the_real_current_anchor(self):
        correction = json.loads(correction_message(ProtocolError(
            'unsafe_tool_arguments', ['$.tool_requests[0].arguments.link_text: required property missing'])))
        self.assertIn('exact visible label', correction['instruction'])
        self.assertIn('same assistant response', correction['instruction'])
        self.assertIn('No download ran', correction['instruction'])

    async def test_json_syntax_correction_explains_string_escaping(self):
        correction = json.loads(correction_message(ProtocolError(
            'invalid_json', ["Expecting ',' delimiter: line 1 column 42 (char 41)"])))
        self.assertIn('reported line/character location', correction['instruction'])
        self.assertIn('ordinary string content', correction['instruction'])
        self.assertIn('backslashes', correction['instruction'])
        self.assertIn('no local action ran', correction['instruction'])

    async def test_failed_package_review_is_sent_to_copilot_as_one_repair_request(self):
        def inspect_request(message):
            response = tool_response(message, name='automation.inspect',
                                     arguments={'path': str(Path.cwd() / 'synthetic.zip')})
            response['approval_required'] = False
            return response

        root, config, state, _ = make_fixture('package-repair-feedback-')
        registry = ToolRegistry()
        browser = MockBrowser([final_response, inspect_request, *([final_response] * 5)])
        app = Orchestrator(config, browser, registry, state, display=lambda text: None)
        review = {"status": "failed", "summary": "Two issues need attention; the ZIP was reviewed but not run.",
                  "failures": [
                      {"item": "Python script syntax", "detail": "scripts/build.py line 18 has an unfinished string.",
                       "next_step": "Fix the broken quoted text on line 18 and compile the script."},
                      {"item": "Declared output files", "detail": "Two stages claim the same report file.",
                       "next_step": "Give each stage a distinct output file."}]}
        failed = {"ok": False, "tool": "automation.inspect",
                  "result": {"status": "failed", "review": review},
                  "error": {"code": "package_review_failed", "message": review["summary"]}}
        with patch.object(registry, 'execute', new=AsyncMock(return_value=failed)):
            await app.initialize()
            await app.turn('Build the synthetic application package and review it locally.')

        followups = [item['message'] for item in browser.sent if item['message']['kind'] == 'tool_results']
        self.assertTrue(followups, [item['message']['kind'] for item in browser.sent])
        followup = followups[0]
        instruction = followup['content']['instruction']
        self.assertIn('fix every finding below together', instruction)
        self.assertIn('scripts/build.py line 18', instruction)
        self.assertIn('Give each stage a distinct output file.', instruction)
        self.assertIn('Do not ask the user to inspect files', instruction)
        self.assertIn('No local package stages have run.', instruction)
        self.assertIn("Copilot's cloud sandbox", instruction)
        self.assertIn('Cloud tests do not replace a user-requested live test', instruction)

    async def test_first_copilot_zip_is_reviewed_immediately_and_all_failures_return_for_one_repair(self):
        from tests.test_automation_packages import package_bytes, write_python_package

        root, config, state, _ = make_fixture('automatic-package-review-')
        workspace = root / 'workspace'
        first = workspace / 'package.zip'
        revision_dir = workspace / 'revision-2'
        revision_dir.mkdir()
        second = revision_dir / 'package.zip'

        with zipfile.ZipFile(io.BytesIO(package_bytes())) as source:
            payloads = {name: source.read(name) for name in source.namelist()}
        payloads['main.py'] = b"print('unfinished\n"
        with zipfile.ZipFile(first, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, payload in payloads.items():
                archive.writestr(name, payload)
        write_python_package(second, "import sys\nfrom pathlib import Path\n"
                             "Path(sys.argv[-1], 'result.txt').write_text('verified')\n")

        def download_request(message, label):
            return tool_response(message, call_id='download-' + label,
                                 name='copilot.download',
                                 arguments={'expected_name': 'package.zip',
                                            'link_text': 'Download package.zip ' + label})

        def repair_after_first_review(message):
            self.assertEqual('tool_results', message['kind'])
            inspections = [item for item in message['content']['results']
                           if item.get('tool') == 'automation.inspect']
            self.assertEqual(1, len(inspections), message['content']['results'])
            review = inspections[0]['result']['review']
            self.assertEqual('failed', review['status'])
            self.assertEqual(2, len(review['failures']))
            self.assertIn('File list and contents match',
                          {item['item'] for item in review['failures']})
            self.assertIn('Python step files can be read',
                          {item['item'] for item in review['failures']})
            instruction = message['content']['instruction']
            self.assertIn('fix every finding below together', instruction)
            self.assertIn("Copilot's cloud sandbox", instruction)
            self.assertIn('Cloud tests do not replace a user-requested live test', instruction)
            self.assertIn('rebuilt ZIP download link', instruction)
            return download_request(message, 'revision-2')

        def finish_after_second_review(message):
            self.assertEqual('tool_results', message['kind'])
            inspections = [item for item in message['content']['results']
                           if item.get('tool') == 'automation.inspect']
            self.assertEqual(1, len(inspections), message['content']['results'])
            self.assertTrue(inspections[0]['ok'])
            self.assertEqual('passed', inspections[0]['result']['review']['status'])
            runs = [item for item in message['content']['results'] if item.get('tool') == 'automation.run']
            self.assertEqual(1, len(runs))
            self.assertEqual('completed', runs[0]['result']['status'])
            self.assertTrue(runs[0]['result']['validation']['ok'])
            return final_response(message, user_response='The revised package passed the local review.')

        browser = MockBrowser([
            final_response,
            lambda message: download_request(message, 'revision-1'),
            repair_after_first_review,
            finish_after_second_review,
        ])
        registry = ToolRegistry()
        approvals = []
        app = Orchestrator(config, browser, registry, state,
                           approval_decider=lambda preview: approvals.append(preview) or 'once',
                           display=lambda text: None)

        class DownloadStub:
            async def prepare(self, arguments, request_id):
                return {'expected_name': arguments['expected_name'], 'request_id': request_id}

        app.download_service = DownloadStub()
        original_execute = registry.execute
        download_paths = [first, second]

        async def execute(name, arguments, context):
            if name == 'copilot.download':
                path = download_paths.pop(0)
                return {'ok': True, 'tool': name,
                        'result': {'status': 'downloaded', 'path': str(path),
                                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                   'size': path.stat().st_size}}
            return await original_execute(name, arguments, context)

        with patch.object(registry, 'execute', new=AsyncMock(side_effect=execute)):
            await app.initialize()
            result = await app.turn(
                'Build a multi-file software project with tests, dependencies, checkpoints, recovery and validation. '
                'Deliver the complete package.zip.')

        self.assertEqual('final', result['response_type'])
        reviews = [call for call in state.data['calls'].values()
                   if call.get('request', {}).get('name') == 'automation.inspect']
        self.assertEqual(2, len(reviews))
        self.assertEqual(3, len(approvals))
        self.assertTrue(all(preview['complete_pending_plan']['tool_requests'][0]['name'] == 'copilot.download'
                            for preview in approvals))

    async def test_independent_readonly_file_checks_run_in_parallel_and_record_method(self):
        root, config, state, _ = make_fixture('parallel-readonly-')
        gate = threading.Lock()
        active = 0
        maximum = 0

        class ParallelRegistry:
            def definitions(self):
                return []

            def definition(self, name):
                return {'approval_policy': 'read_only', 'timeout': 2}

            def validate_call(self, name, arguments, context):
                return None

            async def execute(self, name, arguments, context):
                nonlocal active, maximum
                with gate:
                    active += 1
                    maximum = max(maximum, active)
                await asyncio.sleep(0.05)
                with gate:
                    active -= 1
                return {'ok': True, 'tool': name, 'result': {'path': arguments['path']}}

        calls = [{'call_id': f'parallel-{index}', 'name': name, 'version': '1.0',
                  'arguments': {'path': str(root / 'workspace' / f'{index}.txt')}}
                 for index, name in enumerate(('files.exists', 'files.metadata', 'files.hash'))]
        app = Orchestrator(config, MockBrowser([]), ParallelRegistry(), state, display=lambda text: None)
        outcomes = await app._parallel_readonly_group(calls, 'request-parallel')
        self.assertEqual(3, len(outcomes))
        self.assertGreater(maximum, 1)
        self.assertTrue(all(result['result']['execution_method'] == 'parallel_thread'
                            for result in outcomes.values()))
        self.assertTrue(all(state.data['calls'][call['call_id']]['status'] == 'completed'
                            for call in calls))

    async def test_effectful_calls_are_never_sent_to_parallel_executor(self):
        root, config, state, registry = make_fixture('no-parallel-effects-')
        app = Orchestrator(config, MockBrowser([]), registry, state, display=lambda text: None)
        calls = [{'call_id': 'write-a', 'name': 'files.create', 'version': '1.0',
                  'arguments': {'path': str(root / 'workspace' / 'a.txt')}},
                 {'call_id': 'write-b', 'name': 'files.create', 'version': '1.0',
                  'arguments': {'path': str(root / 'workspace' / 'b.txt')}}]
        self.assertIsNone(await app._parallel_readonly_group(calls, 'request-write'))
        self.assertEqual({}, state.data['calls'])

    async def test_steering_supersedes_unexecuted_plan_and_preserves_order(self):
        root, config, state, registry = make_fixture('orchestrator-steering-')
        queued = []
        poll_count = []

        def poll():
            poll_count.append(len(queued))
            items = list(queued)
            queued.clear()
            return items

        def confirm_steering(message):
            self.assertEqual('steering', message['kind'])
            self.assertEqual(1, len(message['content']['steering_messages']))
            self.assertIn(message['content']['steering_messages'][0]['text'],
                          {'Correction one.', 'Additional detail two.'})
            return final_response(message)

        class SteeringBrowser(MockBrowser):
            async def exchange(self, text, request_id, attachments=(), on_submitted=None):
                result = await super().exchange(text, request_id, attachments, on_submitted)
                if self.sent[-1]['message']['kind'] == 'user_turn':
                    queued.extend([
                        {'message_id': 'steer-1', 'sequence': 1, 'text': 'Correction one.', 'attachments': []},
                        {'message_id': 'steer-2', 'sequence': 2, 'text': 'Additional detail two.', 'attachments': []},
                    ])
                return result

        browser = SteeringBrowser([final_response, tool_response, confirm_steering, confirm_steering])
        app = Orchestrator(config, browser, registry, state, display=lambda text: None,
                           steering_poll=poll)
        await app.initialize()
        response = await app.turn('Original active request.')
        self.assertEqual('complete', response['completion_status'])
        self.assertEqual([], registry.calls, 'The previous unexecuted tool plan must be discarded.')
        steering = [item for item in state.data['messages'] if item.get('source') == 'steering']
        self.assertEqual(['steer-1', 'steer-2'], [item['message_id'] for item in steering])
        self.assertTrue(all(item['incorporated'] for item in steering))
        self.assertIn(2, poll_count)

    async def test_steering_supersedes_recovered_proposal_before_any_tool_dispatch(self):
        _, config, state, registry = make_fixture('orchestrator-recovered-steering-')
        def updated(message):
            self.assertEqual('steering', message['kind'])
            self.assertEqual('New goal; leave the earlier record unchanged.', message['content']['steering_messages'][0]['text'])
            return final_response(message)
        browser = MockBrowser([updated])
        agent = Orchestrator(config, browser, registry, state, display=lambda _: None)
        agent.initialized = True
        agent._pending_steering_items.append({'message_id': 'new-goal', 'sequence': 0,
            'text': 'New goal; leave the earlier record unchanged.', 'attachments': []})
        old = tool_response({'session_id': state.session_id, 'request_id': 'old-proposal'})
        result = await agent.turn('Resume captured request', recovered_response=(encoded(old), 'old-proposal'))
        self.assertEqual('complete', result['completion_status'])
        self.assertEqual([], registry.calls)
        self.assertEqual(1, len(browser.sent))

    async def test_rapid_steering_keeps_each_full_attachment_allowance_separate(self):
        _, config, state, registry = make_fixture('orchestrator-steering-files-')
        first_files = [f'C:/staging/first-{index}.txt' for index in range(20)]
        second_files = [f'C:/staging/second-{index}.txt' for index in range(20)]
        queued = [
            {'message_id': 'files-1', 'sequence': 1, 'text': 'First file batch', 'attachments': first_files},
            {'message_id': 'files-2', 'sequence': 2, 'text': 'Second file batch', 'attachments': second_files},
        ]
        def poll():
            items = list(queued)
            queued.clear()
            return items

        app = Orchestrator(config, MockBrowser([]), registry, state, display=lambda text: None,
                           steering_poll=poll)
        from unittest.mock import AsyncMock
        app._prepare_user_attachments = AsyncMock(side_effect=lambda paths: list(paths))

        first = await app._take_steering('Original request')
        second = await app._take_steering('Original request')

        self.assertEqual(first_files, [str(path) for path in first['attachments']])
        self.assertEqual(second_files, [str(path) for path in second['attachments']])
        self.assertEqual(['files-1'], first['message_ids'])
        self.assertEqual(['files-2'], second['message_ids'])

    async def test_stale_run_steering_is_failed_and_its_uploads_are_released(self):
        _, config, state, registry = make_fixture('orchestrator-stale-steering-')
        released, events = [], []
        app = Orchestrator(config, MockBrowser([]), registry, state, display=lambda text: None,
                           steering_poll=lambda: [{'message_id':'stale-1','sequence':1,
                               'active_run_id':'old-run','text':'Use this stale file',
                               'attachments':['C:/private/stale.txt']}],
                           steering_complete=released.extend, event_sink=lambda *event: events.append(event))
        app._active_turn_run_id = 'current-run'

        self.assertIsNone(await app._take_steering('Current goal'))
        self.assertEqual(['stale-1'], released)
        self.assertEqual('failed', events[0][1]['status'])
        self.assertEqual([], [item for item in state.data['messages'] if item.get('source') == 'steering'])

    async def test_unavailable_steering_file_does_not_abort_original_goal_or_claim_review(self):
        _, config, state, registry = make_fixture('orchestrator-unavailable-steering-file-')
        events, released = [], []
        item = {'message_id':'missing-file', 'sequence':1, 'active_run_id':'run-1',
                'text':'Review this local evidence', 'attachments':['S:/offline/evidence.txt']}
        app = Orchestrator(config, MockBrowser([]), registry, state, display=lambda text: None,
                           steering_poll=lambda: [item], steering_complete=released.extend,
                           event_sink=lambda kind, payload: events.append((kind, payload)))
        async def unavailable(_paths):
            raise PolicyError('The S: file is unavailable')
        app._prepare_user_attachments = unavailable
        app._active_turn_run_id = 'run-1'

        result = await app._take_steering('Original goal')

        self.assertEqual([], result['attachments'])
        self.assertEqual('Review this local evidence', result['content']['steering_messages'][0]['text'])
        self.assertIn('could not be read or validated', result['content']['steering_messages'][0]['attachment_error'])
        saved = next(message for message in state.data['messages'] if message.get('source') == 'steering')
        self.assertEqual('failed', saved['attachment_status'])
        self.assertEqual(0, saved['attachment_count'])
        self.assertEqual(['missing-file'], released)
        self.assertNotIn('S:/offline/evidence.txt', json.dumps(events))

    async def test_tool_usage_has_no_round_count_limit(self):
        root, config, state, registry = make_fixture('unlimited-tool-rounds-')
        responders = [final_response]
        responders.extend(
            lambda message, index=index: tool_response(
                message, f'read-{index}', 'synthetic.read', {'path': f'item-{index}.txt'})
            for index in range(15))
        responders.append(final_response)
        browser = MockBrowser(responders)
        app = Orchestrator(config, browser, registry, state, display=lambda text: None)

        await app.initialize()
        response = await app.turn('Complete all observations without a tool-round cap.')

        self.assertEqual('complete', response['completion_status'])
        self.assertEqual(15, len(registry.calls))
        self.assertEqual([], browser.responders)

    async def test_prepared_pending_files_keep_the_exact_immutable_identity_later_sent(self):
        root, config, state, registry = make_fixture('next-turn-preload-')
        browser = PreloadingBrowser([final_response])
        app = Orchestrator(config, browser, registry, state, display=lambda text: None)
        source = root / 'workspace' / 'review.txt'
        source.write_text('approved review material', encoding='utf-8')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        app.base_context['pending_file_attachments'].append(str(source))
        app.approved_attachment_hashes[str(source)] = digest

        prepared = await app.prepare_pending_attachments()
        raw, request_id = await app._send('user_turn', 'Use the prepared review file.')

        self.assertEqual('prepared', prepared['status'])
        self.assertIn(request_id, raw)
        self.assertEqual(1, len(browser.attachment_preloads))
        prepared_path = browser.attachment_preloads[0][0]
        sent_path = browser.sent[0]['attachments'][0]
        self.assertNotEqual(source, prepared_path)
        self.assertEqual(prepared_path, sent_path)
        self.assertEqual(hashlib.sha256(prepared_path.read_bytes()).hexdigest(), digest)
        self.assertEqual([], app.base_context['pending_file_attachments'])

    async def test_initialization_can_upload_before_model_choice_then_send_exact_preload(self):
        root, config, state, registry = make_fixture('preloaded-initialization-')
        browser = PreloadingBrowser([final_response])
        app = Orchestrator(config, browser, registry, state, display=lambda text: None)

        prepared = await app.prepare_initialization()

        self.assertEqual(0, state.message_count)
        self.assertEqual(1, len(browser.preloads))
        preload = browser.preloads[0]
        self.assertEqual(8, len(preload['attachments']))
        self.assertEqual(0, sum(path.name.startswith('tool-results-') for path in preload['attachments']))
        self.assertEqual(prepared['request_id'], preload['request_id'])
        self.assertEqual(8, prepared['attachment_count'])
        self.assertIn(prepared['request_id'], preload['text'])

        result = await app.initialize()

        self.assertEqual('final', result['response_type'])
        self.assertEqual(1, state.message_count)
        self.assertEqual(1, len(browser.sent))
        self.assertEqual(preload['request_id'], browser.sent[0]['message']['request_id'])
        self.assertEqual(preload['attachments'], browser.sent[0]['attachments'])
        self.assertEqual(json.loads(preload['text']), browser.sent[0]['wire_message'])

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

    async def test_selected_code_file_is_exact_text_without_granting_c_write_root(self):
        from copilot_agent.attachments import AttachmentQueue
        from copilot_agent.policy import PolicyError
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
        self.assertEqual('local_action_rejected', state.data['retry_records'][0]['reason'])
        self.assertIn('failed a preflight check', browser.sent[-1]['message']['content']['instruction'])

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
        self.assertEqual(len(registry.calls),1, state.data.get('task_routing'))
        self.assertEqual(registry.calls[0][0],'code_runner')
        self.assertEqual(registry.calls[0][1],arguments)
        self.assertTrue(registry.calls[0][2]['approved'])
        self.assertEqual(len(previews),1)
        prepared = previews[0]['prepared_code']['plan']
        self.assertEqual(prepared['source_sha256'],original_hash)
        self.assertEqual(Path(prepared['source_path']),source)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original_hash)
        self.assertEqual(state.data['retry_records'],[])

    async def test_package_route_rejects_local_build_before_approval(self):
        approvals = []
        root, config, state, _, browser, _ = self.fixture(
            [final_response,
             lambda message: tool_response(message, 'mkdir-package', 'files.mkdir',
                                           {'path': 'workspace/copilot-build'}),
             final_response])
        registry = ToolRegistry()
        app = Orchestrator(config, browser, registry, state,
                           approval_decider=lambda preview: approvals.append(preview) or 'once',
                           display=lambda text: None)
        await app.initialize()
        await app.turn('Create a workflow that takes 30 minutes with dependencies, checkpoints, retries, recovery and validation.')
        self.assertEqual([], approvals)
        self.assertFalse((root / 'workspace' / 'copilot-build').exists())
        tool_messages = [item['message'] for item in browser.sent
                         if item['message']['kind'] == 'tool_results']
        self.assertTrue(tool_messages, browser.sent[-1]['message'].get('content'))
        tool_result_message = tool_messages[-1]
        result = tool_result_message['content']['results'][0]
        self.assertEqual('package_delivery_required', result['error']['code'])
        self.assertIn('Create the ZIP in Copilot Chat', tool_result_message['content']['instruction'])

    async def test_package_route_rejects_script_batch_before_code_preflight(self):
        invalid_script = "for item in values:\n"
        arguments = {'script': invalid_script, 'purpose': 'Build the requested package locally',
                     'language': 'local_python', 'working_directory': str(Path.cwd()),
                     'read_paths': [], 'create_paths': [], 'modify_paths': [], 'expected_outputs': [],
                     'commands': [], 'subprocesses': [], 'network_destinations': [], 'permissions': [],
                     'risk_summary': 'Local package build', 'recovery_notes': 'No effects',
                     'interpreter': sys.executable, 'arguments': [], 'imports': [],
                     'timeout_seconds': 3, 'max_output_chars': 1000,
                     'expected_effects': ['Build a ZIP'], 'viewer_windows': []}
        calls = [{'call_id': f'local-build-{index}', 'name': 'code_runner', 'version': '1.0',
                  'arguments': arguments, 'expected_result': 'Build local files'} for index in range(2)]
        root, config, state, _, browser, app = self.fixture([
            final_response,
            lambda message: final_response(message, response_type='tool_request', tools_required=True,
                                           tool_requests=calls, continuation_state='continue',
                                           completion_status='in_progress'),
            final_response])
        with patch.object(app, '_code_runner', side_effect=AssertionError('Code Runner preflight must be skipped')):
            await app.initialize()
            await app.turn('Create a workflow that takes 30 minutes with dependencies, checkpoints, retries, recovery and validation.')

        tool_messages = [item['message'] for item in browser.sent
                         if item['message']['kind'] == 'tool_results']
        self.assertEqual('package_delivery_required', tool_messages[-1]['content']['results'][0]['error']['code'])
        self.assertIn('Create the ZIP in Copilot Chat', tool_messages[-1]['content']['instruction'])

    async def test_automation_run_requires_passing_review_before_approval(self):
        approvals = []
        args = {'archive_path': str(Path.cwd() / 'not-reviewed.zip'),
                'expected_sha256': 'a' * 64,
                'workspace': str(Path.cwd() / 'workspace' / 'package-run')}
        root, config, state, _, browser, _ = self.fixture(
            [final_response,
             lambda message: tool_response(message, 'run-unreviewed', 'automation.run', args),
             final_response, RuntimeError('stop after observing the blocked run')])
        registry = ToolRegistry()
        app = Orchestrator(config, browser, registry, state,
                           approval_decider=lambda preview: approvals.append(preview) or 'once',
                           display=lambda text: None)
        await app.initialize()
        with self.assertRaisesRegex(RuntimeError, 'stop after observing'):
            await app.turn('Create a workflow that takes 30 minutes with dependencies, checkpoints, retries, recovery and validation.')
        self.assertEqual([], approvals)
        self.assertFalse(any(record.get('request', {}).get('name') == 'automation.run'
                             and record.get('result', {}).get('ok')
                             for record in state.data['calls'].values()))
        tool_messages = [item['message'] for item in browser.sent
                         if item['message']['kind'] == 'tool_results']
        self.assertTrue(tool_messages, browser.sent[-1]['message'].get('content'))
        tool_result_message = tool_messages[-1]
        result = tool_result_message['content']['results'][0]
        self.assertEqual('package_review_failed', result['error']['code'])
        self.assertEqual('not_started', result['result']['status'])
        self.assertEqual('failed', result['result']['review']['status'])

    async def test_private_session_rechecks_exact_package_after_review_evidence_is_redacted(self):
        root, _, state, registry, _, app = self.fixture([])
        archive = root / 'workspace' / 'reviewed.zip'
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(b'synthetic archive bytes')
        digest = 'a' * 64
        passing_review = {'ok': True, 'tool': 'automation.inspect',
                          'result': {'status': 'validated', 'archive_sha256': digest,
                                     'review': {'status': 'passed', 'archive_sha256': digest,
                                                'checks': [{'item': 'ZIP can be opened safely',
                                                            'status': 'passed'}],
                                                'failures': [], 'not_checked_count': 0}}}
        state.data['website_private'] = True
        state.data['calls']['previous-review'] = {
            'request': {'name': 'automation.inspect', 'version': '1.0', 'call_id': 'previous-review',
                        'arguments': {'path': str(archive), 'expected_sha256': digest}},
            'status': 'completed', 'result': passing_review}
        state.data = private_session_snapshot(state.data)
        self.assertIsNone(app._prior_package_review(digest))

        registry.definition = lambda name: {'timeout': 1}
        registry.execute = AsyncMock(return_value=passing_review)
        context = {'source_request_id': 'resume-request'}
        with patch.object(app, '_local_archive_sha256', return_value=(archive, digest)):
            restored = await app._ensure_package_review(
                {'archive_path': str(archive), 'expected_sha256': digest}, context)

        self.assertTrue(app._review_passed(restored))
        registry.execute.assert_awaited_once_with(
            'automation.inspect', {'path': str(archive), 'expected_sha256': digest},
            {'source_request_id': 'resume-request'})
        fresh = [record for record in state.data['calls'].values()
                 if record.get('request', {}).get('call_id', '').startswith('auto-package-run-review-')]
        self.assertEqual(1, len(fresh))
        self.assertTrue(app._review_passed(fresh[0]['result']))

    async def test_task_estimate_ignores_a_serialized_tool_arguments_block(self):
        request = ('Run one exact existing script and report the observed result. Arguments:\n' +
                   json.dumps({'script': "print('synthetic')\\n", 'permissions': ['read_files'],
                               'expected_outputs': ['report.txt'], 'network_destinations': []}))
        self.assertEqual('Run one exact existing script and report the observed result.',
                         Orchestrator._routing_description(request))

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

    async def test_identical_failed_action_rejection_includes_observed_result(self):
        root, config, state, registry, browser, app = self.fixture(
            [final_response,
             lambda msg: tool_response(msg, 'failed-first', 'synthetic.write', {'path': 'same.txt'}),
             lambda msg: tool_response(msg, 'failed-again-new-id', 'synthetic.write', {'path': 'same.txt'}),
             final_response], lambda preview: 'once')

        async def execute(name, arguments, context):
            registry.calls.append((name, copy.deepcopy(arguments), dict(context)))
            return {'ok': False, 'result': {'status': 'failed', 'side_effects_uncertain': False},
                    'error': {'code': 'operation_failed', 'message': 'Verified no declared effect.'}}

        registry.execute = execute
        await app.initialize()
        await app.turn('Recover using the observed failure result.')

        self.assertEqual(1, len(registry.calls))
        self.assertEqual('local_action_rejected', state.data['retry_records'][0]['reason'])
        self.assertIn('Verified no declared effect.', state.data['retry_records'][0]['errors'][0])
        correction = browser.sent[-1]['message']['content']
        self.assertIn('failed a preflight check', correction['instruction'])
        self.assertIn('changing only its call_id does not count', correction['instruction'])

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
        self.assertIn('browser.recover_uncertain', state.data['retry_records'][0]['errors'][0])

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

    async def test_recover_capture_failed_turn_uses_saved_request_without_resending_user_message(self):
        def interrupted(message):
            raise CaptureTimeoutError('Visible response arrived beyond the initial capture window.')
        root, config, state, registry, browser, app = self.fixture([final_response, interrupted])
        await app.initialize()
        with self.assertRaises(CaptureTimeoutError):
            await app.turn('Resume this already committed request.')
        request_id = [item for item in state.data['messages'] if item['role'] == 'copilot_outbound'][-1]['request_id']

        async def recover(committed_request_id):
            self.assertEqual(request_id, committed_request_id)
            return encoded(final_response(browser.sent[-1]['message']))
        browser.capture_committed_response = recover

        result = await app.recover_capture_failed_turn()

        self.assertEqual('final', result['response_type'])
        self.assertEqual(2, len(browser.sent))  # initialization plus the original request
        self.assertEqual(2, state.message_count)
        self.assertEqual(1, len([item for item in state.data['messages']
                                if item['role'] == 'user']))
        self.assertEqual('ready', state.data['status'])

    async def test_restart_recovers_committed_reply_after_file_or_raw_ledger_save(self):
        for raw_ledger_saved in (False, True):
            with self.subTest(raw_ledger_saved=raw_ledger_saved):
                def interrupted(message):
                    raise CaptureTimeoutError('Synthetic interruption after committed send.')
                root, config, state, registry, browser, app = self.fixture([final_response, interrupted])
                await app.initialize()
                with self.assertRaises(CaptureTimeoutError):
                    await app.turn('Complete the already committed request after restart.')
                sent = browser.sent[-1]['message']
                request_id = sent['request_id']
                raw = encoded(final_response(sent))
                app._record_raw_response(raw, request_id)
                if not raw_ledger_saved:
                    # Simulate interruption after the response artifact write
                    # but before the matching atomic session snapshot.
                    state.data['messages'] = [message for message in state.data['messages']
                                              if not (message['role'] == 'copilot_raw'
                                                      and message.get('request_id') == request_id)]
                    state.save()
                resumed = SessionState(state.directory, resume=True)
                self.assertEqual(request_id, recoverable_capture_request_id(resumed))
                restarted = Orchestrator(config, browser, registry, resumed, display=lambda text: None)
                restarted.initialized = True

                async def capture(committed_request_id):
                    self.assertEqual(request_id, committed_request_id)
                    return raw
                browser.capture_committed_response = capture
                response = await restarted.recover_capture_failed_turn()

                self.assertEqual('final', response['response_type'])
                self.assertEqual(2, len(browser.sent))
                self.assertEqual(2, resumed.message_count)
                self.assertEqual(1, len([item for item in resumed.data['messages']
                                        if item['role'] == 'copilot_raw' and item.get('request_id') == request_id]))
                self.assertEqual(1, len([item for item in resumed.data['messages']
                                        if item['role'] == 'copilot' and item.get('request_id') == request_id]))
                self.assertIsNone(recoverable_capture_request_id(resumed))

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

    async def test_recovered_invalid_responses_skip_slow_ui_diagnostics(self):
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
        self.assertEqual([], captured)
        events = [json.loads(line) for line in state.log.path.read_text(encoding='utf-8').splitlines()]
        evidence = [item for item in events if item['event'] == 'protocol_ui_evidence']
        self.assertEqual([], evidence)
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
        self.assertEqual([], captured)
        self.assertEqual('correction', browser.sent[-1]['message']['kind'])
        self.assertEqual(3, state.message_count)
        self.assertEqual(1, len(state.data['retry_records']))
        self.assertEqual('ready', state.data['status'])
        events = [json.loads(line) for line in state.log.path.read_text(encoding='utf-8').splitlines()]
        unavailable = [item for item in events if item['event'] == 'protocol_ui_evidence_unavailable']
        self.assertEqual([], unavailable)
        self.assertEqual([], registry.calls)
