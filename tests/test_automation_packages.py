import asyncio
import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from copilot_agent.automation_packages import (
    PackageError, PackageReviewError, estimate_task, inspect_package, prepare_package_run, execute_package,
    _approved_output_path, _relative,
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


class PreflightFailureRunner(FakeRunner):
    calls = 0

    def prepare(self, args):
        raise PolicyError("Dunder reflection is unavailable")

    async def run_async(self, args, approved_hash, process_registry=None):
        type(self).calls += 1
        raise AssertionError("A rejected preflight must not start the package script")


class AutomationPackageTests(unittest.TestCase):
    def test_output_paths_reject_absolute_escape_and_normalized_segments(self):
        for value in ("/outside.txt", "../outside.txt", "reports/../outside.txt",
                      "reports//item.txt", "reports/./item.txt", "reports/", "C:/outside.txt",
                      "C:\\outside.txt", "//server/share.txt"):
            with self.subTest(value=value), self.assertRaises(PackageError):
                _relative(value, "output path")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs" / "one" / "outputs"
            root.mkdir(parents=True)
            self.assertEqual((root / "reports" / "nested" / "result.txt").resolve(),
                             _approved_output_path(root, "reports/nested/result.txt"))
            with self.assertRaises(PackageError):
                _approved_output_path(root, "../two/outputs/report.txt")

    def test_stage_final_argument_is_exact_run_output_root_from_unrelated_cwd(self):
        class FinalArgumentRunner(FakeRunner):
            seen = []
            async def run_async(self, args, approved_hash, process_registry=None):
                root = Path(args["arguments"][-1])
                type(self).seen.append((root, Path(args["working_directory"]),
                                        list(args["read_paths"]), list(args["expected_outputs"]),
                                        list(args["arguments"])))
                target = root / "reports" / "nested" / "result.txt"
                target.write_text("verified", encoding="utf-8")
                return {"status": "completed", "exit_code": 0, "stdout": "", "stderr": ""}

        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                archive = root / "package.zip"
                with tempfile.TemporaryDirectory() as source_dir:
                    source = Path(source_dir) / "source.zip"
                    source.write_bytes(package_bytes())
                    with zipfile.ZipFile(source) as original:
                        manifest = json.loads(original.read("manifest.json"))
                        script = original.read("main.py")
                    nested = "reports/nested/result.txt"
                    manifest["capabilities"]["create_paths"] = ["reports/nested"]
                    manifest["stages"][0]["outputs"] = [nested]
                    manifest["stages"][0]["arguments_list"] = ["stage-marker"]
                    manifest["expected_outputs"] = [nested]
                    manifest["validation"][0]["path"] = nested
                    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
                        output.writestr("manifest.json", json.dumps(manifest))
                        output.writestr("README.md", "Sample bounded package")
                        output.writestr("main.py", script)
                state_dir = root / "state"
                state_dir.mkdir()
                args = {"archive_path": str(archive), "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=2000)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": state_dir, "cancelled": lambda: False}
                prepared = prepare_package_run(args, context, object())
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])
                sibling = root / "workspace" / "runs" / "sibling" / "outputs"
                sibling.mkdir(parents=True)
                unrelated = root / "unrelated"
                unrelated.mkdir()
                previous_cwd = Path.cwd()
                try:
                    os.chdir(unrelated)
                    result = await execute_package(args, context, object(), code_runner_factory=FinalArgumentRunner)
                finally:
                    os.chdir(previous_cwd)
                self.assertEqual("completed", result["status"])
                output_root, working, reads, expected, arguments = FinalArgumentRunner.seen[-1]
                self.assertEqual(Path(result["output_root"]), output_root)
                self.assertEqual(str(output_root), result["output_root"])
                self.assertEqual(["stage-marker", str(output_root)], arguments)
                self.assertNotEqual(unrelated, output_root)
                self.assertNotEqual(working, output_root)
                self.assertNotIn(str(sibling), reads)
                self.assertEqual([str(output_root / nested)], expected)
                self.assertFalse(list(sibling.rglob("result.txt")))
        asyncio.run(run())
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

    def test_package_readme_may_be_listed_and_hash_verified_as_root_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "readme-hash.zip"
            source_path = Path(temp) / "source.zip"
            source_path.write_bytes(package_bytes())
            with zipfile.ZipFile(source_path) as source:
                manifest = json.loads(source.read("manifest.json"))
                readme = source.read("README.md")
                main = source.read("main.py")
            manifest["files"]["README.md"] = hashlib.sha256(readme).hexdigest()
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("README.md", readme)
                archive.writestr("main.py", main)

            inspected = inspect_package(path)

            self.assertEqual("passed", inspected["review"]["status"])
            self.assertEqual(hashlib.sha256(readme).hexdigest(), inspected["manifest"]["files"]["README.md"])

    def test_package_review_reports_independent_failures_together(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "package.zip"
            source = package_bytes()
            valid_path = Path(temp) / "valid-package.zip"
            valid_path.write_bytes(source)
            with zipfile.ZipFile(valid_path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                readme = archive.read("README.md")
                main = archive.read("main.py")
            manifest["entrypoint"] = "missing-start-step"
            manifest["files"]["main.py"] = "0" * 64
            second_stage = dict(manifest["stages"][0], id="second", depends_on=[])
            manifest["stages"].append(second_stage)
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("README.md", readme)
                archive.writestr("main.py", main)
                archive.writestr("integrity-manifest.json", "unlisted extra")

            with self.assertRaises(PackageReviewError) as caught:
                inspect_package(path)

            report = caught.exception.report
            failed = {item["item"] for item in report["failures"]}
            self.assertEqual("failed", report["status"])
            self.assertTrue({"File list and contents match", "ZIP contents are all accounted for",
                             "Starting workflow step", "Workflow output files"} <= failed)
            self.assertIn("was reviewed but not run", report["summary"])
            self.assertTrue(report["future_review_options"])

    def test_package_allows_directory_scoped_outputs_and_script_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp:
            original = Path(temp) / "original.zip"
            original.write_bytes(package_bytes())
            with zipfile.ZipFile(original) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                payloads = {name: archive.read(name) for name in archive.namelist()
                            if name not in {"manifest.json", "README.md"}}
                readme = archive.read("README.md")
            manifest["entrypoint"] = "main.py"
            manifest["capabilities"]["read_paths"] = []
            manifest["stages"][0]["permissions"] = ["create_files"]
            manifest["capabilities"]["create_paths"] = ["reports"]
            manifest["stages"][0]["outputs"] = ["reports/result.txt"]
            manifest["expected_outputs"] = ["reports/result.txt"]
            manifest["validation"][0]["path"] = "reports/result.txt"
            path = Path(temp) / "directory-scope.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("README.md", readme)
                for name, data in payloads.items():
                    archive.writestr(name, data)

            result = inspect_package(path)

            self.assertEqual("validated", result["status"])
            self.assertEqual("generate", result["manifest"]["entrypoint_stage_id"])
            self.assertEqual("passed", result["review"]["status"])

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

    def test_run_result_includes_failed_stage_detail_and_marks_preflight_as_not_started(self):
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archive = root / "package.zip"
                archive.write_bytes(package_bytes())
                state_dir = root / "state"
                state_dir.mkdir()
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                config = SimpleNamespace(automation_max_runtime_seconds=60,
                    automation_max_stages=10, automation_max_parallel_stages=2,
                    automation_max_output_chars=2000)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": state_dir, "cancelled": lambda: False}
                prepared = prepare_package_run(args, context, object())
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])
                PreflightFailureRunner.calls = 0

                result = await execute_package(args, context, object(),
                                               code_runner_factory=PreflightFailureRunner)

                self.assertEqual("failed", result["status"])
                self.assertEqual(["generate"], result["failed_stages"])
                self.assertEqual("Dunder reflection is unavailable",
                                 result["stage_results"][0]["error"])
                self.assertFalse(result["stage_results"][0]["side_effects_uncertain"])
                self.assertIn("no package steps completed", result["summary"])
                self.assertIn("Failed step(s): generate", result["summary"])
                self.assertNotIn("All four stages completed", result["summary"])
                self.assertEqual(0, PreflightFailureRunner.calls)
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
