"""Exercise the launcher's actual Python portability probe without private S:."""
import ast
from pathlib import Path
import re
import unittest


class SharedRuntimeProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (Path(__file__).resolve().parents[1] / 'Launcher.ps1').read_text(encoding='utf-8-sig')
        match = re.search(r"(?ms)^\s*\$pythonProbe = @'\r?\n(.*?)\r?\n'@",source)
        if match is None:
            raise AssertionError('Launcher Python runtime probe is absent')
        tree = ast.parse(match[1])
        definitions = [node for node in tree.body if isinstance(node,(ast.Import,ast.FunctionDef)) and
                       (isinstance(node,ast.FunctionDef) or any(alias.name=='ntpath' for alias in node.names))]
        namespace = {}
        exec(compile(ast.Module(body=definitions,type_ignores=[]),'Launcher.ps1 Python portability probe','exec'),namespace)
        cls.check = staticmethod(namespace['assert_shared_runtime'])
        cls.dependencies = staticmethod(namespace['assert_dependencies'])
        cls.locked_versions = staticmethod(namespace['locked_versions'])
        cls.source = source

    def test_complete_shared_installation_and_shared_venv_accepted(self):
        self.check(r'S:\Python\python.exe',r'S:\Python',r'S:\Python\python.exe',r'S:\Python\Lib')
        self.check(r'S:\Env\Scripts\python.exe',r'S:\Python',r'S:\Python\python.exe',r'S:\Python\Lib')
        self.check(r's:\Python\python.exe',r's:\Python',None,r's:\Python\Lib')

    def test_shared_venv_dependent_on_local_base_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'base Python prefix.*on S:'):
            self.check(r'S:\Env\Scripts\python.exe',r'C:\Python',r'C:\Python\python.exe',r'C:\Python\Lib')

    def test_each_actual_runtime_component_must_be_shared(self):
        valid = [r'S:\Python\python.exe',r'S:\Python',r'S:\Python\python.exe',r'S:\Python\Lib']
        for index in range(4):
            with self.subTest(component=index):
                values = valid.copy()
                values[index] = values[index].replace('S:', 'C:')
                with self.assertRaisesRegex(RuntimeError,'complete shared installation'):
                    self.check(*values)

    def test_drive_relative_unc_and_missing_stdlib_rejected(self):
        valid = [r'S:\Python\python.exe',r'S:\Python',r'S:\Python\python.exe',r'S:\Python\Lib']
        for value in ('S:Python\\Lib',r'\\server\Python\Lib',None,''):
            with self.subTest(stdlib=value):
                with self.assertRaises(RuntimeError):
                    self.check(*valid[:3],value)

    def test_shared_dependencies_require_lock_versions_and_s_drive(self):
        lock = (Path(__file__).resolve().parents[1] / 'requirements.lock.txt').read_text(encoding='utf-8-sig')
        expected = self.locked_versions(lock)
        installed = {name:{'version':version,'location':r'S:\Python\Lib\site-packages'}
                     for name,version in expected.items()}
        self.dependencies(installed,expected,True)
        for name in expected:
            with self.subTest(local_package=name):
                local = {package:dict(record) for package,record in installed.items()}
                local[name]['location'] = r'C:\Users\Example\AppData\Roaming\Python\site-packages'
                with self.assertRaisesRegex(RuntimeError,'must be installed on S:'):
                    self.dependencies(local,expected,True)
            with self.subTest(wrong_version=name):
                wrong = {package:dict(record) for package,record in installed.items()}
                wrong[name]['version'] = '0.0.0'
                with self.assertRaisesRegex(RuntimeError,'requirements.lock.txt'):
                    self.dependencies(wrong,expected,True)

    def test_development_keeps_local_playwright_dependency_allowed(self):
        installed = {'playwright':{'version':'1.55.0','location':r'C:\Local\site-packages'}}
        self.dependencies(installed,{'playwright':'1.55.0'},False)
        with self.assertRaises(RuntimeError):
            self.dependencies(installed,{'playwright':'1.55.0'},True)

    def test_dependency_lock_rejects_missing_duplicate_and_unpinned_packages(self):
        for lock in ('playwright==1.55.0','playwright>=1.55.0',
                     'playwright==1.55.0\nplaywright==1.55.0'):
            with self.subTest(lock=lock),self.assertRaises(RuntimeError):
                self.locked_versions(lock)

    def test_all_python_entrypoints_use_shared_environment_isolation_flags(self):
        branch = re.search(r"\$pythonArgs = if \(\$productionShare\) \{ @\((.*?)\) \} else \{ @\((.*?)\) \}",self.source)
        self.assertIsNotNone(branch)
        shared = ast.literal_eval('('+branch[1]+',)')
        development = ast.literal_eval('('+branch[2]+',)')
        self.assertEqual(shared,('-B','-E','-s'))
        self.assertEqual(development,('-B',))
        calls = re.findall(r'(?m)^\s*& \$python\s+([^\r\n]+)',self.source)
        self.assertEqual(len(calls),5)  # Probe, setup, start, tests-setup and tests.
        self.assertTrue(all(call.startswith('@pythonArgs ') for call in calls))


if __name__=='__main__':
    unittest.main()
