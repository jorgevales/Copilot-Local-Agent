import asyncio
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


class AutomationApprovalTests(unittest.TestCase):
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
