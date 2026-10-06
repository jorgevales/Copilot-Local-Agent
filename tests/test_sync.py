import asyncio
import tempfile
import unittest
from pathlib import Path
from copilot_agent.sync import CreatedSync


class SyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_baseline_does_not_count_existing_output(self):
        root=Path(tempfile.mkdtemp(prefix="copilot_sync_test_"))
        (root/"old.txt").write_text("old")
        watcher=CreatedSync(root,stable_seconds=.05,poll_interval=.05)
        baseline=watcher.baseline()
        self.assertEqual((await watcher.poll(baseline,timeout=.15))["status"],"timeout")
        (root/"new.txt").write_text("new")
        result=await watcher.poll(baseline,expected_names=["new.txt"],timeout=.5)
        self.assertEqual(result["status"],"synchronized")
        self.assertEqual(result["files"][0]["name"],"new.txt")

    async def test_ambiguity_and_missing_directory(self):
        root=Path(tempfile.mkdtemp(prefix="copilot_sync_test_"))
        watcher=CreatedSync(root,stable_seconds=.05,poll_interval=.05)
        baseline=watcher.baseline()
        for name in ["one.txt","two.txt"]: (root/name).write_text(name)
        self.assertEqual((await watcher.poll(baseline,timeout=.5))["status"],"ambiguous")
        self.assertEqual((await CreatedSync(root/"missing").poll({},timeout=.1))["status"],"missing_directory")

    async def test_changed_file_must_settle(self):
        root=Path(tempfile.mkdtemp(prefix="copilot_sync_test_"))
        watcher=CreatedSync(root,stable_seconds=.15,poll_interval=.05)
        baseline=watcher.baseline()
        path=root/"growing.txt"
        path.write_text("one")
        async def change():
            await asyncio.sleep(.1)
            path.write_text("longer two")
        task=asyncio.create_task(change())
        result=await watcher.poll(baseline,timeout=.7,expected_names=["growing.txt"])
        await task
        self.assertEqual(result["status"],"synchronized")
        self.assertEqual(result["files"][0]["size"],len("longer two"))

    async def test_candidate_cap_fails_closed(self):
        root=Path(tempfile.mkdtemp(prefix="copilot_sync_test_"))
        watcher=CreatedSync(root,max_candidates=1)
        for name in ["one.txt","two.txt"]: (root/name).write_text(name)
        self.assertEqual((await watcher.poll({},timeout=.1))["status"],"candidate_limit")
