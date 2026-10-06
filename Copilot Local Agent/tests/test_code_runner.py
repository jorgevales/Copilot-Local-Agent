import hashlib
import tempfile
import unittest
from pathlib import Path
from copilot_agent.code_runner import CodeRunner, FIELDS, OPTIONAL, REQUIRED
from copilot_agent.policy import PathPolicy, PolicyError


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
        self.assertEqual({"subprocesses","source_path","source_sha256"},OPTIONAL)
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
