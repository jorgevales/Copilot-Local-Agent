"""Exercise the launcher's actual Python portability probe without private S:."""
import ast
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import shutil
import subprocess
import tempfile
import os
import sys


class SharedRuntimeProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (Path(__file__).resolve().parents[1] / 'Launcher.ps1').read_text(encoding='utf-8-sig')
        match = re.search(r"(?ms)^\s*\$pythonProbe = @'\r?\n(.*?)\r?\n'@",source)
        if match is None:
            raise AssertionError('Launcher Python runtime probe is absent')
        tree = ast.parse(match[1])
        definitions = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))
                       or (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'WINDOWS_SLASH'
                                                                 for target in node.targets))]
        namespace = {}
        exec(compile(ast.Module(body=definitions,type_ignores=[]),'Launcher.ps1 Python portability probe','exec'),namespace)
        cls.check = staticmethod(namespace['assert_shared_runtime'])
        cls.shared_path = staticmethod(namespace['is_shared_path'])
        cls.mapped_root = staticmethod(namespace['mapped_shared_root'])
        cls.valid_prefix = staticmethod(namespace['valid_environment_prefix'])
        cls.dependencies = staticmethod(namespace['assert_dependencies'])
        cls.locked_versions = staticmethod(namespace['locked_versions'])
        cls.source = source

    def test_mapped_s_unc_runtime_and_dependency_paths_accepted(self):
        def resolve(path, *, strict):
            self.assertTrue(strict)
            return '\\' * 2 + r'server\share' if path.casefold() == 's:' + chr(92) else path
        with patch('os.path.realpath', side_effect=resolve):
            self.mapped_root.cache_clear()
            self.check(r'S:\Env\Scripts\python.exe', r'S:\Python',
                       r'\\server\share\Python\python.exe', r'\\server\share\Python\Lib')
            self.check(r'\\server\share\Env\Scripts\python.exe', r'\\server\share\Python',
                       r'\\server\share\Python\python.exe', r'\\server\share\Python\Lib')
            self.dependencies({'playwright': {'version': '1.55.0',
                                              'location': r'\\server\share\Env\Lib\site-packages'}},
                              {'playwright': '1.55.0'}, True)
        self.mapped_root.cache_clear()

    def test_unrelated_unc_share_and_prefix_collision_rejected(self):
        def resolve(path, *, strict):
            self.assertTrue(strict)
            return '\\' * 2 + r'server\share' if path.casefold() == 's:' + chr(92) else path
        with patch('os.path.realpath', side_effect=resolve):
            self.mapped_root.cache_clear()
            for other in (r'\\other\share\Python\python.exe',
                          r'\\server\share2\Python\python.exe'):
                with self.subTest(path=other), self.assertRaisesRegex(RuntimeError, 'base executable'):
                    self.check(r'S:\Env\Scripts\python.exe', r'S:\Python', other, r'S:\Python\Lib')
                with self.subTest(dependency=other), self.assertRaisesRegex(RuntimeError, 'must be installed on S:'):
                    self.dependencies({'playwright': {'version': '1.55.0', 'location': other}},
                                      {'playwright': '1.55.0'}, True)
        self.mapped_root.cache_clear()

    def test_unc_rejected_when_s_mapping_cannot_be_verified(self):
        with patch('os.path.realpath', side_effect=OSError('unavailable')):
            self.mapped_root.cache_clear()
            with self.assertRaisesRegex(RuntimeError, 'base executable'):
                self.check(r'S:\Env\Scripts\python.exe', r'S:\Python',
                           r'\\server\share\Python\python.exe', r'S:\Python\Lib')
        self.mapped_root.cache_clear()

    def test_extended_unc_resolution_and_redirect_outside_share(self):
        def resolve(path, *, strict):
            self.assertTrue(strict)
            if path.casefold() == 's:' + chr(92):
                return r'\\?\UNC\server\share'
            if path == r'\\server\share\redirected\python.exe':
                return r'C:\outside\python.exe'
            return path
        with patch('os.path.realpath', side_effect=resolve):
            self.mapped_root.cache_clear()
            self.check(r'S:\Env\Scripts\python.exe', r'S:\Python',
                       r'\\?\UNC\server\share\Python\python.exe', r'S:\Python\Lib')
            with self.assertRaisesRegex(RuntimeError, 'base executable'):
                self.check(r'S:\Env\Scripts\python.exe', r'S:\Python',
                           r'\\server\share\redirected\python.exe', r'S:\Python\Lib')
        self.mapped_root.cache_clear()

    def test_environment_prefix_uses_directory_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'base'
            environment = Path(directory) / 'env'
            other = Path(directory) / 'other'
            for path in (base, environment, other):
                path.mkdir()
            self.assertTrue(self.valid_prefix(str(environment), str(base), str(environment)))
            self.assertFalse(self.valid_prefix(str(environment), str(base), str(other)))
            self.assertFalse(self.valid_prefix(str(base), str(base), str(base)))
            self.assertFalse(self.valid_prefix(str(environment), str(base), str(environment / 'missing')))

    def test_environment_prefix_accepts_unc_alias_when_file_ids_differ(self):
        aliases = {r'S:\Env': r'\\server\share\Env',
                   r'S:\Python': r'\\server\share\Python'}
        with patch('os.path.samefile', return_value=False), patch(
                'os.path.realpath', side_effect=lambda path, *, strict: aliases.get(path, path)):
            self.assertTrue(self.valid_prefix(r'S:\Env', r'S:\Python',
                                              r'\\server\share\Env'))
        with patch('os.path.samefile', side_effect=OSError('unavailable')), patch(
                'os.path.realpath', side_effect=OSError('unavailable')):
            self.assertFalse(self.valid_prefix(r'S:\Env', r'S:\Python',
                                               r'\\server\share\Env'))

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


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell'), 'Windows PowerShell required')
class PythonSetupChoiceTests(unittest.TestCase):
    def run_helpers(self, body):
        source = (Path(__file__).resolve().parents[1] / 'Launcher.ps1').read_text(encoding='utf-8-sig')
        helpers = source[source.index('function Add-PythonCandidate'):source.index('function Get-OneDriveRoots')]
        script = "$ErrorActionPreference='Stop'; $productionShare=$false; " + source[source.index('$candidates ='):source.index('function Add-PythonCandidate')] + helpers + body
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_pasted_quoted_executable_and_installation_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'python.exe').write_bytes(b'fixture')
            (root / 'Scripts').mkdir()
            (root / 'Scripts' / 'python.exe').write_bytes(b'fixture')
            quoted = str(root).replace("'", "''")
            output = self.run_helpers("Add-PythonCandidate "+chr(39)+chr(34)+quoted+"\\python.exe"+chr(34)+chr(39)+"; Add-PythonCandidate "+chr(39)+quoted+chr(39)+"; if ($candidates.Count -ne 2) { throw "+chr(39)+"Folder/executable detection failed"+chr(39)+" }; Write-Output "+chr(39)+"passed"+chr(39))
            self.assertIn('passed', output)

    def test_invalid_and_relative_paths_rejected(self):
        output = self.run_helpers("foreach ($value in @('python.exe','S:python.exe','\\python.exe','C:\\missing\\python.exe','C:\\Windows\\System32\\cmd.exe')) { Add-PythonCandidate $value }; if ($candidates.Count -ne 0) { throw 'Unsafe candidate accepted' }; Write-Output 'passed'")
        self.assertIn('passed', output)

    def test_shared_deployment_rejects_pasted_local_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'python.exe').write_bytes(b'fixture')
            path = str(Path(directory) / 'python.exe').replace("'", "''")
            output = self.run_helpers("$productionShare=$true; Add-PythonCandidate '" + path + "'; if ($candidates.Count -ne 0) { throw 'Local executable accepted on shared deployment' }; Write-Output 'passed'")
            self.assertIn('passed', output)

    def test_choice_and_path_retry_are_bounded_and_literal(self):
        output = self.run_helpers("function Read-Host { return 'invalid' }; try { Read-PythonMethod; throw 'Missing bound' } catch { if ($_.Exception.Message -notlike '*five attempts*') { throw } }; try { Read-PythonPath; throw 'Missing bound' } catch { if ($_.Exception.Message -notlike '*five attempts*') { throw } }; Write-Output 'passed'")
        self.assertIn('passed', output)

    def test_direct_paste_choice_does_not_need_detection(self):
        output = self.run_helpers("function Read-Host { return '2' }; if ((Read-PythonMethod) -ne '2') { throw 'Wrong choice' }; Write-Output 'passed'")
        self.assertIn('passed', output)

    def test_actual_development_flags_preserve_native_python_arguments(self):
        source = (Path(__file__).resolve().parents[1] / 'Launcher.ps1').read_text(encoding='utf-8-sig')
        assignment = re.search(r"(?m)^\s*\[string\[\]\]\$pythonArgs = if .*", source)
        self.assertIsNotNone(assignment)
        executable = sys.executable.replace("'", "''")
        script = "$productionShare=$false; " + assignment[0].strip() + "; & '" + executable + "' @pythonArgs -c 'import sys; print(sys.argv[1])' native-argument-preserved; exit $LASTEXITCODE"
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], input='', capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'native-argument-preserved')

    def test_python_setup_reports_complete_native_error(self):
        source = (Path(__file__).resolve().parents[1] / 'Launcher.ps1').read_text(encoding='utf-8-sig')
        helper = source[source.index('function Invoke-SetupPython('):source.index('function Get-PipConfiguration(')]
        executable = sys.executable.replace("'", "''")
        script = "$ErrorActionPreference='Stop'; " + helper + " try { Invoke-SetupPython '" + executable + "' @('-c','raise RuntimeError(12345)'); throw 'Failure was ignored' } catch { Write-Output ('CAUGHT: ' + $_.Exception.Message) }"
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RuntimeError: 12345', result.stderr)
        self.assertIn('Python setup command failed with exit code 1', result.stdout)


    def test_cloud_tags_only_allowed_for_local_development(self):
        output = self.run_helpers("foreach ($tag in @(2415919130,2415923226,2415980570)) { if (-not (Test-AllowedCloudTag $tag)) { throw 'Known CLOUD tag denied' } }; foreach ($tag in @(2684354572,2684354563,2415919131,2952790042)) { if (Test-AllowedCloudTag $tag) { throw 'Unknown or surrogate tag accepted' } }; $productionShare=$true; if (Test-AllowedCloudTag 2415919130) { throw 'Cloud allowed on S' }; Write-Output 'passed'")
        self.assertIn('passed', output)

    def environment_fixture(self, directory, body, fail=''):
        bootstrap = Path(directory) / 'bootstrap'
        bootstrap.mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'bootstrap' / 'virtualenv.pyz', bootstrap / 'virtualenv.pyz')
        path = str(directory).replace("'", "''")
        return self.run_helpers("$global:operations=[System.Collections.Generic.List[string]]::new(); function Get-PipConfiguration { return '' }; function Invoke-SetupPython($Executable,$Arguments) { $global:operations.Add(($Arguments -join '|')); " + fail + " if (($Arguments -join '|') -like '*virtualenv.pyz*') { $envPath=$Arguments[-1]; New-Item -ItemType Directory -Path (Join-Path $envPath 'Scripts') -Force | Out-Null; Set-Content -LiteralPath (Join-Path $envPath 'pyvenv.cfg') -Value 'fixture'; Set-Content -LiteralPath (Join-Path $envPath 'Scripts\\python.exe') -Value 'fixture' } }; " + body.replace('PROJECT', "'"+path+"'"))

    def test_setup_creates_environment_installs_pins_and_retains_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.environment_fixture(directory, "$result=Initialize-AgentEnvironment 'base' @('-B') 'probe' 'development' PROJECT; if ($operations.Count -ne 4 -or $operations[1] -notlike '*virtualenv.pyz|--no-download|--no-periodic-update*' -or $operations[3] -notlike '*pip|install|--requirement*--no-user|--prefix*') { throw 'Wrong setup sequence' }; if ($result -notlike '*Scripts\\python.exe') { throw 'Wrong interpreter' }; if (-not (Test-Path -LiteralPath (Join-Path PROJECT '.venv-setup.lock'))) { throw 'Lock not retained' }; Write-Output 'passed'")
            self.assertIn('passed', output)

    def test_environment_bootstrap_needs_neither_base_venv_nor_base_pip(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.environment_fixture(directory, "$result=Initialize-AgentEnvironment 'base' @('-B') 'probe' 'development' PROJECT; if (($operations -join '|') -like '*-m|venv*' -or ($operations -join '|') -like '*-m|pip|install|virtualenv*' -or $operations[1] -notlike '*virtualenv.pyz*') { throw 'Base Python module dependency found' }; Write-Output 'passed'")
            self.assertIn('passed', output)

    def test_modified_bootstrap_stops_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.environment_fixture(directory, "Set-Content -LiteralPath (Join-Path PROJECT 'bootstrap\\virtualenv.pyz') -Value 'modified'; try { Initialize-AgentEnvironment 'base' @('-B') 'probe' 'development' PROJECT; throw 'Tampered bootstrap ran' } catch { if ($_.Exception.Message -notlike '*SHA-256*') { throw } }; if ($operations.Count -ne 1 -or (Test-Path -LiteralPath (Join-Path PROJECT '.venv'))) { throw 'Tampered bootstrap changed environment' }; Write-Output 'passed'")
            self.assertIn('passed', output)

    def test_setup_reuses_existing_environment_and_propagates_install_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / '.venv'
            (env / 'Scripts').mkdir(parents=True)
            (env / 'Scripts' / 'python.exe').write_bytes(b'fixture')
            (env / 'pyvenv.cfg').write_text('fixture')
            output = self.environment_fixture(directory, "try { Initialize-AgentEnvironment 'base' @('-B') 'probe' 'development' PROJECT; throw 'Failure lost' } catch { if ($_.Exception.Message -ne 'install failed') { throw } }; if ($operations.Count -ne 3 -or ($operations -join '|') -like '*|venv|*') { throw 'Existing env recreated' }; $lock=[IO.File]::Open((Join-Path PROJECT '.venv-setup.lock'),'Open','ReadWrite','None'); $lock.Dispose(); Write-Output 'passed'", "if ($Arguments -contains 'install') { throw 'install failed' };")
            self.assertIn('passed', output)

    def test_setup_archives_and_repairs_incomplete_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / '.venv').mkdir()
            (Path(directory) / '.venv' / 'old-file.txt').write_text('keep me')
            output = self.environment_fixture(directory, "$result=Initialize-AgentEnvironment 'base' @('-B') 'probe' 'development' PROJECT; $archives=@(Get-ChildItem -LiteralPath PROJECT -Directory -Filter '.venv-incomplete-*'); if ($archives.Count -ne 1 -or -not (Test-Path -LiteralPath (Join-Path $archives[0].FullName 'old-file.txt')) -or $operations.Count -ne 4) { throw 'Incomplete environment not preserved and repaired' }; Write-Output 'passed'")
            self.assertIn('passed', output)

    def test_pip_target_configuration_stops_before_install(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.environment_fixture(directory, "function Get-PipConfiguration { return 'install.target=outside' }; try { Initialize-AgentEnvironment 'base' @('-B') 'probe' 'development' PROJECT; throw 'Redirect accepted' } catch { if ($_.Exception.Message -notlike '*redirects*') { throw } }; if (($operations -join '|') -like '*|install|*') { throw 'Install attempted' }; Write-Output 'passed'")
            self.assertIn('passed', output)


if __name__=='__main__':
    unittest.main()
