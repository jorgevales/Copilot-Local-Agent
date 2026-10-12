"""Local Edge checks with a fake runtime; never starts Copilot or real tools."""
import secrets
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from agent_ui.workspace import Handler, Workspace


class LaunchUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(channel='msedge', headless=True)
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.ws = Workspace()
        self.calls = []
        self.gate = threading.Event()
        calls, gate = self.calls, self.gate

        class Runtime:
            def submit(self, text):
                calls.append(text)
                gate.wait(10)

        self.ws.runtime = Runtime()
        self.ws.capabilities = {'stop': True, 'attach': True, 'new_session': True}
        self.ws.emit('status', {'state': 'awaiting_input',
                               'summary': '[User] Allow local navigation and verified knowledge saving for this run [Y/n]? '})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.workspace = self.ws
        self.server.token = secrets.token_urlsafe(32)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto(f'http://127.0.0.1:{self.server.server_port}/#token={self.server.token}')
        expect(self.page.locator('#start-agent')).to_be_enabled()

    def tearDown(self):
        self.gate.set()
        self.context.close()
        self.ws.close()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)

    def test_start_payload_pending_draft_and_responsive_presentation(self):
        page = self.page
        page.locator('#composer').fill('Keep this first request')
        expect(page.locator('#send')).to_be_disabled()
        self.assertEqual(page.locator('#composer').get_attribute('aria-describedby'),
                         'composer-hint composer-error')
        page.locator('#start-agent').focus()
        self.assertNotEqual(page.locator('#start-agent').evaluate(
            'e => getComputedStyle(e).outlineStyle'), 'none')
        output = Path('runtime/ui-design')
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / 'launch-desktop.png'), full_page=True)
        for width in (720, 390, 320):
            page.set_viewport_size({'width': width, 'height': 860})
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
            expect(page.locator('#start-agent')).to_be_in_viewport()
        page.screenshot(path=str(output / 'launch-mobile.png'), full_page=True)
        page.emulate_media(reduced_motion='reduce')
        self.assertEqual(page.locator('#start-agent').evaluate(
            'e => getComputedStyle(e).transitionDuration'), '0s')
        page.locator('#start-agent').press('Enter')
        expect(page.locator('#start-agent')).to_be_disabled()
        expect(page.locator('#launch-status')).to_contain_text('Waiting for the backend')
        # Repeated programmatic clicks cannot send another confirmation.
        page.locator('#start-agent').evaluate('e => { e.click(); e.click(); }')
        self.assertEqual(self.calls, ['y'])
        expect(page.locator('#composer')).to_have_value('Keep this first request')
        self.gate.set()
        self.ws.emit('status', {'state': 'awaiting_input', 'summary': 'Choose a displayed model number: '})
        expect(page.locator('#launch-card')).to_be_hidden()
        expect(page.locator('#send')).to_be_enabled()
        expect(page.locator('#composer-hint')).to_contain_text('Reply to the backend prompt')
        self.ws.emit('user', {'text': 'Conversation remains primary'})
        expect(page.locator('#welcome')).to_be_hidden()
        long_path = 'C:/folder/' + 'long-folder-name/' * 80 + 'request.txt'
        self.ws.emit('system', {'text': long_path})
        expect(page.locator('#messages')).to_contain_text(long_path)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 320)
        page.route('**/api/submit', lambda route: route.fulfill(
            status=400, content_type='application/json', body='{"error":"Wait for the active turn."}'))
        page.locator('#send').click()
        expect(page.locator('#composer-error')).to_have_text('Wait for the active turn.')
        expect(page.locator('#composer')).to_have_value('Keep this first request')
        expect(page.locator('#composer')).to_have_attribute('aria-invalid', 'true')
        self.assertEqual(self.errors, [])

    def test_error_retry_cancel_and_disconnection(self):
        page = self.page
        page.locator('#composer').fill('Retained draft')
        page.route('**/api/submit', lambda route: route.fulfill(
            status=400, content_type='application/json', body='{"error":"Review the selected configuration."}'))
        page.locator('#start-agent').click()
        expect(page.locator('#launch-status')).to_have_text('Review the selected configuration.')
        expect(page.locator('#start-agent')).to_be_enabled()
        expect(page.locator('#composer')).to_have_value('Retained draft')
        self.assertEqual(self.calls, [])
        page.unroute('**/api/submit')
        page.locator('#cancel-launch').click()
        expect(page.locator('#launch-status')).to_contain_text('Cancellation sent')
        self.assertEqual(self.calls, ['n'])
        self.ws.emit('connection', {'state': 'disconnected', 'summary': 'Session ended.'})
        expect(page.locator('#connection')).to_have_text('Session ended')
        expect(page.locator('#send')).to_be_disabled()
        expect(page.locator('#start-agent')).to_be_disabled()
        expect(page.locator('#composer')).to_have_value('Retained draft')
        self.assertEqual(self.errors, [])

    def test_unavailable_runtime_never_enables_start_or_submit(self):
        self.ws.runtime = None
        self.page.locator('#composer').fill('Keep draft while disconnected')
        expect(self.page.locator('#start-agent')).to_be_disabled()
        expect(self.page.locator('#send')).to_be_disabled()
        expect(self.page.locator('#launch-status')).to_contain_text('Connection unavailable')
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
