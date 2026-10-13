import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch
from types import SimpleNamespace

from copilot_agent.app import configure_isolated_test_workspace
from copilot_agent.config import Config
from copilot_agent.policy import PathPolicy, PolicyError
from copilot_agent.tools import tool_path_policy
from tests.live_package_run import (load_proof_config, package_archive_was_executed,
                                    proof_retry_instruction, recover_denied_run_plan,
                                    proof_import_scope_valid, proof_description_is_synthetic,
                                    latest_package_run_was_denied,
                                    should_recover_denied_run_plan,
                                     latest_failed_proof_run_state, DEFAULT_PROOF_REVISIONS,
                                     parse_proof_revision_limit, proof_revision_allowed,
                                     require_dedicated_existing_profile)


class IsolatedProofModeTests(unittest.TestCase):
    def test_proof_file_tools_cannot_access_sibling_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            current = root / 'workspace' / 'live-package-proof' / 'current'
            sibling = current.parent / 'sibling'
            current.mkdir(parents=True)
            sibling.mkdir()
            config = SimpleNamespace(_automation_test_mode=True, _proof_file_workspace=str(current),
                                     profile_dir=root / 'edge-profile')
            context = {'config': config, 'session_dir': root / 'session',
                       'policy': PathPolicy([str(root)])}
            for name in ('files.read', 'files.create', 'files.mkdir', 'system.disk'):
                with self.subTest(name=name):
                    policy = tool_path_policy(name, context)
                    self.assertEqual((current / 'result.txt').resolve(),
                                     policy.resolve(current / 'result.txt'))
                    with self.assertRaises(PolicyError):
                        policy.resolve(sibling / 'result.txt')

    def test_unlimited_revision_option_is_proof_only_and_default_stays_four(self):
        self.assertEqual(4, DEFAULT_PROOF_REVISIONS)
        self.assertEqual(8, parse_proof_revision_limit('8'))
        self.assertEqual(9, parse_proof_revision_limit('9'))
        self.assertIsNone(parse_proof_revision_limit('unlimited'))
        self.assertFalse(proof_revision_allowed(DEFAULT_PROOF_REVISIONS, 4))
        self.assertTrue(proof_revision_allowed(None, 1000))
        for invalid in ('0', '-1', 'many'):
            with self.subTest(invalid=invalid), self.assertRaises(Exception):
                parse_proof_revision_limit(invalid)

    def test_explicit_edge_port_requires_this_proofs_dedicated_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            runtime = root / 'runtime'
            profile = runtime / 'acceptance' / 'package-run-20261013T111348Z-7f22f7bf' / 'edge-profile'
            profile.mkdir(parents=True)
            config = type('ProofConfig', (), {'runtime_dir': runtime, 'profile_dir': profile,
                                              'debug_port': 63741, 'attach_existing': True})()
            require_dedicated_existing_profile(config, 63741)
            unrelated_proof = runtime / 'acceptance' / 'other-run' / 'edge-profile'
            unrelated_proof.mkdir(parents=True)
            config.profile_dir = unrelated_proof
            with self.assertRaises(AssertionError):
                require_dedicated_existing_profile(config, 63741)
            config.profile_dir = root / 'unrelated' / 'edge-profile'
            with self.assertRaises(AssertionError):
                require_dedicated_existing_profile(config, 63741)
            config.profile_dir = profile
            config.attach_existing = False
            with self.assertRaises(AssertionError):
                require_dedicated_existing_profile(config, 63741)

    def test_failed_archive_requires_a_fresh_revision_but_denied_run_can_be_retried(self):
        calls = {
            "run-denied": {"request": {"name": "automation.run",
                                        "arguments": {"expected_sha256": "a" * 64}},
                           "result": {"ok": False,
                                      "error": {"code": "approval_denied"}}},
            "run-failed": {"request": {"name": "automation.run",
                                         "arguments": {"expected_sha256": "b" * 64}},
                            "result": {"ok": True, "result": {"status": "failed"}}},
        }

        self.assertFalse(package_archive_was_executed(calls, "a" * 64))
        self.assertTrue(package_archive_was_executed(calls, "b" * 64))
        self.assertFalse(package_archive_was_executed(calls, "c" * 64))
        self.assertTrue(latest_package_run_was_denied({
            "run": calls["run-denied"]
        }))
        self.assertFalse(latest_package_run_was_denied({
            "run": calls["run-failed"]
        }))
        self.assertFalse(should_recover_denied_run_plan(calls, None, None))
        self.assertTrue(should_recover_denied_run_plan({"run": calls["run-denied"]}, None, None))
        self.assertFalse(should_recover_denied_run_plan({"run": calls["run-denied"]}, "capture-id", None))
        self.assertFalse(should_recover_denied_run_plan({"run": calls["run-denied"]}, None, {"request_id": "pending"}))

    def test_declared_hash_listed_local_package_module_is_allowed(self):
        manifest = {
            "files": {"project/src/common.py": "a" * 64},
            "dependencies": {"modules": ["common"]},
            "capabilities": {"imports": ["common", "csv"]},
            "stages": [{"imports": ["common", "csv"]}],
        }

        self.assertTrue(proof_import_scope_valid(manifest))
        manifest["files"]["project/src/os.py"] = "b" * 64
        manifest["capabilities"]["imports"].append("os")
        self.assertFalse(proof_import_scope_valid(manifest))

    def test_proof_accepts_invented_data_description_as_synthetic_scope(self):
        self.assertTrue(proof_description_is_synthetic({
            "description": "Generate from entirely invented transit reliability data."
        }))
        self.assertTrue(proof_description_is_synthetic({"description": "Synthetic data for fictional transit routes."}))
        self.assertFalse(proof_description_is_synthetic({"description": "Analyze customer transit data."}))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic wrapper around customer trip records."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Entirely invented transit data using live customer records."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic data generated from production operational logs."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic data reconstructed from a live feed."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic data based on real-world measurements."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Fictional data derived from real source records."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic data derived from genuine observations."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic data from authentic observations."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Not synthetic data; use production records."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "No synthetic data; manually assembled from the schedule."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic data is not used."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Do not use synthetic data."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic data isn't used."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "We don't use synthetic data."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic data shouldn't be used."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic data will not be used."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic data will never be used."
        }))
        self.assertFalse(proof_description_is_synthetic({
            "description": "Synthetic data must not be used."
        }))
        self.assertFalse(proof_description_is_synthetic({"description": None}))

    def test_latest_failed_proof_state_recovers_only_run_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "isolated-workspace"
            run = workspace / "runs" / "run-one"
            run.mkdir(parents=True)
            state_path = run / "state.json"
            state_path.write_text(__import__("json").dumps({
                "run_id": "run-one", "status": "failed", "archive_sha256": "a" * 64,
                "stages": {"generate_data": {"status": "failed",
                                               "result": {"error": "worker did not start",
                                                          "side_effects_uncertain": False}}},
                "outputs": [],
            }), encoding="utf-8")

            recovered = latest_failed_proof_run_state(workspace)

            self.assertEqual(str(state_path.resolve()), recovered["state_path"])
            self.assertEqual("a" * 64, recovered["archive_sha256"])

    def test_proof_retry_reuses_reviewed_archive_after_harness_only_denial(self):
        instruction = proof_retry_instruction({
            "outputs_match_request": True,
            "archive_path": "C:/proof/deliveries/transit.zip",
            "archive_sha256": "f" * 64,
            "workspace": "C:/proof/workspace/live-package-proof/run-one",
        })

        self.assertIn("local proof-harness allowlist bug", instruction)
        self.assertIn("fresh v9 ZIP", instruction)
        self.assertIn("inline the small shared common.py helpers", instruction)
        self.assertIn("automatically inspect the new fingerprint", instruction)
        self.assertIn("original isolated workspace", instruction)

    def test_newer_approved_run_prevents_recovery_of_an_older_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            acceptance = root / "acceptance"
            acceptance.mkdir()
            old = acceptance / "package-run-20261013T120000Z-old"
            new = acceptance / "package-run-20261013T130000Z-new"
            current = acceptance / "package-run-current"
            for folder in (old, new, current):
                folder.mkdir(parents=True)
            (old / "report.json").write_text(__import__("json").dumps({
                "decisions": [{"tool": "automation.run", "decision": "deny"}],
                "reviews": [{"status": "passed", "failures": [],
                             "archive_sha256": "a" * 64}],
                "all_calls": {},
            }), encoding="utf-8")
            (new / "report.json").write_text(__import__("json").dumps({
                "decisions": [{"tool": "automation.run", "decision": "once"}],
            }), encoding="utf-8")
            config = type("Config", (), {"storage_dir": root / "storage",
                                          "workspace_dir": root / "workspace"})()

            result = recover_denied_run_plan(config, acceptance, current)

            self.assertIsNone(result)

    def test_live_package_harness_unwraps_proof_settings_without_widening_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            storage = root / "proof-runs" / "live"
            storage.mkdir(parents=True)
            settings = root / "settings.json"
            settings.write_text(__import__("json").dumps({
                "schema_version": "1.0", "storage_dir": str(storage),
                "python_executable": sys.executable,
                "config": {"allowed_roots": ["."], "allowed_domains": ["example.com"],
                           "response_timeout": 180, "response_max_duration": 900},
                "edge_executables": {"proof": sys.executable}, "debug_ports": {"proof": 9460},
            }), encoding="utf-8")

            config = load_proof_config(settings)

            self.assertEqual(storage, config.storage_dir)
            self.assertEqual(9460, config.debug_port)
            self.assertEqual(sys.executable, config.edge_executable)
            self.assertFalse(config.attach_existing)
            self.assertTrue(config._automation_test_mode)
            self.assertFalse(config._s_storage_verified)

    def test_config_load_uses_explicit_proof_storage_without_s_drive_lookup(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp).resolve() / "proof"
            with patch("copilot_agent.config.default_local_storage", side_effect=AssertionError("S drive lookup")):
                config = Config.load(storage_override=target)
            self.assertEqual(target, config.storage_dir)

    def test_only_empty_c_drive_project_proof_child_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            config = Config(root=root, storage_dir=root / "user-storage")
            accepted = configure_isolated_test_workspace(config, root / "runtime" / "proof-runs" / "run-one")
            self.assertTrue(config._automation_test_mode)
            self.assertEqual([str(accepted)], config.allowed_roots)
            self.assertEqual(accepted, config.knowledge_directory)
            for rejected in (root / "runtime" / "proof-runs", root / "outside"):
                with self.subTest(path=rejected), self.assertRaises(ValueError):
                    configure_isolated_test_workspace(Config(root=root, storage_dir=root / "other"), rejected)

    def test_nonempty_workspace_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = root / "runtime" / "proof-runs" / "used"
            target.mkdir(parents=True)
            (target / "keep.txt").write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "only be used to resume"):
                configure_isolated_test_workspace(Config(root=root, storage_dir=root / "other"), target)

    def test_nonempty_workspace_is_allowed_only_for_a_session_resume_inside_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = root / "runtime" / "proof-runs" / "used"
            session = target / "runtime" / "sessions" / "session-one"
            session.mkdir(parents=True)
            (session / "session.json").write_text("{}", encoding="utf-8")
            (target / "keep.txt").write_text("preserve", encoding="utf-8")
            config = Config(root=root, storage_dir=root / "other")

            accepted = configure_isolated_test_workspace(config, target, resume_session=session)

            self.assertEqual(target, accepted)
            self.assertEqual("preserve", (target / "keep.txt").read_text(encoding="utf-8"))
            for resume in (None, root / "outside" / "session", target / "runtime" / "sessions" / "missing"):
                with self.subTest(resume=resume), self.assertRaisesRegex(ValueError, "only be used to resume"):
                    configure_isolated_test_workspace(Config(root=root, storage_dir=root / "other"), target,
                                                      resume_session=resume)


if __name__ == "__main__":
    unittest.main()
