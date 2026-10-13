import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from copilot_agent.code_runner import CodeRunner, FIELDS, OPTIONAL, REQUIRED
from copilot_agent.local_python_runner import ManagedProcessRegistry
from copilot_agent.policy import PathPolicy, PolicyError
from copilot_agent.tools import ToolRegistry


class CodeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix="copilot_code_test_"))
        self.runner=CodeRunner(PathPolicy([self.root]),self.root)

    def plan(self,script,**updates):
        result={"script":script,"purpose":"Synthetic test","language":"python_subset","working_directory":str(self.root),"read_paths":[],"create_paths":[],"expected_outputs":[],"commands":[],"network_destinations":[],"permissions":[],"risk_summary":"Bounded synthetic test","recovery_notes":"Retain outputs and inspect failures"}
        result.update(updates)
        return result

    def test_loop_and_create(self):
        args=self.plan("total = 0\nfor i in range(5):\n total = total + i\nwrite_file('result.txt', str(total))\nprint(total)",create_paths=["result.txt"],expected_outputs=["result.txt"],permissions=["create_files"])
        proposal=self.runner.prepare(args)
        result=self.runner.run(args,proposal["proposal_hash"])
        self.assertEqual(result["status"],"completed")
        self.assertEqual((self.root/"result.txt").read_text(),"10")
        self.assertEqual(result["output"],"10\n")
        self.assertEqual(self.runner.run(args,proposal["proposal_hash"])["status"],"failed")

    def test_scope_or_script_change_invalidates_grant(self):
        args=self.plan("print(1)")
        proposal=self.runner.prepare(args)
        with self.assertRaises(PolicyError): self.runner.run({**args,"script":"print(2)"},proposal["proposal_hash"])
        with self.assertRaises(PolicyError): self.runner.run({**args,"risk_summary":"changed"},proposal["proposal_hash"])

    def test_host_execution_and_syntax_rejected(self):
        for script in ["import os", "open('x','w')", "print((1).__class__)", "while True:\n pass", "x=[i for i in range(10)]", "exec('print(1)')"]:
            with self.assertRaises(PolicyError): self.runner.prepare(self.plan(script))

    def test_declared_path_and_resource_limits(self):
        args=self.plan("write_file('undeclared.txt', 'x')")
        result=self.runner.run(args,self.runner.prepare(args)["proposal_hash"])
        self.assertEqual(result["status"],"failed")
        self.assertFalse((self.root/"undeclared.txt").exists())
        args=self.plan("print('x' * 100000000)")
        self.assertEqual(self.runner.run(args,self.runner.prepare(args)["proposal_hash"])["status"],"failed")

    def test_network_and_shell_plan_rejected(self):
        for update in [{"commands":["whoami"]},{"network_destinations":["https://example.com"]},{"read_paths":["../outside"],"permissions":["read_files"]}]:
            with self.assertRaises(PolicyError): self.runner.prepare(self.plan("pass",**update))

    def test_nested_expansion_stops_before_rendering(self):
        args=self.plan("x = ['a']\nfor i in range(40):\n x = [x,x]\nprint(x)")
        result=self.runner.run(args,self.runner.prepare(args)["proposal_hash"])
        self.assertEqual(result["status"],"failed")
        self.assertIn("limit",result["error"])
        self.assertLess(result["duration_seconds"],3)

    def test_no_silent_undeclared_expected_output(self):
        args=self.plan("pass",create_paths=["result.txt"],expected_outputs=["result.txt"],permissions=["create_files"])
        result=self.runner.run(args,self.runner.prepare(args)["proposal_hash"])
        self.assertEqual(result["status"],"failed")
        self.assertEqual(result["exit_code"],1)
        self.assertIn(str((self.root/"result.txt").resolve()),result["missing_outputs"])

    def test_exact_script_bytes_and_stored_proposal_integrity(self):
        import hashlib
        args=self.plan("print('line one')\r\nprint('line two')\r\n")
        proposal=self.runner.prepare(args)
        self.assertEqual(proposal["script_sha256"],hashlib.sha256(args["script"].encode()).hexdigest())
        self.assertEqual(self.runner.run(args,proposal["proposal_hash"])["status"],"completed")
        # Tampering is deliberate synthetic evidence; the original bytes remain
        # retained separately and no file is removed.
        stored=Path(proposal["script_path"])
        (self.root/"original_script_bytes.txt").write_bytes(stored.read_bytes())
        stored.write_text("print('tampered')",encoding="utf-8")
        with self.assertRaises(PolicyError): self.runner.run(args,proposal["proposal_hash"])

    def test_hardlinked_read_declaration_rejected(self):
        import os
        outside=Path(tempfile.mkdtemp(prefix="copilot_code_outside_fixture_"))
        original=outside/"harmless_fixture.txt"
        original.write_text("Synthetic harmless fixture")
        alias=self.root/"alias.txt"
        try: os.link(original,alias)
        except OSError: self.skipTest("Hardlink creation unavailable")
        args=self.plan("print(read_file('alias.txt'))",read_paths=["alias.txt"],permissions=["read_files"])
        with self.assertRaises(PolicyError): self.runner.prepare(args)

    def source_plan(self, script="print('exact downloaded artifact')\r\n", name="downloaded.py", **updates):
        source=self.root/name
        data=script.encode("utf-8")
        source.write_bytes(data)
        args=self.plan(script,source_path=str(source),source_sha256=hashlib.sha256(data).hexdigest(),
                       read_paths=[str(source)],permissions=["read_files"])
        args.update(updates)
        return source,args

    def test_downloaded_source_exact_hash_bytes_and_metadata_without_created_outputs(self):
        source,args=self.source_plan("# coding: utf-8\r\nprint('café')\r\nprint('second line')")
        original=source.read_bytes()
        prepared=self.runner.prepare(args)
        verification={"path":str(source.resolve()),"sha256":hashlib.sha256(original).hexdigest(),
                      "size":len(original),"exact_script_bytes":True}
        self.assertEqual(verification,prepared["source_verification"])
        self.assertEqual(original,Path(prepared["script_path"]).read_bytes())
        self.assertEqual(str(source.resolve()),prepared["plan"]["source_path"])
        result=self.runner.run(args,prepared["proposal_hash"])
        self.assertEqual("completed",result["status"])
        self.assertEqual("café\nsecond line\n",result["stdout"])
        self.assertEqual([],result["created_paths"])
        self.assertEqual(verification,result["source_verification"])
        self.assertEqual(original,source.read_bytes())

    def test_source_fields_are_optional_paired_and_script_stays_required(self):
        self.assertEqual({"subprocesses","source_path","source_sha256","interpreter","arguments","imports",
                          "modify_paths","create_roots","timeout_seconds","max_output_chars","expected_effects","viewer_windows"},OPTIONAL)
        self.assertEqual(FIELDS-OPTIONAL,REQUIRED)
        self.assertIn("script",REQUIRED)
        _,args=self.source_plan()
        for field in ("source_path","source_sha256","script"):
            incomplete={key:value for key,value in args.items() if key!=field}
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.runner.prepare(incomplete)
        self.assertNotIn("source_verification",self.runner.prepare(self.plan("print(1)")))

    def test_source_requires_declared_read_and_permission_before_artifact_read(self):
        source,args=self.source_plan()
        for updates in ({"read_paths":[]},{"permissions":[]},{"read_paths":["another.py"]}):
            with self.subTest(updates=updates),self.assertRaises(PolicyError):
                self.runner.prepare({**args,**updates})
        # Relative declared source remains one normalized, disclosed capability.
        relative={**args,"source_path":source.name,"read_paths":[source.name]}
        prepared=self.runner.prepare(relative)
        self.assertEqual(str(source.resolve()),prepared["plan"]["source_path"])
        self.assertEqual([str(source.resolve())],prepared["plan"]["read_paths"])

    def test_source_raw_sha_script_and_line_endings_must_all_match(self):
        _,args=self.source_plan()
        for updates in ({"source_sha256":"0"*64},
                        {"source_sha256":args["source_sha256"].upper()},
                        {"script":args["script"].replace("\r\n","\n")},
                        {"script":"print('substitute')\r\n"}):
            with self.subTest(updates=updates),self.assertRaises(PolicyError):
                self.runner.prepare({**args,**updates})

    def test_source_changed_after_approval_cannot_execute_or_reuse_original_grant(self):
        source,args=self.source_plan("write_file('must-not-exist.txt', 'approved')\n",
                                     create_paths=["must-not-exist.txt"],expected_outputs=["must-not-exist.txt"],
                                     permissions=["read_files","create_files"])
        prepared=self.runner.prepare(args)
        changed=b"write_file('must-not-exist.txt', 'changed')\n"
        source.write_bytes(changed)
        with self.assertRaises(PolicyError):
            self.runner.run(args,prepared["proposal_hash"])
        changed_args={**args,"script":changed.decode("utf-8"),"source_sha256":hashlib.sha256(changed).hexdigest()}
        with self.assertRaises(PolicyError):
            self.runner.run(changed_args,prepared["proposal_hash"])
        self.assertFalse((self.root/"must-not-exist.txt").exists())

    def test_source_rejects_outside_roots_non_python_nonregular_and_oversize(self):
        source,args=self.source_plan()
        outside=Path(tempfile.mkdtemp(prefix="copilot_source_outside_"))/"outside.py"
        outside.write_bytes(source.read_bytes())
        with self.assertRaises(PolicyError):
            self.runner.prepare({**args,"source_path":str(outside),"read_paths":[str(outside)]})
        text=self.root/"source.txt"
        text.write_bytes(source.read_bytes())
        with self.assertRaises(PolicyError):
            self.runner.prepare({**args,"source_path":str(text),"read_paths":[str(text)]})
        directory=self.root/"directory.py"
        directory.mkdir()
        with self.assertRaises(PolicyError):
            self.runner.prepare({**args,"source_path":str(directory),"read_paths":[str(directory)]})
        source.write_bytes(b"#"*200001)
        with self.assertRaises(PolicyError):
            self.runner.prepare(args)

    def test_source_binding_never_relaxes_ast_subset_or_silently_changes_encoding(self):
        for script in ("import os\n", "\ufeffprint(1)\r\n", "# coding: latin-1\nprint(1)\n"):
            with self.subTest(script=script):
                _,args=self.source_plan(script)
                with self.assertRaises(PolicyError):
                    self.runner.prepare(args)

    def test_source_verification_is_returned_even_for_failed_subset_execution(self):
        _,args=self.source_plan("print('x' * 100000000)\n")
        prepared=self.runner.prepare(args)
        result=self.runner.run(args,prepared["proposal_hash"])
        self.assertEqual("failed",result["status"])
        self.assertEqual(prepared["source_verification"],result["source_verification"])
        self.assertEqual([],result["created_paths"])


class LocalPythonRunnerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="copilot_local_python_test_"))
        self.registry = ManagedProcessRegistry(self.root)
        self.runner = CodeRunner(PathPolicy([self.root]), self.root,
                                 {"tool_timeout": 5, "max_output_chars": 4000})

    def plan(self, script, **updates):
        value = {"script":script, "purpose":"Synthetic approved local Python test", "language":"local_python",
                 "working_directory":str(self.root), "read_paths":[], "create_paths":[], "modify_paths":[],
                 "expected_outputs":[], "commands":[], "subprocesses":[], "network_destinations":[],
                 "permissions":[], "risk_summary":"Exact synthetic local process only.",
                 "recovery_notes":"Stop owned processes and retain audit evidence.",
                 "interpreter":sys.executable, "arguments":[], "imports":[], "timeout_seconds":3,
                 "max_output_chars":2000, "expected_effects":["bounded stdout"], "viewer_windows":[]}
        value.update(updates)
        return value

    def run_plan(self, plan):
        prepared = self.runner.prepare(plan)
        return asyncio.run(self.runner.run_async(plan, prepared["proposal_hash"], process_registry=self.registry))

    def test_package_scratch_roots_require_internal_grant_and_are_usable(self):
        scratch = self.root / "outputs" / ".stage-scratch" / "stage" / "attempt"
        scratch.mkdir(parents=True)
        args = self.plan(
            "import os\nfrom pathlib import Path\nscratch=Path(os.environ['COPILOT_PACKAGE_STAGE_SCRATCH'])\np=scratch/'nested'/'draft.txt'\np.parent.mkdir()\np.write_text('a')\np.write_text(p.read_text()+'b')\nPath('result.txt').write_text('verified')\n",
            imports=["os", "pathlib"], create_paths=["result.txt"], expected_outputs=["result.txt"],
            create_roots=[str(scratch)], permissions=["create_files"],
            expected_effects=["Create verified output and stage-local scratch"])
        with self.assertRaises(PolicyError):
            self.runner.prepare(args)
        self.runner._authorize_package_scratch_root(scratch, self.root / "outputs")
        prepared = self.runner.prepare(args)
        result = asyncio.run(self.runner.run_async(args, prepared["proposal_hash"], process_registry=self.registry))
        self.assertEqual("completed", result["status"], result)
        self.assertEqual("ab", (scratch / "nested" / "draft.txt").read_text(encoding="utf-8"))
        self.assertEqual("verified", (self.root / "result.txt").read_text(encoding="utf-8"))

    def test_direct_package_scratch_grant_rejects_outside_policy_root(self):
        outside = Path(tempfile.mkdtemp(prefix="outside_code_policy_"))
        with self.assertRaises(PolicyError):
            self.runner._authorize_package_scratch_root(outside, self.root)

    def test_package_scratch_cannot_read_sibling_scratch_or_outside_files(self):
        output_root = self.root / "outputs"
        scratch = output_root / ".stage-scratch" / "stage-a" / "attempt"
        other_scratch = output_root / ".stage-scratch" / "stage-b" / "attempt"
        scratch.mkdir(parents=True)
        other_scratch.mkdir(parents=True)
        (other_scratch / "secret.txt").write_text("private", encoding="utf-8")
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        script = (
            "from pathlib import Path\n"
            f"targets=[Path({str(other_scratch / 'secret.txt')!r}), Path({str(outside)!r})]\n"
            "for target in targets:\n"
            " try: target.read_text()\n"
            " except PermissionError: pass\n"
            " else: raise AssertionError('read escaped this stage scratch')\n"
            "print('blocked')\n")
        plan = self.plan(script, imports=["pathlib"], create_roots=[str(scratch)], permissions=[],
                         expected_effects=["Deny reads outside this attempt scratch"])
        self.runner._authorize_package_scratch_root(scratch, output_root)
        prepared = self.runner.prepare(plan)
        result = asyncio.run(self.runner.run_async(plan, prepared["proposal_hash"], process_registry=self.registry))
        self.assertEqual("completed", result["status"], result)
        self.assertEqual(["blocked"], result["stdout"].splitlines())

    def test_scratch_stream_blocks_buffer_truncate_and_over_limit_write(self):
        scratch = self.root / "outputs" / ".stage-scratch" / "stage" / "attempt"
        scratch.mkdir(parents=True)
        args = self.plan(
            "import os, sys\nfrom pathlib import Path\np=Path(os.environ['COPILOT_PACKAGE_STAGE_SCRATCH'])/'x.bin'\nwith open(p,'wb') as f:\n f.write(b'x')\n try: f.buffer.write(b'y')\n except PermissionError: pass\n else: raise AssertionError('buffer bypass')\n try: f._stream.write(b'y')\n except PermissionError: pass\n else: raise AssertionError('private stream bypass')\n try: f.truncate(60000000)\n except PermissionError: pass\n else: raise AssertionError('truncate bypass')\n try: os.write(os.open(p, os.O_WRONLY|os.O_APPEND), b'z')\n except PermissionError: pass\n else: raise AssertionError('raw descriptor bypass')\n try: import mmap\n except PermissionError: pass\n else: raise AssertionError('mmap bypass')\n try: import msvcrt\n except PermissionError: pass\n else: raise AssertionError('CRT write bypass')\n try:\n  raw=sys.modules['_io'].open(p,'ab')\n  try: raw.write(b'x'*(50*1024*1024+1))\n  finally: raw.close()\n except PermissionError: pass\n else: raise AssertionError('private _io.open quota bypass')\n",
            imports=["os", "pathlib", "sys", "mmap", "msvcrt"], create_roots=[str(scratch)], permissions=[],
            expected_effects=["Exercise bounded stage scratch"])
        self.runner._authorize_package_scratch_root(scratch, self.root / "outputs")
        prepared = self.runner.prepare(args)
        result = asyncio.run(self.runner.run_async(args, prepared["proposal_hash"], process_registry=self.registry))
        self.assertEqual("completed", result["status"], result)
        self.assertEqual(1, (scratch / "x.bin").stat().st_size)

        too_large = self.plan(
            "import os\nfrom pathlib import Path\np=Path(os.environ['COPILOT_PACKAGE_STAGE_SCRATCH'])/'large.bin'\np.write_bytes(b'x'*(50*1024*1024+1))\n",
            imports=["os", "pathlib"], create_roots=[str(scratch)], permissions=[],
            expected_effects=["Reject oversized stage scratch write"])
        self.runner._authorize_package_scratch_root(scratch, self.root / "outputs")
        oversized = self.runner.prepare(too_large)
        rejected = asyncio.run(self.runner.run_async(too_large, oversized["proposal_hash"], process_registry=self.registry))
        self.assertEqual("failed", rejected["status"])
        self.assertEqual(0, (scratch / "large.bin").stat().st_size)

    def test_package_scratch_quota_counts_buffer_bytes_not_elements(self):
        scratch = self.root / "outputs" / ".stage-scratch" / "stage" / "attempt"
        scratch.mkdir(parents=True)
        plan = self.plan(
            "import os\nfrom array import array\nfrom pathlib import Path\n"
            "p=Path(os.environ['COPILOT_PACKAGE_STAGE_SCRATCH'])/'wide.bin'\n"
            "payload=memoryview(array('Q',[1])*6600000)\n"
            "with open(p,'wb') as f:\n"
            " try: f.write(payload)\n"
            " except PermissionError: print('blocked')\n"
            " else: raise AssertionError('buffer byte quota bypass')\n",
            imports=["os", "array", "pathlib"], create_roots=[str(scratch)], permissions=[],
            expected_effects=["Count actual buffer bytes for scratch quota"])
        self.runner._authorize_package_scratch_root(scratch, self.root / "outputs")
        prepared = self.runner.prepare(plan)
        result = asyncio.run(self.runner.run_async(plan, prepared["proposal_hash"], process_registry=self.registry))
        self.assertEqual("completed", result["status"], result)
        self.assertEqual(["blocked"], result["stdout"].splitlines())
        self.assertEqual(0, (scratch / "wide.bin").stat().st_size)

    def test_declared_import_arguments_and_created_output_are_executed_and_verified(self):
        plan = self.plan("import sys\nfrom pathlib import Path\nPath('result.txt').write_text(sys.argv[1], encoding='utf-8')\nprint(sys.argv[1])\n",
                         imports=["sys", "pathlib"], arguments=["approved-value"],
                         create_paths=["result.txt"], expected_outputs=["result.txt"],
                         permissions=["create_files"], expected_effects=["Create result.txt", "Print approved-value"])
        result = self.run_plan(plan)
        self.assertEqual("completed", result["status"], result)
        self.assertEqual(["approved-value"], result["stdout"].splitlines())
        self.assertEqual("approved-value", (self.root / "result.txt").read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(b"approved-value").hexdigest(), result["outputs"][0]["sha256"])
        self.assertTrue(Path(result["audit_path"]).is_file())
        audit = json.loads(Path(result["audit_path"]).read_text(encoding="utf-8"))
        self.assertEqual(result["proposal_hash"], audit["prepared"]["proposal_hash"])
        self.assertEqual(sys.executable, result["interpreter"])

    @unittest.skipUnless(os.name == "nt", "Windows CreateProcess working-directory limit")
    def test_worker_starts_before_changing_into_long_approved_directory(self):
        long_working = self.root.joinpath(*(f"segment_{index}_" + "x" * 42 for index in range(5)))
        long_working.mkdir(parents=True)
        self.assertGreater(len(str(long_working)), 260)
        plan = self.plan(
            "from pathlib import Path\nPath('result.txt').write_text('long-path-ok', encoding='utf-8')\n",
            working_directory=str(long_working), create_paths=["result.txt"],
            expected_outputs=["result.txt"], permissions=["create_files"],
            imports=["pathlib"],
            expected_effects=["Create result.txt inside the approved long working directory"])

        result = self.run_plan(plan)

        self.assertEqual("completed", result["status"], result)
        self.assertEqual("long-path-ok", (long_working / "result.txt").read_text(encoding="utf-8"))

    def test_undeclared_import_file_scope_network_and_shell_fail_closed(self):
        with self.assertRaisesRegex(PolicyError, "undeclared import"):
            self.runner.prepare(self.plan("import os\n", imports=[]))
        with self.assertRaises(PolicyError):
            self.runner.prepare(self.plan("print('x')", network_destinations=["https://example.com"], permissions=[]))
        with self.assertRaises(PolicyError):
            self.runner.prepare(self.plan("print('x')", commands=["whoami"]))
        result = self.run_plan(self.plan("open('undeclared.txt', 'w').write('x')\n"))
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["side_effects_uncertain"])
        self.assertIn("outside the approved", result["stderr"])
        self.assertFalse((self.root / "undeclared.txt").exists())
        with self.assertRaisesRegex(PolicyError, "not exposed"):
            self.runner.prepare(self.plan("import copilot_agent.orchestrator\n",
                                          imports=["copilot_agent.orchestrator"]))
        with self.assertRaisesRegex(PolicyError, "preflight failed before approval"):
            self.runner.prepare(self.plan("import unavailable_synthetic_dependency\n",
                                          imports=["unavailable_synthetic_dependency"]))

    def test_worker_rejects_undeclared_directory_and_link_mutations(self):
        outside = self.root.parent / (self.root.name + "_outside")
        target = self.root / "result.txt"
        for operation in (
                f"Path({str(outside)!r}).mkdir()",
                f"Path({str(outside)!r}).symlink_to(Path({str(target)!r}))",
                f"os.link({str(target)!r}, {str(outside)!r})"):
            with self.subTest(operation=operation):
                script = "import os\nfrom pathlib import Path\n" + operation + "\n"
                plan = self.plan(script, imports=["os", "pathlib"], permissions=["create_files"],
                                 expected_effects=["Reject mutation outside approved output root"])
                result = self.run_plan(plan)
                self.assertEqual("failed", result["status"], result)
                expected_error = "unavailable" if "link" in operation else "outside the approved"
                self.assertIn(expected_error, result["stderr"])
                self.assertFalse(outside.exists())

    def test_registry_preflight_uses_the_active_timeout_limit(self):
        plan = self.plan("print('validated only')\n", timeout_seconds=20)
        context = {"config":{"allowed_roots":[str(self.root)], "allowed_domains":[],
                             "tool_timeout":30, "max_output_chars":4000},
                   "session_dir":str(self.root)}
        ToolRegistry().validate_call("code_runner", plan, context)
        context["config"]["tool_timeout"] = 10
        with self.assertRaisesRegex(PolicyError, "limit of 10"):
            ToolRegistry().validate_call("code_runner", plan, context)

    @unittest.skipUnless(os.name == "nt", "Windows desktop capability")
    def test_exposed_desktop_api_preflights_and_runs_in_isolated_worker(self):
        script = ("import json\nfrom pathlib import Path\n"
                  "from copilot_agent.desktop import enumerate_displays\n"
                  "displays=enumerate_displays()\n"
                  "Path('display-evidence.json').write_text(json.dumps(displays),encoding='utf-8')\n"
                  "print(json.dumps({'display_count':len(displays)}))\n")
        plan = self.plan(script, imports=["json", "pathlib", "copilot_agent.desktop"],
                         create_paths=["display-evidence.json"], expected_outputs=["display-evidence.json"],
                         permissions=["create_files", "desktop_capture"],
                         expected_effects=["Enumerate displays", "Create verified display evidence"])
        prepared = self.runner.prepare(plan)
        self.assertTrue(prepared["runtime_binding"]["import_preflight"]["ok"])
        self.assertIn("copilot_agent.desktop", prepared["runtime_binding"]["import_preflight"]["imports"])
        result = self.run_plan(plan)
        self.assertEqual("completed", result["status"], result)
        displays = json.loads((self.root / "display-evidence.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(displays), 1)
        self.assertTrue(result["outputs"][0]["readable"])
        audit = json.loads(Path(result["audit_path"]).read_text(encoding="utf-8"))
        capability = next(item for item in audit["worker_events"] if item["event"] == "capabilities_validated")
        self.assertEqual(["copilot_agent.desktop"], capability["application_imports"])

    def test_interpreter_arguments_permissions_and_runtime_binding_change_hash(self):
        plan = self.plan("print('one')\n")
        prepared = self.runner.prepare(plan)
        self.assertIn("interpreter_sha256", prepared["runtime_binding"])
        for changed in ({**plan, "script":"print('two')\n"},
                        {**plan, "arguments":["changed"]},
                        {**plan, "expected_effects":["changed effect"]}):
            with self.subTest(changed=changed):
                self.assertNotEqual(prepared["proposal_hash"], self.runner.prepare(changed)["proposal_hash"])
                with self.assertRaises(PolicyError):
                    asyncio.run(self.runner.run_async(changed, prepared["proposal_hash"], process_registry=self.registry))

    def test_timeout_returns_cancelled_and_retains_audit(self):
        plan = self.plan("import time\ntime.sleep(30)\n", imports=["time"], timeout_seconds=1)
        result = self.run_plan(plan)
        self.assertEqual("cancelled", result["status"])
        self.assertIsNone(result["exit_code"] if result["exit_code"] is None else None)
        self.assertTrue(Path(result["audit_path"]).is_file())

    def test_timeout_limit_reports_actual_cap_and_configuration_choice(self):
        with self.assertRaisesRegex(PolicyError, "limit of 5.*approved configuration change"):
            self.runner.prepare(self.plan("print('never runs')\n", timeout_seconds=6))

    def test_task_cancellation_stops_worker_and_records_cancelled_audit(self):
        async def exercise():
            plan = self.plan("import time\ntime.sleep(30)\n", imports=["time"], timeout_seconds=5)
            prepared = self.runner.prepare(plan)
            task = asyncio.create_task(self.runner.run_async(plan, prepared["proposal_hash"], process_registry=self.registry))
            await asyncio.sleep(.2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(exercise())
        audits = list((self.root / "code_runs").glob("*/audit.json"))
        self.assertEqual(1, len(audits))
        self.assertEqual("cancelled", json.loads(audits[0].read_text(encoding="utf-8"))["status"])

    def test_managed_persistent_process_cleanup(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.registry.register({"pid":process.pid, "persistent":True, "purpose":"synthetic cleanup child"})
        outcomes = self.registry.cleanup_all()
        process.wait(timeout=5)
        self.assertTrue(outcomes[0]["stopped"])
        self.assertEqual({}, self.registry.records)

    def test_three_viewers_on_display_two_require_independent_verification(self):
        class FakeRegistry:
            def __init__(self): self.registered, self.cleaned = [], []
            def register(self, item): self.registered.append(item)
            def cleanup(self, items): self.cleaned.extend(items); return [{"pid":item["pid"],"stopped":True} for item in items]
        fake = FakeRegistry()
        names = ["display-1.png", "display-2.png", "display-3.png"]
        script = "from pathlib import Path\n" + "\n".join("Path(%r).write_bytes(b'PNG evidence %d')" % (name, index) for index, name in enumerate(names, 1)) + "\n"
        viewers = [{"title":"Approved capture " + str(index), "image_path":name, "display_index":2}
                   for index, name in enumerate(names, 1)]
        plan = self.plan(script, imports=["pathlib"], create_paths=names, expected_outputs=names,
                         permissions=["create_files","window_management","persistent_processes"],
                         viewer_windows=viewers, expected_effects=["Create three captures", "Keep three viewers visible on display 2"])
        prepared = self.runner.prepare(plan)
        launched = [{"pid":9000 + index, "title":item["title"], "display_index":2,
                     "image_path":str((self.root / names[index]).resolve()), "persistent":True}
                    for index, item in enumerate(viewers)]
        observed = {"ok":True, "display_count":3, "displays":[{"display_index":2}],
                    "windows":[{"title":item["title"], "visible":True, "contained_on_display":True,
                                "display_index":2, "image_path":str((self.root / names[index]).resolve())}
                               for index, item in enumerate(viewers)]}
        with patch("copilot_agent.local_python_runner.launch_viewers", return_value=launched), \
             patch("copilot_agent.local_python_runner.inspect_windows", return_value=observed):
            result = asyncio.run(self.runner.run_async(plan, prepared["proposal_hash"], process_registry=fake))
        self.assertEqual("completed", result["status"], result)
        self.assertEqual(3, len(result["outputs"]))
        self.assertTrue(result["verification"]["ok"])
        self.assertEqual({2}, {item["display_index"] for item in result["verification"]["windows"]})
        self.assertEqual(3, len(fake.registered))

    def test_failed_window_verification_cleans_persistent_viewers(self):
        class FakeRegistry:
            def __init__(self): self.cleaned = []
            def register(self, item): raise AssertionError("failed viewers must not persist")
            def cleanup(self, items): self.cleaned.extend(items); return [{"pid":item["pid"],"stopped":True} for item in items]
        fake = FakeRegistry()
        plan = self.plan("from pathlib import Path\nPath('capture.png').write_bytes(b'evidence')\n", imports=["pathlib"],
                         create_paths=["capture.png"], expected_outputs=["capture.png"],
                         permissions=["create_files","window_management","persistent_processes"],
                         viewer_windows=[{"title":"Missing viewer","image_path":"capture.png","display_index":2}],
                         expected_effects=["Verify viewer"])
        prepared = self.runner.prepare(plan)
        launched = [{"pid":9100,"title":"Missing viewer","display_index":2,
                     "image_path":str((self.root / 'capture.png').resolve()),"persistent":True}]
        with patch("copilot_agent.local_python_runner.launch_viewers", return_value=launched), \
             patch("copilot_agent.local_python_runner.inspect_windows", return_value={"ok":False,"display_count":3,"displays":[],"windows":[]}):
            result = asyncio.run(self.runner.run_async(plan, prepared["proposal_hash"], process_registry=fake))
        self.assertEqual("failed", result["status"])
        self.assertEqual(1, len(fake.cleaned))
