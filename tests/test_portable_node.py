from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from copilot_agent import portable_node


class PortableNodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.local = self.root / "local"
        self.zip = self.root / "portable.zip"

    def make_zip(self, extras=None):
        with zipfile.ZipFile(self.zip, "w") as stream:
            stream.writestr("node-v24.13.0-win-x64/node.exe", b"test PE runtime")
            stream.writestr("node-v24.13.0-win-x64/node_modules/npm/bin/npm-cli.js", b"// test npm")
            stream.writestr("node-v24.13.0-win-x64/LICENSE", b"license content")
            for name, value in (extras or {}).items():
                stream.writestr(name, value)

    def extract(self):
        return portable_node.extract_portable_node(self.zip, self.project, environ={"LOCALAPPDATA": str(self.local)})

    def test_extracts_preserves_license_and_reuses_exact_archive(self):
        self.make_zip()
        before = self.zip.read_bytes()
        node = self.extract()
        self.assertTrue(node.is_file())
        self.assertEqual((node.parent / "LICENSE").read_bytes(), b"license content")
        self.assertEqual(self.extract(), node)
        self.assertEqual(self.zip.read_bytes(), before)
        self.assertTrue(node.is_relative_to(self.local))
        self.assertFalse(list(node.parent.parent.glob("*.stage")))

    def test_readonly_first_candidate_falls_back_to_project(self):
        self.make_zip()
        self.local.write_text("a file prevents mkdir")
        node = self.extract()
        self.assertTrue(node.is_relative_to(self.project))

    def test_readonly_first_and_project_candidates_fall_back_to_temp(self):
        self.make_zip()
        self.local.write_text("blocked")
        self.project.write_text("blocked")
        scratch = self.root / "scratch"
        with patch.object(portable_node.tempfile, "gettempdir", return_value=str(scratch)):
            node = self.extract()
        self.assertTrue(node.is_relative_to(scratch))

    def test_rejects_unsafe_paths(self):
        for name in ("../escape", "node/../escape", "C:/escape", "/absolute", "node\\escape", "node/CON.txt", "node/bad:stream", "node/dot. "):
            with self.subTest(name=name):
                self.make_zip({name: b"bad"})
                with self.assertRaises(ValueError):
                    self.extract()
        self.assertFalse((self.root / "escape").exists())

    def test_rejects_symlinks_and_case_collisions(self):
        self.make_zip()
        link = zipfile.ZipInfo("node-v24.13.0-win-x64/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.zip, "a") as stream:
            stream.writestr(link, "elsewhere")
        with self.assertRaisesRegex(ValueError, "link"):
            self.extract()
        self.make_zip({"node-v24.13.0-win-x64/Node.EXE": b"collision"})
        with self.assertRaisesRegex(ValueError, "colliding"):
            self.extract()

    def test_rejects_multiple_roots_missing_npm_and_size_limits(self):
        self.make_zip({"second-root/file": b"bad"})
        with self.assertRaisesRegex(ValueError, "one distribution"):
            self.extract()
        with zipfile.ZipFile(self.zip, "w") as stream:
            stream.writestr("node/node.exe", b"runtime")
        with self.assertRaisesRegex(ValueError, "npm-cli"):
            self.extract()
        self.make_zip()
        with patch.object(portable_node, "MAX_EXTRACTED_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "extracted size"):
                self.extract()
        with patch.object(portable_node, "MAX_ARCHIVE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "compressed size"):
                self.extract()

    def test_broken_cache_is_not_reused_and_preserved(self):
        self.make_zip()
        initial = self.extract()
        initial.unlink()
        next_node = self.extract()
        self.assertNotEqual(next_node, initial)
        self.assertTrue(next_node.is_relative_to(self.project))
        self.assertTrue((initial.parent / "LICENSE").exists())

    def test_changed_source_is_rejected_and_owned_stage_is_removed(self):
        self.make_zip()
        real_digest = portable_node._digest
        calls = 0

        def changing_digest(path):
            nonlocal calls
            calls += 1
            value = real_digest(path)
            return value if calls == 1 else "0" * 64

        with patch.object(portable_node, "_digest", side_effect=changing_digest):
            with self.assertRaisesRegex(ValueError, "changed during"):
                self.extract()
        self.assertFalse(list(self.local.rglob("*.stage")))

    def test_exhausted_candidates_have_diagnostics(self):
        self.make_zip()
        self.local.write_text("blocked")
        self.project.write_text("blocked")
        scratch = self.root / "blocked-scratch"
        scratch.write_text("blocked")
        with patch.object(portable_node.tempfile, "gettempdir", return_value=str(scratch)):
            with self.assertRaisesRegex(RuntimeError, "any writable runtime location") as raised:
                self.extract()
        self.assertIn(str(self.local), str(raised.exception))
        self.assertIn(str(self.project), str(raised.exception))


if __name__ == "__main__":
    unittest.main()
