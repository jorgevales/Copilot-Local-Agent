import asyncio
import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from copilot_agent.automation_packages import (
    PackageError, PackageReviewError, estimate_task, inspect_package, prepare_package_run, execute_package,
    _approved_output_path, _package_requires_fresh_confirmation, _relative,
)
from copilot_agent.policy import PathPolicy, PolicyError
from copilot_agent.state import canonical_hash
from copilot_agent.tools import ToolRegistry
from copilot_agent.protocol import validate_schema


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


def write_tool_package(path, registry, stages, *, package_id="tool-stage-test"):
    payload = b"pass\n"
    tool_ids = list(dict.fromkeys(stage["tool_id"] for stage in stages))
    manifest = {
        "schema_version": "1.0", "package_id": package_id, "package_version": "1.0.0",
        "task_id": package_id, "correlation_id": package_id + "-request",
        "description": "Exercise approved registered tool stages.",
        "entrypoint": stages[0]["id"], "files": {"main.py": hashlib.sha256(payload).hexdigest()},
        "dependencies": {"python_min": "3.8", "modules": []},
        "tools": [{"id": tool_id, "version": registry.definition(tool_id)["version"]}
                  for tool_id in tool_ids],
        "capabilities": {"read_paths": [], "create_paths": [], "modify_paths": [],
                         "network_destinations": [], "imports": [], "permissions": [],
                         "max_runtime_seconds": 60, "max_output_chars": 3000, "max_concurrency": 1},
        "stages": stages, "validation": [], "expected_outputs": [],
        "result_contract": {"status": "complete", "summary": "Tool stages verified"},
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("README.md", "Bounded registered tool test package")
        archive.writestr("main.py", payload)
    return path


def write_python_package(path, script, outputs=("result.txt",), imports=("os", "pathlib", "sys"),
                         *, network_destinations=(), permissions=("read_files", "create_files"), max_concurrency=1):
    source = package_bytes(script)
    with tempfile.TemporaryDirectory() as temp:
        source_path = Path(temp) / "source.zip"
        source_path.write_bytes(source)
        with zipfile.ZipFile(source_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            readme = archive.read("README.md")
            payload = archive.read("main.py")
    outputs = list(outputs)
    manifest["capabilities"].update(create_paths=outputs, imports=list(imports),
                                    network_destinations=list(network_destinations),
                                    permissions=list(permissions), max_concurrency=max_concurrency)
    manifest["expected_outputs"] = outputs
    manifest["validation"] = [{"kind": "exists", "path": item} for item in outputs]
    manifest["stages"][0].update(outputs=outputs, imports=list(imports),
                                 network_destinations=list(network_destinations),
                                 permissions=list(permissions))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("README.md", readme)
        archive.writestr("main.py", payload)
    return Path(path)


async def execute_test_package(root, archive, runner=None, *, cancelled=lambda: False,
                               config_parallelism=2):
    session = root / "session"
    session.mkdir(exist_ok=True)
    config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                             automation_max_parallel_stages=config_parallelism, automation_max_output_chars=2000)
    context = {"config": config, "path_policy": PathPolicy([str(root)]), "session_dir": session,
               "cancelled": cancelled}
    args = {"archive_path": str(archive),
            "expected_sha256": hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
            "workspace": str(root / "workspace")}
    registry = ToolRegistry()
    prepared = prepare_package_run(args, context, registry)
    context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                   approved_hash=prepared["package_plan_hash"])
    result = await execute_package(args, context, registry, code_runner_factory=runner or FakeRunner)
    return result, context


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
    def test_python_min_schema_fixture_matches_major_minor_contract(self):
        schema_root = Path(__file__).resolve().parents[1] / "schemas"
        fixtures = (
            "automation-package-v1.schema.json",
            "automation-package-v1.1.schema.json",
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                manifest_schema = json.loads((schema_root / fixture).read_text(encoding="utf-8"))
                dependencies_schema = manifest_schema["properties"]["dependencies"]
                valid_dependencies = {"python_min": "3.8", "modules": []}
                self.assertEqual([], validate_schema(valid_dependencies, dependencies_schema))

                for invalid_minimum in ("3.8.1", ""):
                    with self.subTest(python_min=invalid_minimum):
                        dependencies = {**valid_dependencies, "python_min": invalid_minimum}
                        self.assertTrue(validate_schema(dependencies, dependencies_schema))

    def test_session_grant_risk_classification_preserves_safe_discovery_and_knowledge(self):
        safe = {"stages": [
            {"kind": "tool", "tool_id": "browser.open", "arguments": {"url": "https://example.com"}},
            {"kind": "tool", "tool_id": "browser.tabs", "arguments": {"operation": "open"}},
            {"kind": "tool", "tool_id": "browser.recon", "arguments": {"tab_id": "tab-a"}},
            {"kind": "tool", "tool_id": "browser.route", "arguments": {"tab_id": "tab-a"}},
            {"kind": "tool", "tool_id": "site_knowledge.bind", "arguments": {}},
            {"kind": "tool", "tool_id": "site_knowledge.save", "arguments": {}},
            {"kind": "tool", "tool_id": "site_knowledge.retrieve", "arguments": {}},
            {"kind": "tool", "tool_id": "discovery.knowledge_save", "arguments": {}},
            {"kind": "tool", "tool_id": "files.append", "arguments": {"path": "existing.txt"}},
            {"kind": "tool", "tool_id": "files.replace", "arguments": {"path": "existing.txt"}},
        ]}
        self.assertFalse(_package_requires_fresh_confirmation(safe))
        self.assertTrue(_package_requires_fresh_confirmation({"stages": [{
            "kind": "tool", "tool_id": "browser.open",
            "arguments": {"url": {"$binding": "observe.step.url"}, "allowed_domains": ["gov.uk"]},
        }]}))
        for tool_id, arguments in (
                ("browser.open", {"url": "https://127.0.0.1/"}),
                ("browser.open", {"url": "https://www.gov.uk/", "allowed_domains": ["service.internal"]}),
                ("browser.tabs", {"operation": "open", "url": "https://10.0.0.8/"})):
            with self.subTest(tool_id=tool_id, arguments=arguments):
                self.assertTrue(_package_requires_fresh_confirmation(
                    {"stages": [{"kind": "tool", "tool_id": tool_id, "arguments": arguments}]}))
        for tool_id, arguments in (
                ("browser.click", {"selector": "#submit"}),
                ("browser.plan", {"steps": [{"op": "click"}]}),
                ("site_knowledge.invalidate", {}),
                ("browser.tabs", {"operation": "reset"}),
                ("browser.tabs", {"operation": {"$binding": "producer.operation"}})):
            with self.subTest(tool_id=tool_id, arguments=arguments):
                self.assertTrue(_package_requires_fresh_confirmation(
                    {"stages": [{"kind": "tool", "tool_id": tool_id, "arguments": arguments}]}))
        self.assertTrue(_package_requires_fresh_confirmation(
            {"stages": [{"kind": "python", "id": "generate", "script": "main.py"}]}))

    def test_result_bound_browser_hosts_reject_private_and_reserved_destinations(self):
        from copilot_agent.automation_packages import _require_public_browser_host

        for host in ("127.0.0.1", "10.0.0.8", "169.254.169.254", "::1",
                     "127.1", "0177.0.0.1", "0x7f.0.0.1", "2130706433",
                     "localhost", "service.internal", "metadata.test"):
            with self.subTest(host=host), self.assertRaises(PolicyError):
                _require_public_browser_host(host)
        _require_public_browser_host("www.gov.uk")

    def test_package_run_preparation_binds_full_python_source_and_hash(self):
        source = "print('review this exact package source')\n"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            archive = root / "python-package.zip"
            archive.write_bytes(package_bytes(source))
            session = root / "session"
            session.mkdir()
            args = {"archive_path": str(archive),
                    "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "workspace": str(root / "workspace")}
            prepared = prepare_package_run(args, {"path_policy": PathPolicy([str(root)]),
                                                   "session_dir": session}, ToolRegistry())

        reviews = prepared["python_stage_reviews"]
        self.assertTrue(prepared["requires_fresh_run_confirmation"])
        self.assertEqual(1, len(reviews))
        self.assertEqual("main.py", reviews[0]["path"])
        self.assertEqual(source, reviews[0]["script"])
        self.assertEqual(hashlib.sha256(source.encode("utf-8")).hexdigest(), reviews[0]["sha256"])

    @unittest.skipUnless(os.name == "nt", "Explicit C: knowledge test store is Windows-specific")
    def test_package_approval_binds_site_knowledge_save_consent_and_readback(self):
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                local = Path(temp).resolve()
                if local.drive.upper() != "C:":
                    self.skipTest("Temporary directory is not on C:")
                appdata = local / "local-app-data"
                test_root = appdata / "CopilotLocalAgent" / "live-navigation-tests"
                test_root.mkdir(parents=True)
                target = test_root / "package-knowledge"
                from copilot_agent.app import configure_local_knowledge_test
                from copilot_agent.config import Config, PROJECT_ROOT
                config = Config(root=PROJECT_ROOT, storage_dir=appdata / "runtime")
                config.manifest_path = True
                config.persistent_graph = True
                config.knowledge_write = True
                config.knowledge_reuse = True
                with patch.dict(os.environ, {"LOCALAPPDATA": str(appdata)}):
                    configure_local_knowledge_test(config, target)
                target.mkdir()

                class Page:
                    url = "https://example.com/home"
                    def __init__(self, browser_context):
                        self.context = browser_context
                    def is_closed(self):
                        return False

                browser_context = object()
                site_page = Page(browser_context)
                browser = SimpleNamespace(tool_page=site_page, tool_context=browser_context,
                                          _tool_pages=[site_page], page=object(), chat_page=object())
                registry = ToolRegistry()
                calls = []
                delegate = registry

                class RecordingRegistry:
                    def definition(self, name):
                        return delegate.definition(name)
                    def validate_input(self, name, arguments):
                        return delegate.validate_input(name, arguments)
                    def validate_call(self, name, arguments, context):
                        return delegate.validate_call(name, arguments, context)
                    async def execute(self, name, arguments, context):
                        result = await delegate.execute(name, arguments, context)
                        calls.append((name, dict(arguments), dict(context), result))
                        return result

                registry = RecordingRegistry()
                from copilot_agent.site_knowledge import KNOWLEDGE_EXAMPLES
                stages = [
                    ("bind", "site_knowledge.bind", KNOWLEDGE_EXAMPLES["site_knowledge.bind"], []),
                    ("save", "site_knowledge.save", KNOWLEDGE_EXAMPLES["site_knowledge.save"], ["bind"]),
                    ("retrieve", "site_knowledge.retrieve", KNOWLEDGE_EXAMPLES["site_knowledge.retrieve"], ["save"]),
                    ("export", "site_knowledge.export", KNOWLEDGE_EXAMPLES["site_knowledge.export"], ["retrieve"]),
                    ("invalidate", "site_knowledge.invalidate", KNOWLEDGE_EXAMPLES["site_knowledge.invalidate"], ["export"]),
                    ("discovery-invalidate", "discovery.knowledge_invalidate",
                     {"origin": "https://example.com", "expected_revision": 0}, ["invalidate"]),
                ]
                payload = b"pass\n"
                manifest = {
                    "schema_version": "1.0", "package_id": "knowledge-roundtrip", "package_version": "1.0.0",
                    "task_id": "knowledge-roundtrip", "correlation_id": "knowledge-roundtrip-1",
                    "description": "Bind, save and verify generic website navigation knowledge.",
                    "entrypoint": "bind", "files": {"main.py": hashlib.sha256(payload).hexdigest()},
                    "dependencies": {"python_min": "3.8", "modules": []},
                    "tools": [{"id": tool_id, "version": delegate.definition(tool_id)["version"]}
                              for _, tool_id, _, _ in stages],
                    "capabilities": {"read_paths": [], "create_paths": [], "modify_paths": [],
                                     "network_destinations": [], "imports": [], "permissions": [],
                                     "max_runtime_seconds": 30, "max_output_chars": 3000, "max_concurrency": 1},
                    "stages": [{"id": stage_id, "kind": "tool", "tool_id": tool_id,
                                "arguments": arguments, "depends_on": depends, "inputs": [], "outputs": [],
                                "timeout_seconds": 10, "retries": 0, "idempotent": False,
                                "checkpoint": True}
                               for stage_id, tool_id, arguments, depends in stages],
                    "validation": [], "expected_outputs": [],
                    "result_contract": {"status": "complete", "summary": "Knowledge saved and read back"},
                }
                archive = target / "knowledge.zip"
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
                    output.writestr("manifest.json", json.dumps(manifest))
                    output.writestr("README.md", "Bounded site knowledge round-trip package")
                    output.writestr("main.py", payload)
                session = target / "session"
                session.mkdir()
                context = {"config": config, "path_policy": PathPolicy([str(target)]),
                           "session_dir": session, "cancelled": lambda: False, "browser": browser,
                           "site_knowledge_bindings": {},
                           "site_knowledge_clock": lambda: datetime(2026, 10, 13, tzinfo=timezone.utc)}
                from copilot_agent.discovery_store import Store
                discovery_store = Store(context, persistent=True)
                discovery_store.close()
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(target / "workspace")}
                prepared = prepare_package_run(args, context, registry)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])

                with patch.dict(os.environ, {"COPILOT_AGENT_EXECUTION_MODE": "testing"}):
                    result = await execute_package(args, context, registry, code_runner_factory=FakeRunner)

                self.assertEqual("completed", result["status"])
                self.assertEqual([name for _, name, _, _ in stages], [call[0] for call in calls])
                for stage_id, tool_id, arguments, _ in stages[:2]:
                    call = next(item for item in calls if item[0] == tool_id)
                    expected_hash = canonical_hash({"package_plan_hash": prepared["package_plan_hash"],
                                                    "stage_id": stage_id, "tool_id": tool_id,
                                                    "arguments": arguments})
                    self.assertEqual(expected_hash, call[2]["approval_hash"])
                    self.assertEqual(expected_hash, call[2]["approved_hash"])
                    self.assertTrue(call[2]["approved"])
                    self.assertEqual(tool_id, call[2]["site_knowledge_reviewed"]["kind"])
                save_context = next(item[2] for item in calls if item[0] == "site_knowledge.save")
                self.assertEqual(save_context["site_knowledge_reviewed"], save_context["site_knowledge_consent"])
                self.assertEqual("local_c_test", save_context["site_knowledge_reviewed"]["storage_mode"])
                retrieved = next(item[3] for item in calls if item[0] == "site_knowledge.retrieve")
                exported = next(item[3] for item in calls if item[0] == "site_knowledge.export")
                self.assertEqual("fresh", retrieved["result"]["status"])
                self.assertEqual("/customers/search", retrieved["result"]["knowledge"]["routes"][0]["path"])
                self.assertEqual("fresh", exported["result"]["status"])
                self.assertEqual(["/customers/search"], exported["result"]["summary"]["route_templates"])
                invalidated = next(item[3] for item in calls if item[0] == "site_knowledge.invalidate")
                self.assertEqual("invalidated", invalidated["result"]["status"])
                discovery_invalidated = next(item[3] for item in calls
                                             if item[0] == "discovery.knowledge_invalidate")
                self.assertEqual("invalidated", discovery_invalidated["result"]["status"])

        asyncio.run(run())

    def test_package_browser_open_approves_only_the_inspected_https_hosts(self):
        class Page:
            url = "about:blank"
            def __init__(self, browser_context):
                self.context = browser_context
                self.routes = []
            def is_closed(self):
                return False
            async def route(self, pattern, callback):
                self.routes.append((pattern, callback))
            async def unroute(self, pattern, callback):
                self.routes = [item for item in self.routes if item != (pattern, callback)]
            async def goto(self, url, **kwargs):
                self.url = url
            async def title(self):
                return "Opened test site"

        class Browser:
            def __init__(self, page, browser_context):
                self.tool_page = page
                self.tool_context = browser_context
                self._tool_pages = [page]
                self.page = object()
                self.chat_page = object()
                self.tool_domains = set()
                self.authorized = []
                self._tool_policy_route = None
            def authorize_tool_domain(self, domain):
                self.authorized.append(domain)
                self.tool_domains.add(domain.lower().rstrip("."))

        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                archive = write_tool_package(root / "browser.zip", ToolRegistry(), [{
                    "id": "open", "kind": "tool", "tool_id": "browser.open",
                    "arguments": {"url": "https://portal.example.test/start",
                                  "allowed_domains": ["static.example.test"]},
                    "depends_on": [], "inputs": [], "outputs": [], "timeout_seconds": 10,
                    "retries": 0, "idempotent": False, "checkpoint": True,
                }])
                state_dir = root / "session"
                state_dir.mkdir()
                browser_context = object()
                page = Page(browser_context)
                browser = Browser(page, browser_context)
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=3000,
                                         allowed_roots=[str(root)], allowed_domains=[], profile_dir=None,
                                         tool_timeout=30)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": state_dir, "cancelled": lambda: False, "browser": browser,
                           "approved_domains": []}
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                prepared = prepare_package_run(args, context, ToolRegistry())
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])

                result = await execute_package(args, context, ToolRegistry(), code_runner_factory=FakeRunner)

                self.assertEqual("completed", result["status"])
                self.assertEqual("https://portal.example.test/start", page.url)
                self.assertEqual({"portal.example.test", "static.example.test"}, browser.tool_domains)
                self.assertEqual(["portal.example.test", "static.example.test"], browser.authorized)
                self.assertEqual([], context["approved_domains"])

        asyncio.run(run())

    def test_package_browser_domain_approval_flows_open_tabs_recon_only_within_run(self):
        class RecordingRegistry(ToolRegistry):
            def __init__(self):
                super().__init__()
                self.contexts = []

            async def execute(self, name, arguments, context):
                self.contexts.append((name, list(context.get("approved_domains", []))))
                result = {"status": "ok"}
                if name == "browser.tabs":
                    result["tab_id"] = "tab-1"
                return {"ok": True, "tool": name, "result": result}

        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                registry = RecordingRegistry()
                stages = [
                    {"id": "open", "kind": "tool", "tool_id": "browser.open",
                     "arguments": {"url": "https://portal.example.test/start"},
                     "depends_on": [], "inputs": [], "outputs": [], "timeout_seconds": 10,
                     "retries": 0, "idempotent": False, "checkpoint": True},
                    {"id": "tabs", "kind": "tool", "tool_id": "browser.tabs",
                     "arguments": {"operation": "open", "url": "https://portal.example.test/section",
                                   "purpose": "Section", "task_id": "task-1"},
                     "depends_on": ["open"], "inputs": [], "outputs": [], "timeout_seconds": 10,
                     "retries": 0, "idempotent": False, "checkpoint": True},
                    {"id": "recon", "kind": "tool", "tool_id": "browser.recon",
                     "arguments": {"goal": "Inspect section", "tab_id": "tab-1", "task_id": "task-1"},
                     "depends_on": ["tabs"], "inputs": [], "outputs": [], "timeout_seconds": 10,
                     "retries": 0, "idempotent": True, "checkpoint": True},
                ]
                archive = write_tool_package(root / "navigation.zip", registry, stages)
                session = root / "session"
                session.mkdir()

                class Browser:
                    def __init__(self):
                        self.authorized = []
                    def authorize_tool_domain(self, domain):
                        self.authorized.append(domain)

                browser = Browser()
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=3000,
                                         allowed_roots=[str(root)], allowed_domains=[], profile_dir=None,
                                         tool_timeout=30)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": session, "cancelled": lambda: False, "browser": browser,
                           "approved_domains": []}
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                prepared = prepare_package_run(args, context, registry)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])

                result = await execute_package(args, context, registry, code_runner_factory=FakeRunner)

                self.assertEqual("completed", result["status"], result)
                self.assertEqual(["browser.open", "browser.tabs", "browser.recon"],
                                 [name for name, _ in registry.contexts])
                self.assertTrue(all("portal.example.test" in domains for _, domains in registry.contexts))
                self.assertEqual(["portal.example.test"], browser.authorized)
                self.assertEqual([], context["approved_domains"])

        asyncio.run(run())

    def test_package_discovery_manifest_uses_hash_bound_prepared_approval(self):
        from tests.discovery_fixtures import manifest

        async def run():
            with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
                    "COPILOT_AGENT_EXECUTION_MODE": "testing"}):
                root = Path(temp).resolve()
                tool_registry = ToolRegistry()
                args_for_stage = {"manifest": manifest()}
                archive = write_tool_package(root / "discovery.zip", tool_registry, [{
                    "id": "discover", "kind": "tool", "tool_id": "discovery.manifest",
                    "arguments": args_for_stage, "depends_on": [], "inputs": [], "outputs": [],
                    "timeout_seconds": 20, "retries": 0, "idempotent": False, "checkpoint": True,
                }], package_id="discovery-stage-test")
                session = root / "session"
                session.mkdir()
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=3000,
                                         allowed_roots=[str(root)], profile_dir=None, manifest_path=True,
                                         persistent_graph=False, bounded_parallelism=False)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": session, "cancelled": lambda: False,
                           "source_request_id": "package-discovery-stage-test-request"}
                # Match the task's exact package correlation to the nested
                # discovery contract before inspection and approval.
                args_for_stage["manifest"]["request_id"] = "ddiscovery-stage-test-request"
                # Rewrite after setting the final request ID so the archive
                # hash and package plan bind the exact submitted manifest.
                archive = write_tool_package(root / "discovery.zip", tool_registry, [{
                    "id": "discover", "kind": "tool", "tool_id": "discovery.manifest",
                    "arguments": args_for_stage, "depends_on": [], "inputs": [], "outputs": [],
                    "timeout_seconds": 20, "retries": 0, "idempotent": False, "checkpoint": True,
                }], package_id="discovery-stage-test")
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                prepared = prepare_package_run(args, context, tool_registry)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])
                captured = {}

                async def fake_discovery(name, arguments, stage_context):
                    captured.update(name=name, arguments=dict(arguments), context=dict(stage_context))
                    return {"outcome": "succeeded", "run_id": "synthetic-run"}

                with patch("copilot_agent.tools.execute_discovery", new=fake_discovery):
                    result = await execute_package(args, context, tool_registry, code_runner_factory=FakeRunner)

                self.assertEqual("completed", result["status"],
                                 (result, json.loads(Path(result["state_path"]).read_text(encoding="utf-8"))))
                stage_hash = canonical_hash({"package_plan_hash": prepared["package_plan_hash"],
                                             "stage_id": "discover", "tool_id": "discovery.manifest",
                                             "arguments": args_for_stage})
                self.assertEqual("discovery.manifest", captured["name"])
                self.assertEqual(stage_hash, captured["context"]["approval_hash"])
                self.assertEqual(stage_hash, captured["context"]["approved_hash"])
                self.assertTrue(captured["context"]["approved"])
                self.assertEqual("discovery.manifest", captured["context"]["discovery_reviewed"]["kind"])

        asyncio.run(run())

    def test_package_navigation_intent_and_discovery_save_carry_prepared_consent(self):
        from tests.discovery_fixtures import ORIGIN, intent

        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                delegate = ToolRegistry()
                scope = {"origins": [ORIGIN], "allow_paths": ["/"], "exclude_paths": [],
                         "query_keys": [], "max_query_variants": 3,
                         "allow_private_network": False, "redirect_limit": 3}
                navigation_intent = intent(scope)
                navigation_intent["request_id"] = "dnavigation-consent-package-request"
                stages = [
                    {"id": "intent", "kind": "tool", "tool_id": "navigation.intent",
                     "arguments": {"intent": navigation_intent}, "depends_on": [], "inputs": [],
                     "outputs": [], "timeout_seconds": 20, "retries": 0,
                     "idempotent": False, "checkpoint": True},
                    {"id": "save", "kind": "tool", "tool_id": "discovery.knowledge_save",
                     "arguments": {"run_id": "synthetic-run", "origin": ORIGIN,
                                   "expected_revision": 0}, "depends_on": ["intent"], "inputs": [],
                     "outputs": [], "timeout_seconds": 10, "retries": 0,
                     "idempotent": False, "checkpoint": True},
                ]
                registry = delegate
                archive = write_tool_package(root / "discovery-consent.zip", registry, stages,
                                             package_id="navigation-consent-package")
                session = root / "session"
                session.mkdir()
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=3000)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": session, "cancelled": lambda: False}
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                prepared = prepare_package_run(args, context, registry)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])
                reviewed_calls = []

                class RecordingRegistry:
                    def definition(self, name):
                        return delegate.definition(name)
                    def validate_input(self, name, arguments):
                        return delegate.validate_input(name, arguments)
                    def execute(self, name, arguments, stage_context):
                        reviewed_calls.append((name, arguments, dict(stage_context)))
                        async def result():
                            return {"ok": True, "tool": name, "result": {"status": "approved"}}
                        return result()

                def prepare(name, arguments, stage_context):
                    return {"kind": name, "args_sha256": canonical_hash(arguments)}

                with patch("copilot_agent.discovery_knowledge.prepare_knowledge_tool", side_effect=prepare):
                    result = await execute_package(args, context, RecordingRegistry(),
                                                   code_runner_factory=FakeRunner)

                self.assertEqual("completed", result["status"], result)
                intent_call = next(item for item in reviewed_calls if item[0] == "navigation.intent")
                save_call = next(item for item in reviewed_calls if item[0] == "discovery.knowledge_save")
                self.assertEqual("navigation.intent", intent_call[2]["discovery_reviewed"]["kind"])
                self.assertEqual("discovery.knowledge_save", save_call[2]["discovery_reviewed"]["kind"])
                self.assertEqual(save_call[2]["discovery_reviewed"], save_call[2]["discovery_save_consent"])
                for stage_id, name, arguments, context_value in (
                        ("intent", "navigation.intent", {"intent": navigation_intent}, intent_call[2]),
                        ("save", "discovery.knowledge_save", stages[1]["arguments"], save_call[2])):
                    expected = canonical_hash({"package_plan_hash": prepared["package_plan_hash"],
                                               "stage_id": stage_id, "tool_id": name,
                                               "arguments": arguments})
                    self.assertEqual(expected, context_value["approval_hash"])

        asyncio.run(run())

    @unittest.skipUnless(os.name == "nt", "Mapped S: package write seam is Windows-specific")
    def test_package_file_stage_carries_exact_mapped_s_preflight_and_denies_sibling(self):
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                package_root = root / "agent-root"
                package_root.mkdir()
                share = root / "mapped-share"
                report_root = share / "Reports"
                sibling_root = share / "Sibling"
                report_root.mkdir(parents=True)
                sibling_root.mkdir()
                allowed = report_root / "approved.txt"
                denied = sibling_root / "denied.txt"
                archive = write_tool_package(package_root / "s-write.zip", ToolRegistry(), [
                    {"id": "approved", "kind": "tool", "tool_id": "files.create",
                     "arguments": {"path": r"S:\Reports\approved.txt", "text": "approved output"},
                     "depends_on": [], "inputs": [], "outputs": [], "timeout_seconds": 10,
                     "retries": 0, "idempotent": False, "checkpoint": True},
                    {"id": "sibling", "kind": "tool", "tool_id": "files.create",
                     "arguments": {"path": r"S:\Sibling\denied.txt", "text": "must not escape"},
                     "depends_on": ["approved"], "inputs": [], "outputs": [], "timeout_seconds": 10,
                     "retries": 0, "idempotent": False, "checkpoint": True},
                ])
                session = package_root / "session"
                session.mkdir()
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=1, automation_max_output_chars=3000,
                                         allowed_roots=[str(package_root), str(report_root)], profile_dir=None,
                                         _auto_s_drive_root=str(share), _automation_test_mode=False,
                                         _local_knowledge_test_mode=False, tool_timeout=30)
                policy = PathPolicy([str(package_root), str(report_root)], mapped_s_root=share)
                context = {"config": config, "path_policy": policy, "session_dir": session,
                           "cancelled": lambda: False}
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(package_root / "workspace")}
                registry = ToolRegistry()

                def mapped_output(value, **kwargs):
                    normalized = str(value).replace("/", "\\")
                    relative = normalized.split("S:\\", 1)[1]
                    return share.joinpath(*relative.split("\\"))

                with patch("copilot_agent.tools.resolve_s_drive_output", side_effect=mapped_output), \
                     patch("copilot_agent.policy.resolve_s_drive_output", side_effect=mapped_output), \
                     patch("copilot_agent.policy.mapped_s_drive_root", return_value=share):
                    prepared = prepare_package_run(args, context, registry)
                    context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                                   approved_hash=prepared["package_plan_hash"])
                    result = await execute_package(args, context, registry, code_runner_factory=FakeRunner)

                self.assertEqual("partial", result["status"], result)
                self.assertTrue(allowed.is_file())
                self.assertEqual("approved output", allowed.read_text(encoding="utf-8"))
                self.assertFalse(denied.exists())
                self.assertEqual(["sibling"], result["failed_stages"])

        asyncio.run(run())

    def test_package_inspector_accepts_user_approved_tools_but_keeps_separate_handoff_tools_blocked(self):
        registry = ToolRegistry()
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.zip"
            source.write_bytes(package_bytes())
            with zipfile.ZipFile(source) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                readme = archive.read("README.md")
                payload = archive.read("main.py")
            browser = registry.definition("browser.open")
            manifest["tools"] = [{"id": "browser.open", "version": browser["version"]}]
            manifest["stages"] = [{"id": "browse", "kind": "tool", "tool_id": "browser.open",
                                   "arguments": {"url": "https://www.gov.uk", "allowed_domains": []},
                                   "depends_on": [], "inputs": [], "outputs": [], "timeout_seconds": 20,
                                   "retries": 0, "idempotent": False, "checkpoint": True}]
            manifest["entrypoint"] = "browse"
            manifest["validation"] = []
            manifest["expected_outputs"] = []
            path = Path(temp) / "package.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("README.md", readme)
                archive.writestr("main.py", payload)

            inspected = inspect_package(path, registry=registry)

            self.assertEqual("passed", inspected["review"]["status"])
            self.assertEqual(["browse"], [stage["id"] for stage in inspected["stages"]])

            manifest["tools"] = [{"id": "code_runner", "version": registry.definition("code_runner")["version"]}]
            manifest["stages"][0]["tool_id"] = "code_runner"
            manifest["stages"][0]["arguments"] = {"script": "print(1)"}
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("README.md", readme)
                archive.writestr("main.py", payload)
            with self.assertRaises(PackageError) as caught:
                inspect_package(path, registry=registry)
            self.assertIn("immutable-plan tools",
                          caught.exception.report["failures"][0]["detail"])

            grant = registry.definition("files.grant_path")
            manifest["tools"] = [{"id": "files.grant_path", "version": grant["version"]}]
            manifest["stages"][0]["tool_id"] = "files.grant_path"
            manifest["stages"][0]["arguments"] = {"path": "C:/outside", "scope": "directory",
                                                   "reason": "Package path extension"}
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("README.md", readme)
                archive.writestr("main.py", payload)
            with self.assertRaises(PackageError) as caught:
                inspect_package(path, registry=registry)
            self.assertIn("files.grant_path", caught.exception.report["failures"][0]["detail"])

    def test_package_inspector_blocks_research_permission_lifecycle_tools(self):
        registry = ToolRegistry()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.zip"
            source.write_bytes(package_bytes())
            with zipfile.ZipFile(source) as archive:
                base_manifest = json.loads(archive.read("manifest.json"))
                readme = archive.read("README.md")
                payload = archive.read("main.py")
            for name in ("permissions.list", "permissions.activate", "permissions.pause", "permissions.revoke"):
                manifest = json.loads(json.dumps(base_manifest))
                definition = registry.definition(name)
                manifest["tools"] = [{"id": name, "version": definition["version"]}]
                manifest["stages"] = [{"id": "permission", "kind": "tool", "tool_id": name,
                                       "arguments": {}, "depends_on": [], "inputs": [], "outputs": [],
                                       "timeout_seconds": 5, "retries": 0, "idempotent": True,
                                       "checkpoint": True}]
                manifest["entrypoint"] = "permission"
                manifest["validation"] = []
                manifest["expected_outputs"] = []
                package = root / (name.replace(".", "-") + ".zip")
                with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("manifest.json", json.dumps(manifest))
                    archive.writestr("README.md", readme)
                    archive.writestr("main.py", payload)

                with self.subTest(tool=name), self.assertRaises(PackageError) as caught:
                    inspect_package(package, registry=registry)
                self.assertIn(name, caught.exception.report["failures"][0]["detail"])

    def test_tool_stage_page_content_is_kept_out_of_durable_package_state(self):
        class FakeRegistry:
            def __init__(self):
                self.delegate = ToolRegistry()

            def definition(self, name):
                return self.delegate.definition(name)

            def validate_input(self, name, arguments):
                return self.delegate.validate_input(name, arguments)

            def validate_call(self, name, arguments, context):
                return self.validate_input(name, arguments)

            async def execute(self, name, arguments, context):
                return {"ok": True, "tool": name,
                        "result": {"text": "private-govuk-page-content"}}

        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                source = root / "source.zip"
                source.write_bytes(package_bytes())
                with zipfile.ZipFile(source) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    readme = archive.read("README.md")
                    payload = archive.read("main.py")
                registry = FakeRegistry()
                definition = registry.definition("browser.read")
                manifest["tools"] = [{"id": "browser.read", "version": definition["version"]}]
                manifest["stages"] = [{"id": "read", "kind": "tool", "tool_id": "browser.read",
                                       "arguments": {}, "depends_on": [], "inputs": [], "outputs": [],
                                       "timeout_seconds": 5, "retries": 0,
                                       "idempotent": True, "checkpoint": True}]
                manifest["entrypoint"] = "read"
                manifest["validation"] = []
                manifest["expected_outputs"] = []
                archive = root / "tool-package.zip"
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
                    output.writestr("manifest.json", json.dumps(manifest))
                    output.writestr("README.md", readme)
                    output.writestr("main.py", payload)
                session = root / "session"
                session.mkdir()
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=2000)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": session, "cancelled": lambda: False}
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                prepared = prepare_package_run(args, context, registry)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])

                result = await execute_package(args, context, registry, code_runner_factory=FakeRunner)

                self.assertEqual("completed", result["status"])
                checkpoint = Path(result["state_path"]).read_text(encoding="utf-8")
                self.assertNotIn("private-govuk-page-content", checkpoint)
                self.assertIn("result_sha256", checkpoint)
        asyncio.run(run())

    def test_v11_typed_tool_result_binding_reaches_only_dependent_tool_stage(self):
        class FakeRegistry:
            def __init__(self):
                self.delegate = ToolRegistry()
                self.calls = []
                self.result_url = "https://www.gov.uk/guidance"

            def definition(self, name):
                return self.delegate.definition(name)

            def validate_input(self, name, arguments):
                return self.delegate.validate_input(name, arguments)

            def validate_call(self, name, arguments, context):
                return self.validate_input(name, arguments)

            async def execute(self, name, arguments, context):
                self.calls.append((name, arguments))
                if name == "browser.read":
                    return {"ok": True, "tool": name,
                            "result": {"url": self.result_url}}
                return {"ok": True, "tool": name, "result": {"opened": arguments["url"]}}

        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                source = root / "source.zip"
                source.write_bytes(package_bytes())
                with zipfile.ZipFile(source) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    readme = archive.read("README.md")
                    payload = archive.read("main.py")
                registry = FakeRegistry()
                manifest["schema_version"] = "1.1"
                manifest["tools"] = [{"id": name, "version": registry.definition(name)["version"]}
                                     for name in ("browser.read", "browser.open")]
                manifest["stages"] = [
                    {"id": "observe.step", "kind": "tool", "tool_id": "browser.read", "arguments": {},
                     "result_bindings": [{"name": "visited", "json_pointer": "/result/url",
                                          "type": "string", "max_bytes": 2048}],
                     "depends_on": [], "inputs": [], "outputs": [], "timeout_seconds": 5,
                     "retries": 0, "idempotent": True, "checkpoint": True},
                    {"id": "open", "kind": "tool", "tool_id": "browser.open",
                     "arguments": {"url": {"$binding": "observe.step.visited"}, "allowed_domains": ["gov.uk"]},
                     "depends_on": ["observe.step"], "inputs": [], "outputs": [], "timeout_seconds": 5,
                     "retries": 0, "idempotent": False, "checkpoint": True},
                ]
                manifest["entrypoint"] = "observe.step"
                manifest["validation"] = []
                manifest["expected_outputs"] = []
                invalid_manifest = json.loads(json.dumps(manifest))
                invalid_manifest["stages"][1]["arguments"]["allowed_domains"] = [
                    {"$binding": "observe.step.visited"}]
                invalid_archive = root / "bound-domain.zip"
                with zipfile.ZipFile(invalid_archive, "w", zipfile.ZIP_DEFLATED) as output:
                    output.writestr("manifest.json", json.dumps(invalid_manifest))
                    output.writestr("README.md", readme)
                    output.writestr("main.py", payload)
                with self.assertRaises(PackageReviewError) as raised:
                    inspect_package(invalid_archive, registry=registry)
                self.assertTrue(any("allowed_domains must be statically declared" in check.get("detail", "")
                                    for check in raised.exception.report["checks"]))
                archive = root / "bound-tools.zip"
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
                    output.writestr("manifest.json", json.dumps(manifest))
                    output.writestr("README.md", readme)
                    output.writestr("main.py", payload)
                session = root / "session"
                session.mkdir()
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=2000)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": session, "cancelled": lambda: False}
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                prepared = prepare_package_run(args, context, registry)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])

                result = await execute_package(args, context, registry, code_runner_factory=FakeRunner)

                self.assertEqual("completed", result["status"])
                self.assertEqual(["browser.read", "browser.open"], [name for name, _ in registry.calls])
                self.assertEqual("https://www.gov.uk/guidance", registry.calls[1][1]["url"])
                checkpoint = Path(result["state_path"]).read_text(encoding="utf-8")
                self.assertNotIn("https://www.gov.uk/guidance", checkpoint)

                registry.calls.clear()
                registry.result_url = "https://169.254.169.254/latest/meta-data"
                rejected = await execute_package(args, context, registry, code_runner_factory=FakeRunner)
                self.assertNotEqual("completed", rejected["status"])
                self.assertEqual(["browser.read"], [name for name, _ in registry.calls])
        asyncio.run(run())

    def test_resume_rejects_completed_private_binding_producer_before_mutating_run(self):
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                source = root / "source.zip"
                source.write_bytes(package_bytes())
                with zipfile.ZipFile(source) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    readme = archive.read("README.md")
                    payload = archive.read("main.py")
                registry = ToolRegistry()
                manifest["schema_version"] = "1.1"
                manifest["tools"] = [{"id": name, "version": registry.definition(name)["version"]}
                                     for name in ("browser.read", "browser.open")]
                manifest["stages"] = [
                    {"id": "observe.step", "kind": "tool", "tool_id": "browser.read", "arguments": {},
                     "result_bindings": [{"name": "visited", "json_pointer": "/result/url",
                                          "type": "string", "max_bytes": 2048}],
                     "depends_on": [], "inputs": [], "outputs": [], "timeout_seconds": 5,
                     "retries": 0, "idempotent": True, "checkpoint": True},
                    {"id": "open", "kind": "tool", "tool_id": "browser.open",
                     "arguments": {"url": {"$binding": "observe.step.visited"}, "allowed_domains": ["gov.uk"]},
                     "depends_on": ["observe.step"], "inputs": [], "outputs": [], "timeout_seconds": 5,
                     "retries": 0, "idempotent": False, "checkpoint": True},
                ]
                manifest["entrypoint"] = "observe.step"
                manifest["validation"] = []
                manifest["expected_outputs"] = []
                archive = root / "bound-tools.zip"
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
                    output.writestr("manifest.json", json.dumps(manifest))
                    output.writestr("README.md", readme)
                    output.writestr("main.py", payload)
                run_id = "a" * 32
                run_dir = root / "workspace" / "runs" / run_id
                run_dir.mkdir(parents=True)
                state_path = run_dir / "state.json"
                initial_state = {"archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                                 "status": "partial",
                                 "stages": {"observe.step": {"status": "completed", "result": {
                                     "result_sha256": "0" * 64, "result_bytes": 16}}}}
                state_path.write_text(json.dumps(initial_state), encoding="utf-8")
                original_state = state_path.read_bytes()
                session = root / "session"
                session.mkdir()
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=2000)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": session, "cancelled": lambda: False}
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace"), "resume_run_id": run_id}
                prepared = prepare_package_run(args, context, registry)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])

                with self.assertRaisesRegex(PackageError, "private tool results are intentionally not checkpointed"):
                    await execute_package(args, context, registry, code_runner_factory=FakeRunner)

                self.assertEqual(original_state, state_path.read_bytes())
                self.assertFalse((run_dir / "outputs").exists())
        asyncio.run(run())

    def test_prior_run_patch_rejects_cached_binding_producer_before_creating_new_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "source.zip"
            source.write_bytes(package_bytes())
            with zipfile.ZipFile(source) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                readme = archive.read("README.md")
                payload = archive.read("main.py")
            registry = ToolRegistry()
            manifest["schema_version"] = "1.1"
            manifest["tools"] = [{"id": name, "version": registry.definition(name)["version"]}
                                 for name in ("browser.read", "browser.open")]
            manifest["stages"] = [
                {"id": "observe.step", "kind": "tool", "tool_id": "browser.read", "arguments": {},
                 "result_bindings": [{"name": "visited", "json_pointer": "/result/url",
                                      "type": "string", "max_bytes": 2048}],
                 "depends_on": [], "inputs": [], "outputs": [], "timeout_seconds": 5,
                 "retries": 0, "idempotent": True, "checkpoint": True},
                {"id": "open", "kind": "tool", "tool_id": "browser.open",
                 "arguments": {"url": {"$binding": "observe.step.visited"}, "allowed_domains": ["gov.uk"]},
                 "depends_on": ["observe.step"], "inputs": [], "outputs": [], "timeout_seconds": 6,
                 "retries": 0, "idempotent": False, "checkpoint": True},
            ]
            manifest["entrypoint"] = "observe.step"
            manifest["validation"] = []
            manifest["expected_outputs"] = []
            archive = root / "bound-tools.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
                output.writestr("manifest.json", json.dumps(manifest))
                output.writestr("README.md", readme)
                output.writestr("main.py", payload)
            prior_manifest = json.loads(json.dumps(manifest))
            prior_manifest["stages"][1]["timeout_seconds"] = 5
            prior_id = "c" * 32
            prior_dir = root / "workspace" / "runs" / prior_id
            prior_dir.mkdir(parents=True)
            prior_state = {"status": "completed", "manifest": prior_manifest,
                           "stages": {"observe.step": {"status": "completed"},
                                      "open": {"status": "completed"}}}
            (prior_dir / "state.json").write_text(json.dumps(prior_state), encoding="utf-8")
            session = root / "session"
            session.mkdir()
            config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                     automation_max_parallel_stages=2, automation_max_output_chars=2000)
            context = {"config": config, "path_policy": PathPolicy([str(root)]), "session_dir": session}
            args = {"archive_path": str(archive),
                    "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "workspace": str(root / "workspace"), "prior_run_id": prior_id}

            with self.assertRaisesRegex(PackageError, "private tool result is not checkpointed"):
                prepare_package_run(args, context, registry)

            self.assertEqual([prior_id], [path.name for path in (root / "workspace" / "runs").iterdir()])

    def test_independent_read_only_tab_stages_run_in_parallel_but_same_tab_is_serial(self):
        class FakeRegistry:
            def __init__(self, delay=0.02):
                self.delegate = ToolRegistry()
                self.active = 0
                self.max_active = 0
                self.delay = delay
                self.started = False
                self.calls = []

            def definition(self, name):
                return self.delegate.definition(name)

            def validate_input(self, name, arguments):
                return self.delegate.validate_input(name, arguments)

            def validate_call(self, name, arguments, context):
                return self.validate_input(name, arguments)

            async def execute(self, name, arguments, context):
                self.started = True
                self.calls.append((name, arguments))
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                await asyncio.sleep(self.delay)
                self.active -= 1
                return {"ok": True, "tool": name, "result": {"status": "observed"}}

        async def run(tab_ids, *, cancel_on_start=False):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                source = root / "source.zip"
                source.write_bytes(package_bytes())
                with zipfile.ZipFile(source) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    readme = archive.read("README.md")
                    payload = archive.read("main.py")
                registry = FakeRegistry(delay=0.5 if cancel_on_start else 0.02)
                definition = registry.definition("browser.recon")
                manifest["schema_version"] = "1.1"
                manifest["tools"] = [{"id": "browser.recon", "version": definition["version"]}]
                manifest["capabilities"]["max_concurrency"] = 2
                manifest["stages"] = [
                    {"id": f"read-{index}", "kind": "tool", "tool_id": "browser.recon",
                     "arguments": {"goal": "inspect public guidance", "tab_id": tab_id, "task_id": "govuk"},
                     "depends_on": [], "inputs": [], "outputs": [], "timeout_seconds": 5,
                     "retries": 0, "idempotent": True, "checkpoint": True}
                    for index, tab_id in enumerate(tab_ids, 1)
                ]
                if cancel_on_start:
                    manifest["stages"].append({"id": "dependent", "kind": "tool", "tool_id": "browser.recon",
                                               "arguments": {"goal": "follow up", "tab_id": "tab-3", "task_id": "govuk"},
                                               "depends_on": ["read-1", "read-2"], "inputs": [], "outputs": [],
                                               "timeout_seconds": 5, "retries": 0,
                                               "idempotent": True, "checkpoint": True})
                manifest["entrypoint"] = "read-1"
                manifest["validation"] = []
                manifest["expected_outputs"] = []
                archive = root / "tabs.zip"
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
                    output.writestr("manifest.json", json.dumps(manifest))
                    output.writestr("README.md", readme)
                    output.writestr("main.py", payload)
                session = root / "session"
                session.mkdir()
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=2000)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": session,
                           "cancelled": lambda: registry.started if cancel_on_start else False}
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                prepared = prepare_package_run(args, context, registry)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])
                pages = {tab_id: SimpleNamespace(url="https://www.gov.uk/benefits") for tab_id in set(tab_ids)}
                with patch("copilot_agent.web_navigation.get_navigation_page",
                           side_effect=lambda context, tab_id=None, *_args, **_kwargs: pages[tab_id]):
                    result = await execute_package(args, context, registry, code_runner_factory=FakeRunner)
                if cancel_on_start:
                    self.assertEqual("cancelled", result["status"])
                    self.assertEqual(2, len(registry.calls))
                    state_path = root / "workspace" / "runs" / result["run_id"] / "state.json"
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    self.assertEqual({"cancelled"}, {record["status"] for record in state["stages"].values()})
                    started_records = [record for record in state["stages"].values()
                                       if "started_at" in record or "finished_at" in record]
                    self.assertTrue(started_records)
                    for record in started_records:
                        self.assertIsInstance(record["started_at"], (int, float))
                        self.assertIsInstance(record["finished_at"], (int, float))
                        self.assertLessEqual(record["started_at"], record["finished_at"])
                    return registry.max_active, result
                self.assertEqual("completed", result["status"])
                return registry.max_active, result

        async def checks():
            parallelism, _ = await run(["tab-2", "tab-3"])
            self.assertEqual(2, parallelism)
            serialism, _ = await run(["tab-2", "tab-2"])
            self.assertEqual(1, serialism)
            cancelled_parallelism, _ = await run(["tab-2", "tab-3"], cancel_on_start=True)
            self.assertEqual(2, cancelled_parallelism)
        asyncio.run(checks())

    def test_result_bound_read_tabs_overlap_only_when_bindings_resolve_to_distinct_owned_tabs(self):
        class FakeRegistry:
            def __init__(self):
                self.delegate = ToolRegistry()
                self.active = 0
                self.max_active = 0
                self.recon_calls = []

            def definition(self, name):
                return self.delegate.definition(name)

            def validate_input(self, name, arguments):
                return self.delegate.validate_input(name, arguments)

            def validate_call(self, name, arguments, context):
                return self.validate_input(name, arguments)

            async def execute(self, name, arguments, context):
                if name == "browser.tabs":
                    tab_id = None if arguments["purpose"] == "missing" else arguments["purpose"]
                    result = {"tab_id": tab_id} if tab_id else {}
                    return {"ok": True, "tool": name, "result": result}
                self.recon_calls.append(arguments)
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                try:
                    await asyncio.sleep(0.04)
                    return {"ok": True, "tool": name, "result": {"status": "observed"}}
                finally:
                    self.active -= 1

        async def run(*, duplicate=False, invalid=False, invalid_origin=False, aliased_page=False,
                      invalid_owner=False):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                source = root / "source.zip"
                source.write_bytes(package_bytes())
                with zipfile.ZipFile(source) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    readme = archive.read("README.md")
                    payload = archive.read("main.py")
                registry = FakeRegistry()
                tabs = ["missing" if invalid else "tab-a", "tab-b"]
                producers = []
                for index, purpose in enumerate(tabs, 1):
                    producer_id = f"open-{index}"
                    producers.append({"id": producer_id, "kind": "tool", "tool_id": "browser.tabs",
                                      "arguments": {"operation": "open", "url": "https://www.gov.uk/",
                                                    "purpose": purpose, "task_id": "govuk"},
                                      "result_bindings": [{"name": "tab", "json_pointer": "/result/tab_id",
                                                           "type": "string", "max_bytes": 128}],
                                      "depends_on": [], "inputs": [], "outputs": [], "timeout_seconds": 5,
                                      "retries": 0, "idempotent": False, "checkpoint": True})
                consumers = []
                for index in range(2):
                    producer_id = "open-1" if duplicate else f"open-{index + 1}"
                    consumers.append({"id": f"read-{index + 1}", "kind": "tool", "tool_id": "browser.recon",
                                      "arguments": {"goal": "inspect public guidance", "task_id": "govuk",
                                                    "tab_id": {"$binding": producer_id + ".tab"}},
                                      "depends_on": ["open-1", "open-2"], "inputs": [], "outputs": [],
                                      "timeout_seconds": 5, "retries": 0, "idempotent": True, "checkpoint": True})
                manifest["schema_version"] = "1.1"
                manifest["tools"] = [{"id": tool_id, "version": registry.definition(tool_id)["version"]}
                                     for tool_id in ("browser.tabs", "browser.recon")]
                manifest["capabilities"]["max_concurrency"] = 2
                manifest["stages"] = producers + consumers
                manifest["entrypoint"] = "open-1"
                manifest["validation"] = []
                manifest["expected_outputs"] = []
                archive_path = root / "bound-tabs.zip"
                with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("manifest.json", json.dumps(manifest))
                    archive.writestr("README.md", readme)
                    archive.writestr("main.py", payload)
                session = root / "session"
                session.mkdir()
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=2000)
                context = {"config": config, "path_policy": PathPolicy([str(root)]), "session_dir": session}
                args = {"archive_path": str(archive_path),
                        "expected_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                prepared = prepare_package_run(args, context, registry)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])
                page_a = SimpleNamespace(url="https://www.gov.uk/benefits")
                page_b = page_a if aliased_page else SimpleNamespace(
                    url="https://example.com/benefits" if invalid_origin else "https://www.gov.uk/benefits")
                pages = {tabs[0]: page_a, tabs[1]: page_b}
                def lookup_page(context, tab_id=None, *_args, **_kwargs):
                    if invalid_owner and tab_id == "tab-b":
                        raise PolicyError("Tab ownership changed")
                    return pages[tab_id]
                with patch("copilot_agent.web_navigation.get_navigation_page",
                           side_effect=lookup_page):
                    result = await execute_package(args, context, registry, code_runner_factory=FakeRunner)
                state_path = root / "workspace" / "runs" / result["run_id"] / "state.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                return registry, result, state

        def assert_stage_timestamps(state):
            for record in state["stages"].values():
                self.assertIsInstance(record["started_at"], (int, float))
                self.assertIsInstance(record["finished_at"], (int, float))
                self.assertLessEqual(record["started_at"], record["finished_at"])

        async def checks():
            registry, result, state = await run()
            self.assertEqual("completed", result["status"])
            self.assertEqual(2, registry.max_active)
            self.assertEqual(2, len(registry.recon_calls))
            assert_stage_timestamps(state)
            recon_records = [state["stages"][stage_id] for stage_id in ("read-1", "read-2")]
            for record in recon_records:
                self.assertIsInstance(record["started_at"], (int, float))
                self.assertIsInstance(record["finished_at"], (int, float))
                self.assertLessEqual(record["started_at"], record["finished_at"])
            self.assertLess(max(record["started_at"] for record in recon_records),
                            min(record["finished_at"] for record in recon_records),
                            "distinct-tab recon stage intervals should overlap")

            registry, result, state = await run(duplicate=True)
            self.assertEqual("completed", result["status"])
            self.assertEqual(1, registry.max_active)
            self.assertEqual(2, len(registry.recon_calls))
            assert_stage_timestamps(state)

            registry, result, _ = await run(invalid_owner=True)
            self.assertEqual("completed", result["status"])
            self.assertEqual(1, registry.max_active)
            self.assertEqual(2, len(registry.recon_calls))

            registry, result, _ = await run(invalid_origin=True)
            self.assertEqual("completed", result["status"])
            self.assertEqual(1, registry.max_active)
            self.assertEqual(2, len(registry.recon_calls))

            registry, result, _ = await run(aliased_page=True)
            self.assertEqual("completed", result["status"])
            self.assertEqual(1, registry.max_active)
            self.assertEqual(2, len(registry.recon_calls))

            registry, result, _ = await run(invalid=True)
            self.assertNotEqual("completed", result["status"])
            self.assertEqual(0, len(registry.recon_calls))
        asyncio.run(checks())

    def test_independent_python_stages_overlap_with_isolated_scratch(self):
        class TrackingRunner(FakeRunner):
            active = 0
            max_active = 0
            scratch_roots = []
            started = []
            finished = []
            async def run_async(self, args, approved_hash, process_registry=None):
                type(self).active += 1
                type(self).max_active = max(type(self).max_active, type(self).active)
                type(self).scratch_roots.append(args["create_roots"][0])
                stage_name = args["arguments"][0]
                type(self).started.append(stage_name)
                try:
                    await asyncio.sleep(.03)
                    Path(args["expected_outputs"][0]).write_text("verified", encoding="utf-8")
                    type(self).finished.append(stage_name)
                    return {"status": "completed", "exit_code": 0, "stdout": "", "stderr": ""}
                finally:
                    type(self).active -= 1

        async def run_variant(*, network=False, dependent=False):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                source = root / "source.zip"
                source.write_bytes(package_bytes())
                with zipfile.ZipFile(source) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    readme = archive.read("README.md")
                    payload = archive.read("main.py")
                outputs = ["first.txt", "second.txt"]
                destinations = ["https://example.com"] if network else []
                permissions = ["read_files", "create_files"] + (["network"] if network else [])
                manifest["capabilities"]["read_paths"] = ["main.py"] + ([outputs[0]] if dependent else [])
                manifest["capabilities"]["create_paths"] = outputs
                manifest["capabilities"]["network_destinations"] = destinations
                manifest["capabilities"]["permissions"] = permissions
                manifest["expected_outputs"] = outputs
                manifest["validation"] = [{"kind": "exists", "path": item} for item in outputs]
                manifest["capabilities"]["max_concurrency"] = 2
                manifest["stages"] = [
                    {"id": "python-1", "kind": "python", "script": "main.py", "arguments_list": ["python-1"],
                     "depends_on": [], "inputs": [], "outputs": [outputs[0]], "timeout_seconds": 5, "retries": 0,
                     "idempotent": True, "checkpoint": True, "imports": [],
                     "network_destinations": destinations, "permissions": permissions},
                    {"id": "python-2", "kind": "python", "script": "main.py", "arguments_list": ["python-2"],
                     "depends_on": ["python-1"] if dependent else [],
                     "inputs": [outputs[0]] if dependent else [], "outputs": [outputs[1]],
                     "timeout_seconds": 5, "retries": 0, "idempotent": True, "checkpoint": True, "imports": [],
                     "network_destinations": destinations, "permissions": permissions},
                ]
                manifest["entrypoint"] = "python-1"
                archive_path = root / "parallel-python.zip"
                with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as output:
                    output.writestr("manifest.json", json.dumps(manifest))
                    output.writestr("README.md", readme)
                    output.writestr("main.py", payload)
                session = root / "session"
                session.mkdir()
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=2000)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": session, "cancelled": lambda: False}
                args = {"archive_path": str(archive_path),
                        "expected_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                registry = ToolRegistry()
                prepared = prepare_package_run(args, context, registry)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])
                TrackingRunner.active = TrackingRunner.max_active = 0
                TrackingRunner.scratch_roots = []
                TrackingRunner.started = []
                TrackingRunner.finished = []

                result = await execute_package(args, context, registry, code_runner_factory=TrackingRunner)

                self.assertEqual("completed", result["status"])
                output_root = (root / "workspace" / "runs" / result["run_id"] / "outputs").resolve()
                self.assertEqual(2, len(set(TrackingRunner.scratch_roots)))
                self.assertTrue(all(Path(path).is_relative_to(output_root) for path in TrackingRunner.scratch_roots))
                return TrackingRunner.max_active, TrackingRunner.started, TrackingRunner.finished

        async def checks():
            parallelism, _, _ = await run_variant()
            self.assertEqual(2, parallelism)
            network_parallelism, _, _ = await run_variant(network=True)
            self.assertEqual(1, network_parallelism)
            dependency_parallelism, started, finished = await run_variant(dependent=True)
            self.assertEqual(1, dependency_parallelism)
            self.assertEqual(["python-1", "python-2"], started)
            self.assertEqual(["python-1", "python-2"], finished)
        asyncio.run(checks())

    def test_independent_effectful_tool_stages_are_serialized(self):
        class TrackingRegistry:
            def __init__(self):
                self.delegate = ToolRegistry()
                self.active = 0
                self.max_active = 0
            def definition(self, name):
                return self.delegate.definition(name)
            def validate_input(self, name, arguments):
                return self.delegate.validate_input(name, arguments)
            def validate_call(self, name, arguments, context):
                return self.delegate.validate_call(name, arguments, context)
            async def execute(self, name, arguments, context):
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                try:
                    await asyncio.sleep(.03)
                    return {"ok": True, "tool": name, "result": {"opened": arguments["url"]}}
                finally:
                    self.active -= 1

        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                registry = TrackingRegistry()
                archive = write_tool_package(root / "effectful.zip", registry, [
                    {"id": "open-a", "kind": "tool", "tool_id": "browser.open",
                     "arguments": {"url": "https://one.example.test", "allowed_domains": []},
                     "depends_on": [], "inputs": [], "outputs": [], "timeout_seconds": 10,
                     "retries": 0, "idempotent": False, "checkpoint": True},
                    {"id": "open-b", "kind": "tool", "tool_id": "browser.open",
                     "arguments": {"url": "https://two.example.test", "allowed_domains": []},
                     "depends_on": [], "inputs": [], "outputs": [], "timeout_seconds": 10,
                     "retries": 0, "idempotent": False, "checkpoint": True},
                ])
                session = root / "session"
                session.mkdir()
                config = SimpleNamespace(automation_max_runtime_seconds=60, automation_max_stages=10,
                                         automation_max_parallel_stages=2, automation_max_output_chars=3000,
                                         allowed_roots=[str(root)], allowed_domains=[], profile_dir=None)
                context = {"config": config, "path_policy": PathPolicy([str(root)]),
                           "session_dir": session, "cancelled": lambda: False,
                           "approved_domains": []}
                args = {"archive_path": str(archive),
                        "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "workspace": str(root / "workspace")}
                prepared = prepare_package_run(args, context, registry)
                context.update(approved=True, package_plan_hash=prepared["package_plan_hash"],
                               approved_hash=prepared["package_plan_hash"])

                result = await execute_package(args, context, registry, code_runner_factory=FakeRunner)

                self.assertEqual("completed", result["status"])
                self.assertEqual(1, registry.max_active)

        asyncio.run(run())

    def test_real_python_package_stage_uses_isolated_scratch_and_retains_output_root_abi(self):
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                script = ("import os, sys\nfrom pathlib import Path\n"
                          "scratch=Path(os.environ['COPILOT_PACKAGE_STAGE_SCRATCH'])\n"
                          "draft=scratch/'nested'/'draft.txt'\ndraft.parent.mkdir()\n"
                          "draft.write_text('first')\ndraft.write_text(draft.read_text()+'-second')\n"
                          "Path(sys.argv[-1], 'result.txt').write_text(draft.read_text())\n")
                archive = write_python_package(root / "scratch.zip", script)
                from copilot_agent.code_runner import CodeRunner
                factory = lambda policy, session, timeout, output: CodeRunner(
                    policy, session, {"tool_timeout": timeout, "max_output_chars": output})
                result, _ = await execute_test_package(root, archive, factory)
                self.assertEqual("completed", result["status"], result)
                output_root = Path(result["output_root"])
                self.assertEqual("first-second", (output_root / "result.txt").read_text(encoding="utf-8"))
                self.assertFalse((output_root / ".stage-scratch").exists())
                state = json.loads(Path(result["state_path"]).read_text(encoding="utf-8"))
                self.assertTrue(state["stages"]["generate"]["scratch_cleanup_verified"])
        asyncio.run(run())

    def test_package_python_blocks_native_database_escape_outside_path_policy(self):
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                outside_db = root.parent / (root.name + "-outside.sqlite")
                if outside_db.exists():
                    outside_db.unlink()
                script = ("import sys\nfrom pathlib import Path\n"
                          "try:\n import sqlite3\n"
                          f"except PermissionError:\n Path(sys.argv[-1], 'result.txt').write_text('blocked')\n"
                          f"else:\n sqlite3.connect({str(outside_db)!r}).close()\n")
                archive = write_python_package(root / "sqlite.zip", script, imports=("sys", "pathlib", "sqlite3"))
                from copilot_agent.code_runner import CodeRunner
                factory = lambda policy, session, timeout, output: CodeRunner(
                    policy, session, {"tool_timeout": timeout, "max_output_chars": output})
                result, _ = await execute_test_package(root, archive, factory)
                self.assertEqual("completed", result["status"], result)
                self.assertEqual("blocked", (Path(result["output_root"]) / "result.txt").read_text(encoding="utf-8"))
                self.assertFalse(outside_db.exists())
        asyncio.run(run())

    def test_package_python_blocks_private_io_fileio_quota_and_path_escape(self):
        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                outside = root.parent / (root.name + "-raw-io.bin")
                if outside.exists():
                    outside.unlink()
                script = ("import sys\nfrom pathlib import Path\n"
                          "try:\n sys.modules['_io'].FileIO(" + repr(str(outside)) + ", 'w').write(b'x'*(50*1024*1024+1))\n"
                          f"except PermissionError:\n Path(sys.argv[-1], 'result.txt').write_text('blocked')\n"
                          "else:\n Path(sys.argv[-1], 'result.txt').write_text('escaped')\n")
                archive = write_python_package(root / "raw-io.zip", script, imports=("sys", "pathlib"))
                from copilot_agent.code_runner import CodeRunner
                factory = lambda policy, session, timeout, output: CodeRunner(
                    policy, session, {"tool_timeout": timeout, "max_output_chars": output})
                try:
                    result, _ = await execute_test_package(root, archive, factory)
                    self.assertEqual("completed", result["status"], result)
                    self.assertEqual("blocked", (Path(result["output_root"]) / "result.txt").read_text(encoding="utf-8"))
                    self.assertFalse(outside.exists())
                finally:
                    if outside.exists():
                        outside.unlink()
        asyncio.run(run())

    def test_failed_and_cancelled_python_stages_remove_only_unverified_outputs(self):
        class FailedRunner(FakeRunner):
            async def run_async(self, args, approved_hash, process_registry=None):
                Path(args["expected_outputs"][0]).write_text("partial", encoding="utf-8")
                return {"status": "failed", "exit_code": 1, "side_effects_uncertain": True}

        class CancelRunner(FakeRunner):
            started = False
            async def run_async(self, args, approved_hash, process_registry=None):
                Path(args["expected_outputs"][0]).write_text("partial", encoding="utf-8")
                type(self).started = True
                await asyncio.Future()

        async def run():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                archive = write_python_package(root / "failed.zip", "from pathlib import Path\nPath(sys.argv[-1], 'result.txt').write_text('partial')\n",
                                               imports=("sys", "pathlib"))
                result, _ = await execute_test_package(root, archive, FailedRunner)
                self.assertNotEqual("completed", result["status"])
                output = Path(result["output_root"]) / "result.txt"
                self.assertFalse(output.exists())
                self.assertFalse((Path(result["output_root"]) / ".stage-scratch").exists())

            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                archive = write_python_package(root / "cancel.zip", "print('running')\n")
                CancelRunner.started = False
                result, _ = await execute_test_package(root, archive, CancelRunner,
                                                       cancelled=lambda: CancelRunner.started)
                self.assertEqual("cancelled", result["status"])
                output_root = root / "workspace" / "runs" / result["run_id"] / "outputs"
                output = output_root / "result.txt"
                self.assertFalse(output.exists())
                self.assertFalse((output_root / ".stage-scratch").exists())
        asyncio.run(run())

    def test_package_output_collisions_reject_casefold_and_file_directory_prefixes(self):
        for outputs in (("Reports/summary.txt", "reports/SUMMARY.TXT"),
                        ("reports", "reports/summary.txt")):
            with self.subTest(outputs=outputs), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                original = root / "source.zip"
                original.write_bytes(package_bytes())
                with zipfile.ZipFile(original) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    readme, payload = archive.read("README.md"), archive.read("main.py")
                manifest["capabilities"]["create_paths"] = list(outputs)
                manifest["expected_outputs"] = list(outputs)
                manifest["stages"] = [
                    {"id": f"step-{index}", "kind": "python", "script": "main.py", "depends_on": [],
                     "inputs": [], "outputs": [item], "timeout_seconds": 5, "retries": 0,
                     "idempotent": True, "checkpoint": True, "imports": [],
                     "network_destinations": [], "permissions": ["create_files"]}
                    for index, item in enumerate(outputs, 1)]
                manifest["validation"] = [{"kind": "exists", "path": item} for item in outputs]
                manifest["entrypoint"] = "step-1"
                archive_path = root / "collision.zip"
                with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("manifest.json", json.dumps(manifest))
                    archive.writestr("README.md", readme)
                    archive.writestr("main.py", payload)
                with self.assertRaises((PackageError, PackageReviewError)):
                    inspect_package(archive_path)

    def test_output_paths_reject_absolute_escape_and_normalized_segments(self):
        for value in ("/outside.txt", "../outside.txt", "reports/../outside.txt",
                      "reports//item.txt", "reports/./item.txt", "reports/", "C:/outside.txt",
                      "C:\\outside.txt", "//server/share.txt", "report./item.txt",
                      "report /item.txt", "CON.txt", "nul.log", "COM1.txt", "LPT9.csv",
                      "COM\u00b9.txt", "LPT\u00b2.txt", "COM\u00b3.txt"):
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

    def test_package_review_summary_preserves_individual_and_session_authorization_choices(self):
        from copilot_agent.automation_packages import _package_review_report

        report = _package_review_report([])
        self.assertIn("pending run authorization", report["summary"])
        self.assertIn("individual approval", report["summary"])
        self.assertIn("active agent-session grant", report["summary"])
        self.assertIn("explicit individual or agent-session authorization", report["future_review_options"][0])

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
