"""Private live context, immutable reviews and durable audit never copy customer facts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from copilot_agent.approvals import ApprovalManager
from copilot_agent.config import Config, PROJECT_ROOT
from copilot_agent.feedback import Feedback
from copilot_agent.findings import Findings
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.prompts import PromptBuilder
from copilot_agent.state import SessionState
from copilot_agent.web_privacy import audit_evidence, private_id, private_session_snapshot
from tests.test_orchestrator import MockBrowser, final_response
from tests.test_protocol_state import FixtureRegistry

SENTINEL = "CUSTOMER_PRIVATE_SENTINEL_4d72f9"


class WebPrivacyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="copilot_privacy_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "workspace").mkdir()
        (self.root / "guidance").mkdir()
        (self.root / "schemas").mkdir()
        for source in (PROJECT_ROOT / "guidance").glob("0[1-8]-*.md"):
            (self.root / "guidance" / source.name).write_bytes(source.read_bytes())
        (self.root / "schemas" / "response-v1.schema.json").write_bytes(
            (PROJECT_ROOT / "schemas" / "response-v1.schema.json").read_bytes())
        self.config = Config(root=self.root, profile_dir=self.root / "profile",
                             allowed_roots=[str(self.root / "workspace")],
                             max_context_chars=1200, max_corrections=1, max_tool_rounds=3)
        self.config.validate()
        self.state = SessionState(self.root / "session")
        self.state.data["website_private"] = True
        self.state.save()

    def assert_no_persisted_customer(self):
        for path in self.state.directory.rglob("*"):
            if path.is_file():
                self.assertNotIn(SENTINEL.encode(), path.read_bytes(), str(path))
                self.assertNotIn(SENTINEL, str(path), str(path))

    def test_private_state_messages_calls_metadata_feedback_and_history_are_safe(self):
        self.state.message("user", SENTINEL)
        self.state.data.update(summary=SENTINEL, requirements=[SENTINEL], decisions=[{"fact": SENTINEL}],
                               constraints=[SENTINEL], current_plan=[{"action": SENTINEL}],
                               unresolved_questions=[SENTINEL], retry_records=[{"error": SENTINEL}],
                               attachments=[{"path": str(self.root / (SENTINEL + ".pdf")), "name": SENTINEL}],
                               findings_sync=[{"name": SENTINEL}])
        call = {"call_id": "private-call", "name": "browser.customer_summary", "version": "1.0",
                "arguments": {"identifier": SENTINEL}, "expected_result": SENTINEL}
        self.state.begin_call(call)
        self.state.finish_call("private-call", {"ok": True, "tool": "browser.customer_summary",
                                               "result": {"customer_name": SENTINEL}})
        Feedback(sink=lambda line: None, state=self.state).emit("Copilot", SENTINEL)
        self.state.event("fixture", customer_identifier=SENTINEL)
        self.state.save()
        self.assertEqual(self.state.data["messages"][0]["content"], SENTINEL)
        self.assertEqual(self.state.data["calls"]["private-call"]["result"]["result"]["customer_name"], SENTINEL)
        stored = json.loads(self.state.path.read_text(encoding="utf-8"))
        self.assertTrue(stored["messages"][0]["content"]["website_content_omitted"])
        self.assertTrue(stored["calls"][private_id("private-call")]["request"]["arguments"]["website_content_omitted"])
        self.assert_no_persisted_customer()

    async def test_exact_approval_is_displayed_in_memory_but_only_hashes_persist(self):
        previews = []
        manager = ApprovalManager(self.state, lambda preview: previews.append(copy.deepcopy(preview)) or "once",
                                  Feedback(sink=lambda line: None, state=self.state))
        call = {"call_id": "private-review", "name": "browser.fill", "version": "1.0",
                "arguments": {"selector": "#customer-search", "text": SENTINEL}}
        plan = {"tool_requests": [call], "purpose": SENTINEL}
        allowed, grant = await manager.request(plan, call, {"reviewed_identity": SENTINEL})
        self.assertTrue(allowed)
        self.assertEqual(len(grant), 64)
        self.assertEqual(previews[0]["complete_pending_plan"]["tool_requests"][0]["arguments"]["text"], SENTINEL)
        record = next((self.state.directory / "approvals").glob("*.json"))
        stored = json.loads(record.read_text(encoding="utf-8"))
        self.assertTrue(stored["exact_plan_evidence"]["website_content_omitted"])
        self.assert_no_persisted_customer()

    def test_private_overflow_keeps_live_goal_and_pending_policy_without_attachment(self):
        builder = PromptBuilder(self.config, FixtureRegistry(), self.state, Findings(self.state.directory))
        self.state.data["requirements"] = ["Locate documents for " + SENTINEL]
        self.state.data["summary"] = SENTINEL * 200
        self.state.data["current_plan"] = [{"description": SENTINEL * 30}]
        self.state.data["calls"] = {"pending-private-call": {"status": "uncertain", "state_changing": True,
                                                            "request_hash": "a" * 64, "action_hash": "b" * 64,
                                                            "request": {"arguments": {"customer": SENTINEL}}}}
        for _ in range(2):
            text, attachments = builder.build("tool_results", {"observed_name": SENTINEL}, "private-request")
            message = json.loads(text)
            self.assertTrue(message["context"]["private_context_omitted"])
            self.assertEqual(message["context"]["current_user_request"], "Locate documents for " + SENTINEL)
            self.assertEqual(message["context"]["pending_operations"]["pending-private-call"]["status"], "uncertain")
            self.assertEqual(message["content"]["observed_name"], SENTINEL)
            self.assertLessEqual(len(json.dumps(message["context"], ensure_ascii=False)), self.config.max_context_chars)
            self.assertNotIn(builder.context_file, attachments)
        self.assertFalse(builder.context_file.exists())
        self.assertFalse((self.state.directory / ".history" / builder.context_file.name).exists())
        self.state.save()
        self.assert_no_persisted_customer()

    def test_small_context_budget_preserves_explicit_unresolved_boundary(self):
        builder = PromptBuilder(self.config, FixtureRegistry(), self.state, Findings(self.state.directory))
        self.config.max_context_chars = 250
        self.state.data["requirements"] = [SENTINEL * 100]
        self.state.data["calls"] = {"call-" + str(index): {"status": "uncertain", "state_changing": True,
                                                         "request_hash": "a" * 64, "action_hash": "b" * 64}
                                    for index in range(30)}
        text, attachments = builder.build("tool_results", {"request": SENTINEL}, "private-budget")
        context = json.loads(text)["context"]
        self.assertTrue(context["private_context_omitted"])
        self.assertTrue(context["requires_local_reconciliation"])
        self.assertEqual(context["pending_operations_count"], 30)
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False)), 250)
        self.assertNotIn(builder.context_file, attachments)
        self.assertFalse(builder.context_file.exists())

    async def test_orchestrator_raw_user_and_copilot_envelopes_stay_ephemeral(self):
        registry = FixtureRegistry()
        browser = MockBrowser([final_response, lambda message: final_response(message, user_response=SENTINEL)])
        engine = Orchestrator(self.config, browser, registry, self.state, display=lambda message: None)
        self.assertTrue(self.state.data["website_private"])
        self.assertTrue(browser.website_private)
        await engine.initialize()
        result = await engine.turn("Read the authorized profile for " + SENTINEL)
        self.assertEqual(result["user_response"], SENTINEL)
        self.assertEqual(self.state.data["summary"].split("\n")[-1], SENTINEL)
        self.assertIn(SENTINEL, json.dumps(browser.sent[-1]["message"]))
        self.assert_no_persisted_customer()
        for path in (self.state.directory / "responses").glob("*.txt"):
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["website_content_omitted"])

    def test_restarted_session_has_audit_identity_and_no_customer_fact_replay(self):
        self.state.message("user", SENTINEL)
        self.state.data["summary"] = SENTINEL
        self.state.save()
        restored = SessionState(self.state.directory, resume=True)
        self.assertEqual(restored.session_id, self.state.session_id)
        self.assertEqual(restored.data["summary"], "")
        self.assertNotIn(SENTINEL, json.dumps(restored.context()))
        self.assert_no_persisted_customer()

    def test_audit_hash_changes_without_exposing_content(self):
        first = audit_evidence({"customer_name": SENTINEL})
        second = audit_evidence({"customer_name": SENTINEL + "-different"})
        self.assertNotEqual(first["content_sha256"], second["content_sha256"])
        self.assertNotIn(SENTINEL, json.dumps(first))

    def test_untrusted_correlation_labels_are_hashed_and_idempotent_on_restart(self):
        self.state.data["response_ids"] = [SENTINEL]
        call = {"call_id": SENTINEL, "name": "browser.read", "version": "1.0", "arguments": {}}
        self.state.begin_call(call, state_changing=False)
        self.state.finish_call(SENTINEL, {"ok": True, "result": {"text": "Observed generic text"}})
        self.state.save()
        stored = json.loads(self.state.path.read_text(encoding="utf-8"))
        alias = private_id(SENTINEL)
        self.assertEqual(stored["response_ids"], [alias])
        self.assertEqual(set(stored["calls"]), {alias})
        self.assertEqual(stored["calls"][alias]["request"]["call_id"], alias)
        restored = SessionState(self.state.directory, resume=True)
        restored.save()
        self.assertEqual(json.loads(restored.path.read_text(encoding="utf-8"))["response_ids"], [alias])
        self.assertEqual(private_id(alias), alias)
        self.assert_no_persisted_customer()

    def test_original_audit_digest_survives_repeated_resume_and_save(self):
        self.state.message("user", SENTINEL)
        arguments = {"customer": SENTINEL}
        result = {"ok": False, "tool": "browser.plan", "error": {"code": "timeout", "message": SENTINEL}}
        self.state.begin_call({"call_id": "stable-evidence", "name": "browser.plan", "version": "1.0", "arguments": arguments})
        self.state.finish_call("stable-evidence", result)
        self.state.data["attachments"] = [{"name": SENTINEL}]
        self.state.save()
        alias = private_id("stable-evidence")
        for _ in range(3):
            restored = SessionState(self.state.directory, resume=True)
            restored.save()
            stored = json.loads(restored.path.read_text(encoding="utf-8"))
            self.assertEqual(stored["messages"][0]["content"], audit_evidence(SENTINEL))
            self.assertEqual(stored["calls"][alias]["request"]["arguments"], audit_evidence(arguments))
            self.assertEqual(stored["calls"][alias]["result"], audit_evidence(result))
            self.assertEqual(stored["attachments"], [audit_evidence({"name": SENTINEL})])
        self.assert_no_persisted_customer()

    def test_forged_evidence_cannot_preserve_raw_fields_wrong_types_or_secret_error_code(self):
        base = {"content_sha256": "a" * 64, "content_bytes": 1, "website_content_omitted": True}
        for changed in ({"raw_customer": SENTINEL}, {"content_sha256": SENTINEL}, {"content_bytes": True},
                        {"ok": SENTINEL}, {"tool": SENTINEL}, {"tool": [SENTINEL]}, {"error": {"code": SENTINEL}},
                        {"error": {"code": "timeout", "message": SENTINEL}}):
            candidate = dict(base, **changed)
            snapshot = private_session_snapshot({"messages": [{"role": "user", "content": candidate}]})
            evidence = snapshot["messages"][0]["content"]
            self.assertNotEqual(evidence["content_sha256"], "a" * 64)
            self.assertNotIn(SENTINEL, json.dumps(snapshot))


if __name__ == "__main__":
    unittest.main()
