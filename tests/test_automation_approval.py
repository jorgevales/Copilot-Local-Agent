import asyncio
import hashlib
import tempfile
import time
import unittest

from copilot_agent.approvals import ApprovalManager
from copilot_agent.state import SessionState


class QuietFeedback:
    def section(self, *args):
        pass

    def record(self, *args, **kwargs):
        pass

    def emit(self, *args, **kwargs):
        pass


class RecordingFeedback(QuietFeedback):
    def __init__(self):
        self.emitted = []

    def emit(self, category, text, **kwargs):
        self.emitted.append(str(text))


class AutomationApprovalTests(unittest.TestCase):
    def test_all_numeric_package_choices_match_the_displayed_terminal_options(self):
        async def run():
            for fresh in (False, True):
                for choice in ('1', '2', '3', '4'):
                    with self.subTest(fresh=fresh, choice=choice), tempfile.TemporaryDirectory() as temp:
                        state = SessionState(temp)
                        manager = ApprovalManager(state, lambda preview: choice, QuietFeedback())
                        call = {'call_id': 'package', 'name': 'automation.run', 'arguments': {}}
                        plan = {'tool_requests': [call]}
                        prepared = {'approval_scope_type': 'automation_package',
                                    'requires_fresh_run_confirmation': fresh}
                        allowed, _ = await manager.request(plan, call, prepared)
                        self.assertEqual(choice != '1', allowed)
        asyncio.run(run())

    def test_session_grant_covers_later_automatically_inspected_package_runs(self):
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                state = SessionState(temp)
                seen = []
                def decide(preview):
                    seen.append(preview)
                    return "session" if len(seen) == 1 else "deny"
                manager = ApprovalManager(state, decide, QuietFeedback())

                def package_plan(run_id, digest):
                    plan = {"tool_requests": [{"call_id": run_id, "name": "automation.run",
                                               "arguments": {"workspace": "C:/proof/work"}}],
                            "risk_summary": "Reviewed package run"}
                    scope = {"approval_scope_type": "automation_package", "package_id": run_id,
                             "archive_sha256": digest, "manifest_sha256": "b" * 64,
                             "workspace": "C:/proof/work", "python_stages": [], "tool_stages": [
                                 {"stage_id": "discover", "tool_id": "browser.tabs", "arguments": {"op": "open"}}],
                             "requires_fresh_run_confirmation": False,
                             "capabilities": {"modify_paths": ["C:/project/notes.md"]},
                             "expected_outputs": [], "resource_limits": {"max_runtime_seconds": 30}}
                    return plan, plan["tool_requests"][0], scope

                first = package_plan("first", "a" * 64)
                self.assertTrue((await manager.request(*first))[0])
                second = package_plan("second", "c" * 64)
                self.assertTrue((await manager.request(*second))[0])
                self.assertEqual(1, len(seen), "a session grant should not ask again for another reviewed package")
                self.assertEqual("automation_package", seen[0]["approval_scope_type"])
                self.assertIn("session", seen[0]["choices"])

                manager.revoke_session_grants()
                third = package_plan("revoked", "d" * 64)
                self.assertFalse((await manager.request(*third))[0],
                                 "revoking the local session grant must require fresh approval")
                self.assertEqual(2, len(seen))

                next_session = ApprovalManager(state, lambda preview: seen.append(preview) or "deny", QuietFeedback())
                fourth = package_plan("fourth", "e" * 64)
                self.assertFalse((await next_session.request(*fourth))[0],
                                 "a new local agent session must not inherit a package grant")
                self.assertEqual(3, len(seen))

        asyncio.run(run())

    def test_session_grant_covers_freshly_inspected_bounded_python_packages(self):
        from pathlib import Path
        from copilot_agent.automation_packages import prepare_package_run
        from copilot_agent.policy import PathPolicy
        from copilot_agent.tools import ToolRegistry
        from tests.test_automation_packages import write_python_package

        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                state = SessionState(root / 'session')
                seen = []
                manager = ApprovalManager(state, lambda preview: seen.append(preview) or '4', QuietFeedback())
                scopes = []
                for number in (1, 2):
                    archive = write_python_package(root / f'package-{number}.zip', f"print({number})\n")
                    args = {'archive_path': str(archive),
                            'expected_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                            'workspace': str(root / 'workspace')}
                    scope = prepare_package_run(args, {'path_policy': PathPolicy([str(root)]),
                                                      'session_dir': state.directory}, ToolRegistry())
                    scopes.append(scope)
                    call = {'call_id': f'run-{number}', 'name': 'automation.run', 'arguments': args}
                    self.assertFalse(scope['requires_fresh_run_confirmation'])
                    self.assertTrue((await manager.request({'tool_requests': [call]}, call, scope))[0])
                self.assertEqual(1, len(seen))
                self.assertNotEqual(scopes[0]['package_plan_hash'], scopes[1]['package_plan_hash'])
        asyncio.run(run())

    def test_session_grant_cannot_approve_consequential_package_stages(self):
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                state = SessionState(temp)
                seen = []
                feedback = RecordingFeedback()
                manager = ApprovalManager(
                    state,
                    lambda preview: seen.append(preview) or ("session" if len(seen) == 1 else "deny"),
                    feedback,
                )

                def request(run_id, tool_id, fresh, python_stage_reviews=None):
                    plan = {"tool_requests": [{"call_id": run_id, "name": "automation.run",
                                               "arguments": {"workspace": "C:/proof/work"}}],
                            "risk_summary": "Reviewed exact package run"}
                    call = plan["tool_requests"][0]
                    prepared = {"approval_scope_type": "automation_package", "package_id": run_id,
                                "archive_sha256": run_id[0] * 64, "manifest_sha256": "b" * 64,
                                "workspace": "C:/proof/work", "tool_stages": [
                                    {"stage": "action", "tool": tool_id, "arguments": {"selector": "#submit"}}],
                                "python_stages": [], "capabilities": {}, "expected_outputs": [],
                                "resource_limits": {}, "requires_fresh_run_confirmation": fresh,
                                "python_stage_reviews": python_stage_reviews or []}
                    return manager.request(plan, call, prepared)

                self.assertTrue((await request("safe", "browser.open", False))[0])
                self.assertTrue((await request("file-edit", "files.replace", False))[0],
                                "session grant covers a hash-bound edit inside already approved roots")
                self.assertEqual(1, len(seen), "bounded file edits should not require a new package confirmation")
                self.assertFalse((await request("effect", "browser.click", True))[0])
                self.assertEqual(2, len(seen), "the session grant must not auto-approve browser.click")
                self.assertEqual(["deny", "once", "plan", "session"], seen[1]["choices"])
                self.assertIn("Fresh confirmation", seen[1]["approval_scope"])
                self.assertFalse((await request("submit", "browser.press", True))[0])
                self.assertEqual(3, len(seen), "the session grant must not auto-approve submit-capable browser.press")
                self.assertEqual(["deny", "once", "plan", "session"], seen[2]["choices"])
                source = "print('exact package code')\n"
                digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
                reviews = [{"stage": "generate", "path": "main.py", "sha256": digest, "script": source}]
                self.assertFalse((await request("python", "package-python", True, reviews))[0])
                self.assertEqual(4, len(seen), "the session grant must not authorize package Python")
                self.assertEqual(["deny", "once", "plan", "session"], seen[3]["choices"])
                emitted = "\n".join(feedback.emitted)
                self.assertIn("EXACT PACKAGE PYTHON STAGE generate", emitted)
                self.assertIn(digest, emitted)
                self.assertIn(source, emitted)

        asyncio.run(run())

    def test_one_review_covers_exact_package_scope_and_expires(self):
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                state = SessionState(temp)
                seen = []
                manager = ApprovalManager(state, lambda preview: seen.append(preview) or "plan", QuietFeedback())
                plan = {"tool_requests": [{"call_id": "run-1", "name": "automation.run",
                                           "arguments": {"workspace": "C:/proof/work"}}],
                        "risk_summary": "Exact package run"}
                call = plan["tool_requests"][0]
                scope = {"approval_scope_type": "automation_package", "package_id": "sample",
                         "archive_sha256": "a" * 64, "manifest_sha256": "b" * 64,
                         "workspace": "C:/proof/work", "python_stages": [], "tool_stages": [],
                         "capabilities": {"create_paths": ["out.txt"]}, "expected_outputs": ["out.txt"],
                         "resource_limits": {"max_runtime_seconds": 30}}
                allowed, _ = await manager.request(plan, call, scope)
                self.assertTrue(allowed)
                self.assertEqual("automation_package", seen[0]["approval_scope_type"])
                self.assertIn("plan", seen[0]["choices"])
                record = state.data["approvals"][seen[0]["plan_hash"]]
                self.assertGreater(record["expires_at"], time.time())
                record["expires_at"] = time.time() - 1
                decisions = []
                renewed = ApprovalManager(state, lambda preview: decisions.append(preview) or "once", QuietFeedback())
                approved, _ = await renewed.request(plan, call, scope)
                self.assertTrue(approved)
                self.assertEqual(1, len(decisions), "expired package plan must be reviewed again")
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
