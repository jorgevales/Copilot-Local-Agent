import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from copilot_agent.app import configure_isolated_test_workspace
from copilot_agent.config import Config


class IsolatedProofModeTests(unittest.TestCase):
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
            with self.assertRaisesRegex(ValueError, "new or empty"):
                configure_isolated_test_workspace(Config(root=root, storage_dir=root / "other"), target)


if __name__ == "__main__":
    unittest.main()
