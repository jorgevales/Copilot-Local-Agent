"""Replay the changed picker structure in an isolated, offline Edge page."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from copilot_agent.browser import BrowserAdapter, ModelUnavailableError


PICKER_HTML = '''
<button id="gptModeSwitcher" aria-expanded="false">Models</button>
<div id="top" role="menu" hidden>
  <div role="menuitem" data-testid="gptSubMenuModelTrigger-Magic" aria-checked="true">
    <svg data-testid="checkmark-Magic"></svg>Auto
  </div>
  <div id="claude" role="menuitem" aria-haspopup="menu" aria-expanded="false"
       data-testid="gptSubMenuModelTrigger-Claude" aria-checked="false">
    <svg data-testid="checkmark-Claude"></svg>Claude Anthropic
  </div>
  <div id="gpt" role="menuitem" aria-haspopup="menu" aria-expanded="false"
       data-testid="gptSubMenuModelTrigger-OpenAI" aria-checked="false">
    <svg data-testid="checkmark-OpenAI"></svg>GPT OpenAI
  </div>
</div>
<div id="claude-options" role="menu" aria-labelledby="claude" hidden>
  <div role="menuitem" data-testid="gptSubMenuModelTrigger-Claude" aria-checked="false">
    <svg data-testid="checkmark-Claude_Sonnet"></svg>Sonnet 5.5
  </div>
</div>
<div id="gpt-options" role="menu" aria-labelledby="gpt" hidden>
  <div role="menuitem" data-testid="gptSubMenuModelTrigger-OpenAI" aria-checked="false">
    <svg data-testid="checkmark-Gpt_5_6_Chat"></svg>GPT-5.6 Sol Quick response
  </div>
  <div role="menuitem" data-testid="gptSubMenuModelTrigger-OpenAI" aria-checked="false">
    <svg data-testid="checkmark-Gpt_5_6_Reasoning"></svg>GPT-5.6 Sol Think deeper
  </div>
  <div role="menuitem" data-testid="gptSubMenuModelTrigger-OpenAI"
       aria-checked="false" aria-disabled="true">
    <svg data-testid="checkmark-Gpt_61_Sol_Reasoning"></svg>GPT-6.1 Sol
  </div>
</div>
<script>
const picker = document.getElementById('gptModeSwitcher');
const topMenu = document.getElementById('top');
function closeMenus() {
  document.querySelectorAll('[role="menu"]').forEach(n => n.hidden = true);
  document.querySelectorAll('[aria-expanded]').forEach(n => n.setAttribute('aria-expanded', 'false'));
}
picker.onclick = () => {
  picker.setAttribute('aria-expanded', 'true');
  setTimeout(() => topMenu.hidden = false, 60);
};
for (const id of ['claude', 'gpt']) {
  const provider = document.getElementById(id);
  provider.onclick = () => {
    provider.setAttribute('aria-expanded', 'true');
    setTimeout(() => document.getElementById(id + '-options').hidden = false, 80);
  };
}
document.querySelectorAll('[role="menu"][aria-labelledby] [role="menuitem"]').forEach(n => {
  n.onclick = () => {
    if (n.getAttribute('aria-disabled') === 'true') return;
    document.querySelectorAll('[aria-checked]').forEach(m => m.setAttribute('aria-checked', 'false'));
    n.setAttribute('aria-checked', 'true');
    closeMenus();
  };
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenus(); });
</script>
'''


class ModelPickerDOMTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            from playwright.async_api import async_playwright, Error
        except ImportError:
            self.skipTest('Playwright is not installed')
        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        try:
            self.edge = await self.playwright.chromium.launch(channel='msedge', headless=True)
        except Error as exc:
            self.skipTest('An installed Edge browser is required: ' + str(exc))
        self.addAsyncCleanup(self.edge.close)
        self.page = await self.edge.new_page()
        await self.page.set_content(PICKER_HTML)
        self.adapter = BrowserAdapter(SimpleNamespace(startup_timeout=5, poll_interval=.05))
        self.adapter.page = self.page
        self.adapter.diagnostics = AsyncMock()

    async def test_provider_checkmarks_delayed_menus_and_disabled_model(self):
        models = await self.adapter.discover_models()
        self.assertEqual({
            ('Claude', 'Sonnet 5.5', True),
            ('OpenAI', 'GPT-5.6 Sol Quick response', True),
            ('OpenAI', 'GPT-5.6 Sol Think deeper', True),
            ('OpenAI', 'GPT-6.1 Sol', False),
        }, {(m['provider'], m['label'], m['enabled']) for m in models})
        with self.assertRaises(ModelUnavailableError):
            await self.adapter.select_model('GPT-6.1 Sol')
        chosen = await self.adapter.select_model('GPT-5.6 Sol Think deeper')
        self.assertTrue(chosen['verified'])
        self.assertEqual('GPT-5.6 Sol Think deeper', self.adapter.model_label)

    async def test_legacy_provider_and_changed_model_names_remain_discoverable(self):
        await self.page.locator('#gpt svg').evaluate('(n) => n.remove()')
        await self.page.locator('#gpt').evaluate('(n) => n.removeAttribute("aria-haspopup")')
        await self.page.locator('#gpt-options [role="menuitem"]').first.evaluate(
            '(n) => n.lastChild.textContent = "Future account model"')
        models = await self.adapter.discover_models()
        self.assertIn('Future account model', [m['label'] for m in models])
        chosen = await self.adapter.select_model('Future account model')
        self.assertTrue(chosen['verified'])
