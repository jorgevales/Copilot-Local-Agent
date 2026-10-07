"""Startup latency contracts without launching Edge or sending Copilot messages."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.app import run
from tests.test_protocol_state import make_fixture


class StartupBrowser:
    def __init__(self, events):
        self.events = events
        self.model_label = None

    async def start(self):
        self.events.append('browser:start')

    async def discover_models(self):
        self.events.append('browser:discover')
        return [
            {'label': 'GPT-6 Sol', 'enabled': True, 'provider': 'OpenAI'},
            {'label': 'Alternate model', 'enabled': True, 'provider': 'OpenAI'},
        ]

    async def select_model(self, label):
        self.events.append('browser:select:' + label)
        self.model_label = label
        return {'label': label, 'checked': True}

    async def verify_interaction_ready(self, expected_model):
        self.events.append('browser:ready:' + expected_model)
        return True

    async def close(self):
        self.events.append('browser:close')


class StartupOrchestrator:
    events = None

    def __init__(self, config, browser, registry, state, **kwargs):
        self.browser = browser
        self.state = state
        self.findings = SimpleNamespace(data={'findings': []})
        self.events.append('orchestrator:create')

    async def prepare_initialization(self):
        self.events.append('orchestrator:preload')
        return {'request_id': 'synthetic', 'attachment_count': 8}

    async def initialize(self):
        self.events.append('orchestrator:initialize')
        self.state.data['status'] = 'ready'
        return {'response_type': 'final'}

    def attachment_queue(self):
        return SimpleNamespace(records=lambda: [], verify=lambda: None,
                               paths=lambda: [], clear=lambda: None)

    async def close(self, **kwargs):
        self.events.append('orchestrator:close')


class StartupFlowTests(unittest.IsolatedAsyncioTestCase):
    async def run_flow(self, answers, explicit_model=None, configured_model='GPT-6 Sol'):
        root, config, _, _ = make_fixture('app-startup-flow-')
        config.storage_dir = root
        config.model = configured_model
        config.profile_dir = root / 'profile'
        events = []
        browser = StartupBrowser(events)
        StartupOrchestrator.events = events
        replies = iter(answers)

        async def answer(prompt):
            events.append('ask:' + prompt)
            return next(replies)

        args = SimpleNamespace(config=None, attach_existing=False, port=None,
                               profile=None, model=explicit_model, setup_only=False,
                               resume=None, yes_setup=True)
        with patch('copilot_agent.app.Config.load', return_value=config), \
             patch('copilot_agent.app.discover_onedrive_accounts', return_value=[]), \
             patch('copilot_agent.app.validate_storage_directory', side_effect=lambda path, accounts: Path(path)), \
             patch('copilot_agent.app.read_user_settings', return_value={}), \
             patch('copilot_agent.app.save_user_settings'), \
             patch('copilot_agent.app.choose_edge', new=AsyncMock()), \
             patch('copilot_agent.app.choose_browser_endpoint', new=AsyncMock()), \
             patch('copilot_agent.app.BrowserAdapter', return_value=browser), \
             patch('copilot_agent.app.Orchestrator', StartupOrchestrator), \
             patch('copilot_agent.app.ask', side_effect=answer), \
             patch('copilot_agent.app.system'):
            await run(args)
        return events

    async def test_default_is_preselected_while_user_decides_and_readiness_precedes_prompt(self):
        events = await self.run_flow(['', ':exit'])
        model_prompt = next(item for item in events if item.startswith('ask:Choose'))
        user_prompt = next(item for item in events if item == 'ask:You: ')

        self.assertLess(events.index('orchestrator:preload'), events.index('browser:discover'))
        self.assertLess(events.index('browser:select:GPT-6 Sol'), events.index(model_prompt))
        self.assertEqual(1, events.count('browser:select:GPT-6 Sol'))
        self.assertLess(events.index('orchestrator:initialize'),
                        events.index('browser:ready:GPT-6 Sol'))
        self.assertLess(events.index('browser:ready:GPT-6 Sol'), events.index(user_prompt))

    async def test_alternate_choice_changes_model_once_after_default_preselection(self):
        events = await self.run_flow(['2', ':exit'])

        self.assertEqual(1, events.count('browser:select:GPT-6 Sol'))
        self.assertEqual(1, events.count('browser:select:Alternate model'))
        self.assertLess(events.index('browser:select:GPT-6 Sol'),
                        events.index('browser:select:Alternate model'))
        self.assertLess(events.index('browser:select:Alternate model'),
                        events.index('orchestrator:initialize'))
        self.assertLess(events.index('orchestrator:initialize'),
                        events.index('browser:ready:Alternate model'))

    async def test_legacy_empty_saved_model_migrates_to_product_default(self):
        events = await self.run_flow(['', ':exit'], configured_model='')

        self.assertEqual(1, events.count('browser:select:GPT-6 Sol'))


if __name__ == '__main__':
    unittest.main()
