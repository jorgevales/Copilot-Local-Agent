"""Delivery evidence, immutable observed-artifact approval and log redaction."""
import asyncio
import hashlib
import json
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from copilot_agent.policy import PolicyError
from copilot_agent.approvals import ApprovalManager
from copilot_agent.logging_utils import redact
from copilot_agent.orchestrator import Orchestrator
from tests.test_orchestrator import MockBrowser, final_response, tool_response
from tests.test_protocol_state import make_fixture


class DeliveryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_automatically_inspected_unnamed_automation_zip_satisfies_zip_delivery(self):
        await self._automatic_package_delivery()

    async def test_immediate_session_downloads_and_runs_without_quality_review_or_prompts(self):
        with patch('copilot_agent.automation_packages._preflight_package_review',
                   side_effect=AssertionError('Quality reviewer must not run in immediate mode')):
            await self._automatic_package_delivery(immediate=True)

    async def _automatic_package_delivery(self, immediate=False):
        from copilot_agent.tools import ToolRegistry
        from copilot_agent.delivery import delivery_requirements
        from tests.test_automation_packages import write_python_package

        prompt = ('Create and deliver a NEW executable automation ZIP that performs a fresh multi-tab '
                  'GOV.UK navigation proof and stores the navigation knowledge.')
        requirement = delivery_requirements(prompt)
        self.assertEqual('zip', requirement['mode'])
        self.assertEqual([], requirement['expected_names'])
        self.assertEqual('The user explicitly requested an archive/package.', requirement['reason'])

        root, config, state, _ = make_fixture('delivery-inspected-package-')
        config.max_delivery_retries = 1
        config.automation_package_score = 1
        config._continuous_package_session = immediate
        config._package_review_enabled = not immediate
        archive = root / 'workspace' / 'govuk-package.zip'
        write_python_package(archive, "from pathlib import Path\nimport sys\nPath(sys.argv[-1]).joinpath('result.txt').write_text('verified', encoding='utf-8')\n")

        def download_request(message):
            return tool_response(message, call_id='download-package', name='copilot.download',
                                 arguments={'expected_name': archive.name,
                                            'link_text': 'Download ' + archive.name})

        browser = MockBrowser([final_response, download_request, *([final_response] * 4)])
        registry = ToolRegistry()
        approvals = []
        def decide(preview):
            approvals.append(preview)
            return 'deny' if immediate else 'once'
        agent = Orchestrator(config, browser, registry, state,
                             approval_decider=decide, display=lambda text: None)

        class DownloadStub:
            async def prepare(self, arguments, request_id):
                return {'expected_name': arguments['expected_name'], 'request_id': request_id}

        agent.download_service = DownloadStub()
        original_execute = registry.execute

        async def execute(name, arguments, context):
            if name == 'copilot.download':
                return {'ok': True, 'tool': name, 'result': {
                    'status': 'downloaded', 'path': str(archive),
                    'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                    'size': archive.stat().st_size}}
            return await original_execute(name, arguments, context)

        with patch.object(registry, 'execute', new=AsyncMock(side_effect=execute)):
            await agent.initialize()
            result = await agent.turn(prompt)

        self.assertEqual('complete', result['completion_status'])
        if immediate:
            self.assertEqual([], approvals)
        self.assertNotIn('delivery_retry', [entry['message']['kind'] for entry in browser.sent])
        inspections = [record for record in state.data['calls'].values()
                       if record.get('request', {}).get('name') == 'automation.inspect']
        self.assertEqual(1, len(inspections))
        self.assertEqual('ready_unreviewed' if immediate else 'validated', inspections[0]['result']['result']['status'])
        inspection_id = next(call_id for call_id, record in state.data['calls'].items()
                             if record is inspections[0])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        download_report = {'tool': 'copilot.download', 'status': 'downloaded',
                           'path': str(archive), 'sha256': digest}
        receipt = {'tool': 'automation.inspect', 'status': 'verified', 'review_status': 'skipped' if immediate else 'passed',
                   'path': str(archive), 'sha256': digest, 'inspection_call_id': inspection_id}
        self.assertTrue(agent._delivery_verified(requirement, [download_report, receipt]))
        self.assertFalse(agent._delivery_verified(
            {'mode': 'zip', 'reason': requirement['reason'], 'expected_names': ['README.md']},
            [download_report, receipt]))
        self.assertFalse(agent._delivery_verified(
            {'mode': 'zip', 'reason': 'Office outputs always require a downloadable ZIP, including single files.',
             'expected_names': ['report.pptx']}, [download_report, receipt]))
        self.assertFalse(agent._delivery_verified(
            {'mode': 'zip', 'reason': requirement['reason'], 'expected_names': ['different.zip']},
            [download_report, receipt]))

        recorded_args = state.data['calls'][inspection_id]['request']['arguments']
        original_hash = recorded_args.get('expected_sha256')
        recorded_args['expected_sha256'] = '0' * 64
        self.assertFalse(agent._delivery_verified(requirement, [download_report, receipt]))
        if original_hash is None:
            recorded_args.pop('expected_sha256')
        else:
            recorded_args['expected_sha256'] = original_hash
        with archive.open('ab') as stream:
            stream.write(b'changed after verification')
        self.assertFalse(agent._delivery_verified(requirement, [download_report, receipt]))

    async def test_explicit_inspection_satisfies_delivery_without_a_new_link(self):
        await self._explicit_inspection_delivery()

    async def test_explicit_inspection_without_optional_hash_finishes_delivery(self):
        await self._explicit_inspection_delivery(include_expected_hash=False)

    async def test_reused_explicit_review_updates_delivery_evidence(self):
        await self._explicit_inspection_delivery(reuse_review=True)

    async def test_reused_review_without_optional_hash_finishes_delivery(self):
        await self._explicit_inspection_delivery(include_expected_hash=False, reuse_review=True)

    async def test_reused_review_binds_current_download_copy(self):
        await self._explicit_inspection_delivery(reuse_review=True, review_copy=True)

    async def _explicit_inspection_delivery(self, include_expected_hash=True, reuse_review=False, review_copy=False):
        from copilot_agent.tools import ToolRegistry
        from copilot_agent.delivery import delivery_requirements
        from tests.test_automation_packages import package_bytes

        prompt = ('Create and deliver a NEW executable automation ZIP that performs a fresh multi-tab '
                  'GOV.UK navigation proof and stores the navigation knowledge.')
        requirement = delivery_requirements(prompt)
        self.assertEqual('zip', requirement['mode'])
        self.assertEqual([], requirement['expected_names'])
        self.assertEqual('The user explicitly requested an archive/package.', requirement['reason'])

        root, config, state, _ = make_fixture('delivery-inspected-package-')
        config.max_delivery_retries = 1
        config.automation_package_score = 100000
        archive = root / 'workspace' / 'govuk-package.zip'
        archive.write_bytes(package_bytes())

        def download_request(message):
            return tool_response(message, call_id='download-package', name='copilot.download',
                                 arguments={'expected_name': archive.name,
                                            'link_text': 'Download ' + archive.name})

        def inspect_request(message):
            arguments = {'path': str(archive)}
            if include_expected_hash:
                arguments['expected_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
            return tool_response(message, call_id='inspect-package', name='automation.inspect',
                                 arguments=arguments)

        browser = MockBrowser([final_response, download_request, inspect_request, *([final_response] * 4)])
        registry = ToolRegistry()
        agent = Orchestrator(config, browser, registry, state,
                             approval_decider=lambda preview: 'once', display=lambda text: None)

        class DownloadStub:
            async def prepare(self, arguments, request_id):
                return {'expected_name': arguments['expected_name'], 'request_id': request_id}

        agent.download_service = DownloadStub()
        original_execute = registry.execute

        if reuse_review:
            prior_archive = archive
            if review_copy:
                prior_archive = archive.with_name('prior-package.zip')
                prior_archive.write_bytes(archive.read_bytes())
            prior = {'call_id': 'prior-package-inspection', 'name': 'automation.inspect', 'version': '1.0',
                     'arguments': {'path': str(prior_archive),
                                   'expected_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}}
            state.begin_call(prior, state_changing=False)
            state.finish_call(prior['call_id'], await original_execute('automation.inspect', prior['arguments'], agent.base_context))

        async def execute(name, arguments, context):
            if name == 'copilot.download':
                return {'ok': True, 'tool': name, 'result': {
                    'status': 'downloaded', 'path': str(archive),
                    'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                    'size': archive.stat().st_size}}
            return await original_execute(name, arguments, context)

        with patch.object(registry, 'execute', new=AsyncMock(side_effect=execute)):
            await agent.initialize()
            result = await agent.turn(prompt)

        self.assertEqual('complete', result['completion_status'])
        self.assertNotIn('delivery_retry', [entry['message']['kind'] for entry in browser.sent])
        inspections = [record for record in state.data['calls'].values()
                       if record.get('request', {}).get('name') == 'automation.inspect']
        self.assertEqual(2 if reuse_review else 1, len(inspections))
        self.assertEqual('validated', inspections[0]['result']['result']['status'])
        inspection_id = 'inspect-package'
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        download_report = {'tool': 'copilot.download', 'status': 'downloaded',
                           'path': str(archive), 'sha256': digest}
        receipt = {'tool': 'automation.inspect', 'status': 'verified', 'review_status': 'passed',
                   'path': str(archive), 'sha256': digest, 'inspection_call_id': inspection_id}
        self.assertTrue(agent._delivery_verified(requirement, [download_report, receipt]))
        self.assertFalse(agent._delivery_verified(
            {'mode': 'zip', 'reason': requirement['reason'], 'expected_names': ['README.md']},
            [download_report, receipt]))
        self.assertFalse(agent._delivery_verified(
            {'mode': 'zip', 'reason': 'Office outputs always require a downloadable ZIP, including single files.',
             'expected_names': ['report.pptx']}, [download_report, receipt]))
        self.assertFalse(agent._delivery_verified(
            {'mode': 'zip', 'reason': requirement['reason'], 'expected_names': ['different.zip']},
            [download_report, receipt]))

    async def test_large_package_report_keeps_hash_bound_verification(self):
        from copilot_agent.tools import ToolRegistry
        root, config, state, registry = make_fixture('delivery-large-report-')
        agent = Orchestrator(config, MockBrowser([]), registry, state, display=lambda text: None)
        report = {'status': 'verified', 'archive': 'package.zip', 'archive_sha256': 'a' * 64, 'destination': 'new-output',
                  'verified_files': [{'path': 'file-' + str(number) + '.txt', 'sha256': 'b' * 64, 'size': 10} for number in range(150)], 'expected_files': ['file-0.txt']}
        outcome = ToolRegistry()._limit({'ok': True, 'tool': 'archives.extract', 'result': report}, {'session_dir': state.directory, 'config': config})
        self.assertTrue(outcome['result']['truncated'])
        self.assertEqual(150, outcome['result']['verification_summary']['verified_file_count'])
        self.assertEqual(report, agent._delivery_result('archives.extract', outcome))
        retained = Path(outcome['result']['retained_result'])
        with retained.open('ab') as output: output.write(b'changed')
        with self.assertRaises(PolicyError): agent._delivery_result('archives.extract', outcome)

    async def test_extraction_must_match_current_retained_download(self):
        root, config, state, registry = make_fixture('delivery-origin-')
        agent = Orchestrator(config, MockBrowser([]), registry, state, display=lambda text: None)
        artifact = root / 'workspace' / 'README.md'; artifact.write_text('synthetic', encoding='utf-8')
        archive = root / 'workspace' / 'package.zip'
        with zipfile.ZipFile(archive, 'w') as package: package.writestr('README.md', 'synthetic')
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        extraction = {'tool': 'archives.extract', 'status': 'verified', 'archive': str(archive), 'archive_sha256': digest,
                      'verified_files': [{'path': str(artifact), 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}]}
        request = {'mode': 'zip', 'expected_names': ['README.md', 'package.zip']}
        self.assertFalse(agent._delivery_verified(request, [extraction]))
        download = {'tool': 'copilot.download', 'status': 'downloaded', 'path': str(archive), 'sha256': digest}
        self.assertTrue(agent._delivery_verified(request, [download, extraction]))
        with archive.open('ab') as output: output.write(b'changed')
        self.assertFalse(agent._delivery_verified(request, [download, extraction]))

    async def test_plain_model_claim_cannot_finish_delivery_and_retries_count(self):
        root, config, state, registry = make_fixture('delivery-unverified-')
        config.max_delivery_retries = 2
        browser = MockBrowser([final_response] * 4)
        agent = Orchestrator(config, browser, registry, state, display=lambda text: None)
        await agent.initialize()
        response = await agent.turn('Create one text file named example.txt with synthetic content.')
        self.assertEqual('blocked', response['completion_status'])
        self.assertEqual('delivery_blocked', state.data['status'])
        self.assertEqual(4, state.message_count)
        self.assertEqual(['initialize', 'user_turn', 'delivery_retry', 'delivery_retry'], [entry['message']['kind'] for entry in browser.sent])
        self.assertIn('actual downloadable', browser.sent[1]['message']['file_delivery_instruction'])
        self.assertTrue(all(entry['message']['content'] for entry in browser.sent))

    async def test_verified_download_requires_unchanged_local_hash_and_expected_name(self):
        root, config, state, registry = make_fixture('delivery-evidence-')
        agent = Orchestrator(config, MockBrowser([]), registry, state, display=lambda text: None)
        path = root / 'workspace' / 'example.txt'; path.write_text('synthetic', encoding='utf-8')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        report = {'tool': 'copilot.download', 'status': 'verified', 'path': str(path), 'sha256': digest}
        from copilot_agent.delivery import delivery_requirements
        requirement = delivery_requirements('Create one text file named example.txt. If direct delivery is unavailable, ZIP fallback is allowed.')
        self.assertTrue(agent._delivery_verified(requirement, [report]))
        self.assertFalse(agent._delivery_verified({'mode': 'zip', 'expected_names': []}, [report]))
        self.assertFalse(agent._delivery_verified({'mode': 'direct', 'expected_names': ['other.txt']}, [report]))
        path.write_text('changed', encoding='utf-8')
        self.assertFalse(agent._delivery_verified(requirement, [report]))

    async def test_observed_link_or_destination_change_invalidates_plan_grant(self):
        root, config, state, registry = make_fixture('delivery-grant-')
        previews = []
        def decide(preview): previews.append(preview); return 'plan'
        approvals = ApprovalManager(state, decide)
        call = {'call_id': 'download-one', 'name': 'copilot.download', 'version': '1.0', 'arguments': {'expected_name': 'example.txt'}}
        plan = {'tool_requests': [call]}
        await approvals.request(plan, call, {'href_sha256': 'a' * 64, 'destination': 'one'})
        await approvals.request(plan, call, {'href_sha256': 'b' * 64, 'destination': 'two'})
        self.assertEqual(2, len(previews))
        self.assertNotEqual(previews[0]['plan_hash'], previews[1]['plan_hash'])


class SignedLinkTests(unittest.TestCase):
    def test_single_file_with_conditional_zip_fallback_stays_direct(self):
        from copilot_agent.delivery import delivery_requirements
        request = 'Create one harmless text file named synthetic-delivery.txt. Provide an actual downloadable UI file link. If direct delivery is unavailable, ZIP fallback is allowed.'
        self.assertEqual('direct', delivery_requirements(request)['mode'])

    def test_signed_urls_are_removed_from_response_text_and_nested_state(self):
        value = {'response': '[download](https://host.example/artifact.zip?sv=1&sig=secret-value&se=later)', 'nested': ['https://host.example/x?%74oken=secret-token']}
        encoded = json.dumps(redact(value))
        self.assertNotIn('secret-value', encoded)
        self.assertNotIn('secret-token', encoded)
        self.assertIn('artifact.zip', encoded)

    def test_ordinary_query_does_not_change_task_intent(self):
        self.assertEqual('https://example.com/search?q=synthetic', redact('https://example.com/search?q=synthetic'))


class ExtractionLocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_extraction_outside_selected_onedrive_is_denied(self):
        from copilot_agent.tools import ToolRegistry
        root, config, state, registry = make_fixture('extraction-location-')
        storage = root / 'onedrive-storage'; storage.mkdir()
        archive = root / 'workspace' / 'package.zip'
        with zipfile.ZipFile(archive, 'w') as package: package.writestr('example.txt', 'synthetic')
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        context = {'config': {'storage_dir': str(storage), 'allowed_roots': [str(root / 'workspace'), str(storage)]}, 'session_dir': state.directory, 'approved': True}
        tools = ToolRegistry()
        rejected = await tools.execute('archives.extract', {'path': str(archive), 'destination': str(root / 'workspace' / 'outside-onedrive'), 'expected_sha256': digest}, context)
        self.assertFalse(rejected['ok'])
        self.assertFalse((root / 'workspace' / 'outside-onedrive').exists())
        accepted = await tools.execute('archives.extract', {'path': str(archive), 'destination': str(storage / 'delivered'), 'expected_sha256': digest, 'expected_files': ['example.txt']}, context)
        self.assertTrue(accepted['ok'])
        self.assertEqual('synthetic', (storage / 'delivered' / 'example.txt').read_text())
