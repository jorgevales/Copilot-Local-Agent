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
            def submit(self, text, attachments=()):
                calls.append(text)
                gate.wait(10)

        self.ws.runtime = Runtime()
        self.ws.capabilities = {'stop': True, 'attach': True, 'new_session': True}
        self.ws.emit('status', {'state': 'awaiting_input',
                               'summary': '[User] Start fast discovery session: scoped read-only tools and useful S: knowledge saves run immediately; one prefilled login-button click is allowed; new targets, other writes and target changes need approval; MFA stays manual [Y/n]? '})
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
                         'composer-hint composer-error attachment-status')
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
        expect(page.locator('#outbox')).to_contain_text('Failed: Wait for the active turn.')
        expect(page.locator('#outbox')).to_contain_text('Keep this first request')
        expect(page.locator('#composer')).to_have_value('')
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
        self.gate.set()
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

    def ready_for_steering(self):
        self.page.locator('#start-agent').click()
        self.gate.set()
        self.ws.emit('status', {'state': 'awaiting_input', 'summary': 'You: '})
        self.page.locator('#composer').fill('Continue this session')
        expect(self.page.locator('#launch-card')).to_be_hidden()
        expect(self.page.locator('#send')).to_be_enabled()

    def test_live_composer_and_attachments_accept_up_to_twenty(self):
        page = self.page
        self.ready_for_steering()
        self.ws.busy = True
        self.ws.emit('status', {'state': 'action_active', 'summary': 'Agent is working.'})
        expect(page.locator('#send')).to_be_enabled()
        expect(page.locator('#composer-hint')).to_contain_text('Send another message to steer')
        self.assertEqual('Add files to this message', page.locator('#attach').get_attribute('aria-label'))

        uploaded, submitted = [], []
        def attach_route(route):
            payload = route.request.post_data_json
            uploaded.append(payload)
            route.fulfill(status=200, content_type='application/json',
                          body='{"attachment_id":"att-%s","name":"%s","size":%s,"kind":"text"}' %
                          (len(uploaded), payload['name'], payload['size']))
        def submit_route(route):
            submitted.append(route.request.post_data_json)
            route.fulfill(status=200, content_type='application/json', body='{"ok":true}')
        page.route('**/api/attachments', attach_route)
        page.route('**/api/submit', submit_route)

        page.locator('#file-input').set_input_files(
            {'name': 'résumé.txt', 'mimeType': 'text/plain', 'buffer': b'one'})
        expect(page.locator('#attachments .attachment-chip')).to_have_count(1)
        expect(page.locator('#attachments')).to_contain_text('résumé.txt')
        page.get_by_role('button', name='Remove attachment résumé.txt').click()
        expect(page.locator('#attachments .attachment-chip')).to_have_count(0)
        files = [{'name': f'Folder résumé {i}.txt', 'mimeType': 'text/plain', 'buffer': b'hello'}
                 for i in range(19)]
        page.locator('#file-input').set_input_files(files)
        expect(page.locator('#attachments .attachment-chip')).to_have_count(19)
        expect(page.locator('#attachment-status')).to_contain_text('19 of 20')
        page.locator('#file-input').set_input_files(
            {'name': 'another.txt', 'mimeType': 'text/plain', 'buffer': b'x'})
        expect(page.locator('#attachments .attachment-chip')).to_have_count(20)
        expect(page.locator('#attachment-status')).to_contain_text('20 of 20')
        expect(page.locator('#send')).to_be_enabled()
        page.locator('#composer').fill('Steer this same run')
        page.locator('#send').click()
        expect(page.locator('#outbox')).to_contain_text('Received by the active run')
        self.assertEqual(20, len(uploaded))
        self.assertEqual([f'Folder résumé {i}.txt' for i in range(19)],
                         [item['name'] for item in uploaded[:19]])
        self.assertEqual('Steer this same run', submitted[0]['text'])
        self.assertEqual(20, len(submitted[0]['attachment_ids']))
        self.assertTrue(submitted[0]['client_message_id'])
        expect(page.locator('#composer')).to_have_value('')
        self.assertEqual([], self.errors)

    def test_rapid_steering_messages_preserve_order(self):
        page = self.page
        self.ready_for_steering()
        self.ws.busy = True
        self.ws.emit('status', {'state': 'action_active', 'summary': 'Agent is working.'})
        submitted = []
        def submit_route(route):
            submitted.append(route.request.post_data_json)
            route.fulfill(status=200, content_type='application/json', body='{"ok":true}')
        page.route('**/api/submit', submit_route)
        page.locator('#composer').fill('First correction')
        page.locator('#send').click()
        page.locator('#composer').fill('Second detail')
        page.locator('#send').click()
        expect(page.locator('.outbox-item.received')).to_have_count(2)
        self.assertEqual(['First correction', 'Second detail'], [item['text'] for item in submitted])
        self.assertEqual(2, len({item['client_message_id'] for item in submitted}))
        self.assertEqual([], self.errors)

    def test_retry_reuses_stable_message_identity(self):
        page = self.page
        self.ready_for_steering()
        attempts = []
        def submit_route(route):
            attempts.append(route.request.post_data_json['client_message_id'])
            if len(attempts) == 1:
                route.fulfill(status=503, content_type='application/json', body='{"error":"Temporary failure"}')
            else:
                route.fulfill(status=200, content_type='application/json', body='{"ok":true}')
        page.route('**/api/submit', submit_route)
        page.locator('#composer').fill('Retry this steering message')
        page.locator('#send').click()
        expect(page.locator('.outbox-item.failed')).to_contain_text('Temporary failure')
        page.get_by_role('button', name='Retry').click()
        expect(page.locator('.outbox-item.received')).to_contain_text('Retry this steering message')
        self.assertEqual(2, len(attempts))
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual([], self.errors)

    def test_twenty_one_file_precheck_keeps_message_and_files(self):
        page = self.page
        self.ready_for_steering()
        files = [{'name': f'file-{i}.txt', 'mimeType': 'text/plain', 'buffer': b'x'}
                 for i in range(21)]
        page.locator('#file-input').set_input_files(files)
        page.locator('#composer').fill('Keep this draft')
        expect(page.locator('#attachment-status')).to_contain_text('21 files selected')
        expect(page.locator('#attachment-status')).to_contain_text('remove 1')
        expect(page.locator('#send')).to_be_disabled()
        expect(page.locator('#composer')).to_have_value('Keep this draft')
        expect(page.locator('#attachments .attachment-chip')).to_have_count(21)
        self.assertEqual([], self.errors)


if __name__ == '__main__':
    unittest.main()
