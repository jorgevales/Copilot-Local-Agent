"""Shared website capabilities and reviewed file queues across actual orchestrator sends.

Transport is mocked: these tests prove local scope/commit/cancellation contracts,
not live Copilot UI upload acceptance.
"""
import hashlib
import json
from pathlib import Path
import threading
import unittest

from copilot_agent.browser import CaptureTimeoutError, SubmissionNotSentError
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.policy import PolicyError
from copilot_agent.tools import ToolRegistry
from tests.test_orchestrator import MockBrowser, final_response, tool_response
from tests.test_protocol_state import encoded, make_fixture
from tests.test_web_documents import FakeContext, FakePage


class WebTransportTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, responders=None, registry=None, stop=None):
        root, config, state, fixture_registry = make_fixture("web-transport-")
        config.storage_dir = root / "workspace"
        config.allowed_domains = ["fixture.test"]
        browser = MockBrowser([final_response] if responders is None else responders)
        registry = registry or ToolRegistry()
        engine = Orchestrator(config, browser, registry, state, approval_decider=lambda preview: "once",
                              display=lambda message: None, cancel_event=stop)
        return root, config, state, registry, browser, engine

    async def queue_file(self, root, registry, engine):
        source = root / "workspace" / "reviewed-document.txt"
        content = b"Authorized synthetic website document bytes.\n"
        source.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        context = dict(engine.base_context, approved=True)
        result = await registry.execute("files.transfer_to_copilot", {"files": [{"path": str(source), "sha256": digest}]}, context)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["status"], "queued")
        self.assertFalse(result["result"]["delivery_verified"])
        self.assertEqual(engine.base_context["pending_file_attachments"], [source])
        self.assertEqual(engine.approved_attachment_hashes[str(source)], digest)
        return source, content, digest

    async def test_registered_document_discovery_tickets_survive_cloned_call_contexts(self):
        root, config, state, registry, browser, engine = self.fixture()
        native = root / "workspace" / "native"
        native.mkdir()
        isolated = FakeContext(native)
        page = FakePage(isolated, True)
        page.links = [{"key": 1, "href": "https://fixture.test/documents/report.pdf?signature=PRIVATE_SIGNATURE",
                       "download": None, "label": "Report"}]
        isolated.pages.append(page)
        isolated.browser = browser
        browser.tool_context, browser.tool_page = isolated, page
        browser.tool_domains = {"fixture.test"}
        engine.base_context["approved_domains"].append("fixture.test")
        first_context = dict(engine.base_context)
        first = await registry.execute("browser.documents", {}, first_context)
        self.assertTrue(first["ok"], first)
        first_id = first["result"]["documents"][0]["document_id"]
        second_context = dict(engine.base_context)
        self.assertIs(first_context["web_document_tickets"], second_context["web_document_tickets"])
        self.assertIn(first_id, second_context["web_document_tickets"])
        second = await registry.execute("browser.documents", {}, second_context)
        self.assertTrue(second["ok"], second)
        self.assertEqual(len(engine.base_context["web_document_tickets"]), 2)
        self.assertNotIn("PRIVATE_SIGNATURE", json.dumps(first))
        self.assertEqual(isolated.navigations, [])

    async def test_exact_transfer_queue_drains_only_at_proven_send_commit(self):
        root, config, state, registry, browser, engine = self.fixture()
        await engine.initialize()
        source, content, digest = await self.queue_file(root, registry, engine)
        observed = []
        async def exchange(text, request_id, attachments=(), on_submitted=None):
            self.assertEqual(engine.base_context["pending_file_attachments"], [source])
            self.assertEqual(engine.base_context["transferred_attachment_hashes"], {})
            self.assertEqual(state.message_count, 1)
            self.assertEqual(len(attachments), 1)
            self.assertNotEqual(attachments[0], source)
            self.assertEqual(attachments[0].read_bytes(), content)
            self.assertEqual(hashlib.sha256(attachments[0].read_bytes()).hexdigest(), digest)
            observed.append(Path(attachments[0]))
            on_submitted()
            self.assertEqual(engine.base_context["pending_file_attachments"], [])
            self.assertEqual(engine.base_context["transferred_attachment_hashes"], {digest: 1})
            return encoded(final_response(json.loads(text)))
        browser.exchange = exchange
        await engine._validated_exchange("tool_results", {"instruction": "Read the reviewed document"})
        self.assertEqual(state.message_count, 2)
        self.assertIsNone(state.data["pending_submission"])
        self.assertEqual(len(observed), 1)
        self.assertTrue(observed[0].is_file())

    async def test_changed_reviewed_bytes_block_transport_and_preserve_queue(self):
        root, config, state, registry, browser, engine = self.fixture()
        await engine.initialize()
        source, content, digest = await self.queue_file(root, registry, engine)
        source.write_bytes(content + b"changed")
        with self.assertRaisesRegex(PolicyError, "changed"):
            await engine._send("tool_results", {"instruction": "Do not upload changed files"})
        self.assertEqual(len(browser.sent), 1)
        self.assertEqual(state.message_count, 1)
        self.assertIsNone(state.data["pending_submission"])
        self.assertEqual(engine.base_context["pending_file_attachments"], [source])
        self.assertEqual(engine.base_context["transferred_attachment_hashes"], {})

    async def test_proven_not_sent_preserves_transfer_for_reviewed_retry(self):
        root, config, state, registry, browser, engine = self.fixture(
            [final_response, SubmissionNotSentError("Synthetic send was proven not submitted")])
        await engine.initialize()
        source, content, digest = await self.queue_file(root, registry, engine)
        with self.assertRaises(SubmissionNotSentError):
            await engine._send("tool_results", {"instruction": "Keep queued file if not submitted"})
        self.assertEqual(state.message_count, 1)
        self.assertIsNone(state.data["pending_submission"])
        self.assertEqual(engine.base_context["pending_file_attachments"], [source])
        self.assertEqual(engine.base_context["transferred_attachment_hashes"], {})

    async def test_capture_timeout_after_commit_does_not_requeue_or_claim_new_upload(self):
        root, config, state, registry, browser, engine = self.fixture()
        await engine.initialize()
        source, content, digest = await self.queue_file(root, registry, engine)
        async def exchange(text, request_id, attachments=(), on_submitted=None):
            on_submitted()
            raise CaptureTimeoutError("Synthetic response capture failed after proven submission")
        browser.exchange = exchange
        with self.assertRaises(CaptureTimeoutError):
            await engine._send("tool_results", {"instruction": "Never automatically resend committed attachment"})
        self.assertEqual(state.message_count, 2)
        self.assertIsNone(state.data["pending_submission"])
        self.assertEqual(engine.base_context["pending_file_attachments"], [])
        self.assertEqual(engine.base_context["transferred_attachment_hashes"], {digest: 1})

    async def test_ui_stop_event_reaches_tool_context_and_prevents_next_actions(self):
        stop = threading.Event()
        root, config, state, fixture_registry = make_fixture("web-transport-stop-")
        def cancel_after_response(message):
            stop.set()
            return tool_response(message, "cancelled-call", "synthetic.read")
        browser = MockBrowser([final_response, cancel_after_response])
        engine = Orchestrator(config, browser, fixture_registry, state, display=lambda line: None, cancel_event=stop)
        self.assertIs(engine.base_context["cancel_event"], stop)
        self.assertFalse(engine.base_context["cancelled"]())
        await engine.initialize()
        result = await engine.turn("Cancel before the proposed tool can execute")
        self.assertTrue(engine.base_context["cancelled"]())
        self.assertEqual(result["completion_status"], "blocked")
        self.assertEqual(state.data["status"], "cancelled")
        self.assertEqual(fixture_registry.calls, [])
        self.assertEqual(state.data["calls"], {})
        self.assertEqual(len(browser.sent), 2)


if __name__ == "__main__":
    unittest.main()
