import importlib.util
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

spec = importlib.util.spec_from_file_location('version_launcher', Path(__file__).resolve().parents[1] / 'version_launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class VersionTests(unittest.TestCase):
    def fixture(self):
        root = Path(tempfile.mkdtemp(prefix='copilot-versions-'))
        live = root / 'live'
        (live / 'copilot_agent').mkdir(parents=True)
        (live / 'app.py').write_text('print("live")')
        (live / 'copilot_agent' / 'first.py').write_text('VALUE = 1')
        (live / 'copilot_agent' / 'second.py').write_text('VALUE = 2')
        proposals = root / 'delivery'
        proposals.mkdir()
        return live, proposals

    def test_multiple_changes_accumulate_and_live_is_preserved(self):
        live, delivery = self.fixture()
        (delivery / 'first.py').write_text('VALUE = 3')
        first = launcher.create_version(live, delivery)
        (delivery / 'second.py').write_text('VALUE = 4')
        second = launcher.create_version(live, delivery, first)
        self.assertEqual((second / 'copilot_agent/first.py').read_text(), 'VALUE = 3')
        self.assertEqual((second / 'copilot_agent/second.py').read_text(), 'VALUE = 4')
        self.assertEqual((live / 'copilot_agent/first.py').read_text(), 'VALUE = 1')
        self.assertEqual((first / 'copilot_agent/second.py').read_text(), 'VALUE = 2')
        self.assertTrue((second.parent / 'manifest.json').is_file())

    def test_private_files_excluded_and_bad_python_stops_creation(self):
        live, delivery = self.fixture()
        (live / 'config.local.json').write_text('private')
        (delivery / 'first.py').write_text('VALUE = 9')
        version = launcher.create_version(live, delivery)
        self.assertFalse((version / 'config.local.json').exists())
        (delivery / 'first.py').write_text('invalid python !')
        with self.assertRaises(SyntaxError):
            launcher.create_version(live, delivery)

    def test_ambiguous_flat_file_requires_relative_path(self):
        live, delivery = self.fixture()
        (live / 'tests').mkdir()
        (live / 'tests/first.py').write_text('VALUE = 0')
        (delivery / 'first.py').write_text('VALUE = 8')
        with self.assertRaises(ValueError):
            launcher.replacement_map(live, delivery)

    def test_live_selection(self):
        live, _ = self.fixture()
        self.assertEqual(launcher.choose_source(live, lambda _: '1'), live)

    def test_fixed_drop_folder_handles_same_names_and_reuses_unchanged(self):
        live, _ = self.fixture()
        (live / 'copilot_agent/app.py').write_text('VALUE = 1')
        inbox = launcher.prepare_drop_folder(live)
        (inbox / '.gitkeep').write_text('')
        (inbox / 'app.py').write_text('print("testing")')
        (inbox / 'copilot_agent/app.py').write_text('VALUE = 99')
        version = launcher.choose_source(live, choice='2')
        self.assertEqual((version / 'app.py').read_text(), 'print("testing")')
        self.assertEqual((version / 'copilot_agent/app.py').read_text(), 'VALUE = 99')
        self.assertEqual(launcher.choose_source(live, lambda _: '', choice='2'), version)
        self.assertFalse((version / '.gitkeep').exists())

    def test_next_drop_updates_latest_version_automatically(self):
        live, _ = self.fixture()
        inbox = launcher.prepare_drop_folder(live)
        (inbox / 'copilot_agent/first.py').write_text('VALUE = 50')
        first = launcher.choose_source(live, choice='2')
        (inbox / 'copilot_agent/second.py').write_text('VALUE = 60')
        second = launcher.choose_source(live, lambda _: '', choice='2')
        self.assertNotEqual(first, second)
        self.assertEqual((second / 'copilot_agent/first.py').read_text(), 'VALUE = 50')
        self.assertEqual((second / 'copilot_agent/second.py').read_text(), 'VALUE = 60')
        self.assertEqual((live / 'copilot_agent/first.py').read_text(), 'VALUE = 1')

    def test_copy_runs_imports_from_its_own_updated_modules(self):
        live, delivery = self.fixture()
        (live / 'app.py').write_text('from copilot_agent.first import VALUE\nprint(VALUE)')
        (delivery / 'first.py').write_text('VALUE = 77')
        version = launcher.create_version(live, delivery)
        result = subprocess.run([sys.executable, '-B', str(version / 'app.py')],
                                cwd=version, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '77')
