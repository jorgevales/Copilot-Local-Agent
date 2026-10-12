import asyncio
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from copilot_agent.automation_packages import (
    PackageError, estimate_task, inspect_package, prepare_package_run, execute_package,
)
from copilot_agent.policy import PathPolicy, PolicyError


def package_bytes(script="print('ok')", version="1.0.0"):
    source = script.encode("utf-8")
    manifest = {
        "schema_version": "1.0", "package_id": "sample", "package_version": version,
        "task_id": "test", "correlation_id": "test-1", "description": "Generate one verified output",
        "entrypoint": "generate", "files": {"main.py": hashlib.sha256(source).hexdigest()},
        "dependencies": {"python_min": "3.8", "modules": []}, "tools": [],
        "capabilities": {"read_paths": ["main.py"], "create_paths": ["result.txt"],
                         "modify_paths": [], "network_destinations": [], "imports": [],
                         "permissions": ["read_files", "create_files"], "max_runtime_seconds": 20,
                         "max_output_chars": 2000, "max_concurrency": 1},
        "stages": [{"id": "generate", "kind": "python", "script": "main.py", "depends_on": [],
                    "inputs": [], "outputs": ["result.txt"], "timeout_seconds": 5, "retries": 0,
                    "idempotent": True, "checkpoint": True, "imports": [],
                    "network_destinations": [], "permissions": ["read_files", "create_files"]}],
        "validation": [{"kind": "exists", "path": "result.txt"}],
        "expected_outputs": ["result.txt"],
        "result_contract": {"status": "complete", "summary": "Output verified"},
    }
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "package.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("README.md", "Sample bounded package")
            archive.writestr("main.py", source)
        return path.read_bytes()


class FakeRunner:
    calls = 0

    def __init__(self, policy, session_dir, timeout, output_limit):
        self.policy = policy

    def prepare(self, args):
        return {"proposal_hash": "fake"}

    async def run_async(self, args, approved_hash, process_registry=None):
        type(self).calls += 1
        Path(args["expected_outputs"][0]).write_text("verified", encoding="utf-8")
        return {"status": "completed", "exit_code": 0, "stdout": "", "stderr": ""}


class AutomationPackageTests(unittest.TestCase):
    def test_task_routing_uses_multiple_observable_factors_and_keeps_small_work_direct(self):
        small = estimate_task("Read one file and summarize its title.")
        complex_work = estimate_task("Build a multi-file app with tests, dependencies, checkpoints, retries, and validation.")
        self.assertEqual("direct", small["route"])
        self.assertEqual("package", complex_work["route"])
        self.assertGreaterEqual(complex_work["factors"]["estimated_files"], 3)

    def test_package_inspection_validates_hashes_and_stage_graph(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "package.zip"
            path.write_bytes(package_bytes())
            inspected = inspect_package(path)
            self.assertEqual("validated", inspected["status"])
            self.assertEqual(["generate"], [item["id"] for item in inspected["stages"]])
            path.write_bytes(package_bytes("print('tampered')"))
            with self.assertRaises(PackageError):
                inspect_package(path, inspected["archive_sha256"])

    def test_execution_requires_hash_bound_approval_and_retains_verified_checkpoint(self):
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archive = root / "package.zip"
                archive.write_bytes(package_bytes())
                workspace = root / "workspace"
                state_dir = root / "state"
                state_dir.mkdir()
                args = {"archive_path": str(archive), "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(workspace)}
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                    automation_max_parallel_stages=2, automation_max_output_chars=2000)
                policy = PathPolicy([str(root)])
                context = {"config": config, "path_policy": policy, "session_dir": state_dir,
                           "cancelled": lambda: False}
                prepared = prepare_package_run(args, context, object())
                with self.assertRaises(PolicyError):
                    await execute_package(args, context, object(), code_runner_factory=FakeRunner)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"], approved_hash="changed-scope")
                with self.assertRaises(PolicyError):
                    await execute_package(args, context, object(), code_runner_factory=FakeRunner)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])
                FakeRunner.calls = 0
                result = await execute_package(args, context, object(), code_runner_factory=FakeRunner)
                self.assertEqual("completed", result["status"], (FakeRunner.calls, result, json.loads(Path(result["state_path"]).read_text(encoding="utf-8"))))
                self.assertTrue(result["validation"]["ok"])
                self.assertEqual("verified", Path(result["outputs"][0]["path"]).read_text(encoding="utf-8"))
                self.assertTrue(Path(result["state_path"]).is_file())
                resume = dict(args, resume_run_id=result["run_id"])
                resume_prepared = prepare_package_run(resume, context, object())
                context["package_plan_hash"] = resume_prepared["package_plan_hash"]
                context["approved_hash"] = resume_prepared["package_plan_hash"]
                resumed = await execute_package(resume, context, object(), code_runner_factory=FakeRunner)
                self.assertEqual("completed", resumed["status"])
                self.assertEqual(1, FakeRunner.calls)
        asyncio.run(run())

    def test_package_workspace_must_be_inside_an_allowed_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "package.zip"
            archive.write_bytes(package_bytes())
            policy = PathPolicy([str(root)])
            context = {"config": SimpleNamespace(), "path_policy": policy}
            args = {"archive_path": str(archive), "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "workspace": str(root.parent / "outside")}
            with self.assertRaises((PolicyError, PackageError)):
                prepare_package_run(args, context, object())


if __name__ == "__main__":
    unittest.main()
