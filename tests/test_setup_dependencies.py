"""Installer path/reuse regressions; simulated VDI error, actual offline pip proof."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile


class DependencySetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1]/'bootstrap'/'setup_dependencies.py'
        spec = importlib.util.spec_from_file_location('setup_dependencies', path)
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)

    def fixture(self, root):
        pins = Path(root)/'requirements.lock.txt'
        pins.write_text('jsonschema==4.26.0\nlxml==6.1.3\n', encoding='utf-8')
        return pins

    def test_ready_environment_skips_install_cache_and_folder_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            calls=[]
            def runner(args, env):
                calls.append(args)
                return SimpleNamespace(returncode=0, output='')
            self.helper.install(self.fixture(root), Path(root),
                versions=lambda:{'jsonschema':'4.26.0','lxml':'6.1.3'}, run=runner,
                health=lambda:None, ask=lambda _:self.fail('Unnecessary prompt'))
            self.assertEqual(1,len(calls))
            self.assertEqual(['-m','pip','check'], calls[0])

    def test_missing_unpack_file_retries_with_new_folder_and_reuses_partial_install(self):
        with tempfile.TemporaryDirectory() as root:
            calls, installed = [], {}
            def runner(args, env):
                if 'install' not in args:
                    return SimpleNamespace(returncode=0, output='')
                self.assertNotEqual('C:', env['TEMP'])
                self.assertTrue(Path(env['TEMP']).is_dir())
                self.assertEqual(env['TEMP'], env['TMP'])
                self.assertEqual(env['TEMP'], env['TMPDIR'])
                calls.append((args,env['TEMP']))
                if len(calls)==1:
                    installed['lxml']='6.1.3'
                    return SimpleNamespace(returncode=1, output="ERROR: [Error 2] No such file or directory: C:\\Users\\fixture\\pip-unpack-2b5gqeh0\\jsonschema.whl")
                installed['jsonschema']='4.26.0'
                return SimpleNamespace(returncode=0, output='')
            self.helper.install(self.fixture(root), Path(root), versions=lambda:dict(installed),
                run=runner, health=lambda:None, environ={'TEMP':'C:', 'TMP':str(Path(root)/'other')},
                ask=lambda _:self.fail('Automatic fallbacks should work'))
            self.assertEqual(2,len(calls))
            self.assertNotEqual(calls[0][1],calls[1][1])
            self.assertIn('lxml==6.1.3',calls[0][0])
            self.assertNotIn('lxml==6.1.3',calls[1][0])
            self.assertIn('--no-deps',calls[1][0])
            self.assertIn('--no-compile',calls[1][0])

    def test_final_fallback_question_is_plain_and_successful(self):
        with tempfile.TemporaryDirectory() as root:
            chosen=Path(root)/'chosen folder'
            questions,installed=[],{}
            def probe(path):
                if path!=chosen:
                    raise FileNotFoundError('No usable folder')
                self.helper.probe(path)
            def runner(args, env):
                if 'install' in args:
                    installed.update(jsonschema='4.26.0',lxml='6.1.3')
                    self.assertEqual(str(chosen),env['TEMP'])
                return SimpleNamespace(returncode=0,output='')
            def ask(question):
                questions.append(question)
                return '"'+str(chosen)+'"'
            self.helper.install(self.fixture(root),Path(root),versions=lambda:dict(installed),
                run=runner,health=lambda:None,probe_folder=probe,ask=ask,environ={})
            self.assertEqual(1,len(questions))
            self.assertIn('folder where you can save files',questions[0])

    def test_mirror_failure_does_not_reinstall_in_every_folder(self):
        with tempfile.TemporaryDirectory() as root:
            calls=[]
            def runner(args, env):
                if 'install' in args:
                    calls.append(args)
                    return SimpleNamespace(returncode=1,output='ERROR: No matching distribution found')
                return SimpleNamespace(returncode=0,output='')
            with self.assertRaisesRegex(RuntimeError,'package source'):
                self.helper.install(self.fixture(root),Path(root),versions=lambda:{},run=runner,
                    health=lambda:None,ask=lambda _:self.fail('Wrong folder prompt'),environ={})
            self.assertEqual(1,len(calls))

    def test_no_root_or_relative_path_accepted_as_fallback(self):
        for value in ('C:', 'relative', str(Path.cwd().anchor)):
            with self.assertRaises(ValueError):
                self.helper.folder(value)

    def test_all_folder_failures_offer_final_choice_before_stopping(self):
        with tempfile.TemporaryDirectory() as root:
            questions=[]
            def denied(path): raise PermissionError('denied')
            def ask(q): questions.append(q); return ''
            with self.assertRaisesRegex(RuntimeError,'folder'):
                self.helper.install(self.fixture(root),Path(root),versions=lambda:{},
                    run=lambda args,env:SimpleNamespace(returncode=0,output='') if 'install' not in args else self.fail('Unverified folder used'),health=lambda:None,
                    probe_folder=denied,ask=ask,environ={})
            self.assertEqual(1,len(questions))

    def test_actual_pip_install_offline_with_broken_temp_spaces_and_repeat(self):
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'shared folder with spaces'
            wheels=root/'wheels'
            wheels.mkdir(parents=True)
            package='setup_fixture-1.0.0.dist-info/'
            with zipfile.ZipFile(wheels/'setup_fixture-1.0.0-py3-none-any.whl','w') as archive:
                archive.writestr('setup_fixture/__init__.py','value = 123\n')
                archive.writestr(package+'METADATA','Metadata-Version: 2.1\nName: setup-fixture\nVersion: 1.0.0\n')
                archive.writestr(package+'WHEEL','Wheel-Version: 1.0\nGenerator: regression-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
                archive.writestr(package+'RECORD','setup_fixture/__init__.py,,\n'+package+'METADATA,,\n'+package+'WHEEL,,\n'+package+'RECORD,,\n')
            prefix=root/'.venv'
            seeded=subprocess.run([sys.executable,str(repo/'bootstrap'/'virtualenv.pyz'),
                '--no-download','--no-periodic-update','--seeder','pip','--app-data',str(root/'seed-cache'),str(prefix)],
                capture_output=True,text=True,timeout=60)
            self.assertEqual(0,seeded.returncode,seeded.stdout+seeded.stderr)
            executable=prefix/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            requirements=root/'requirements.lock.txt'
            requirements.write_text('setup-fixture==1.0.0\n',encoding='utf-8')
            env=dict(os.environ,TEMP='C:',TMP='C:',TMPDIR='C:',PIP_NO_INDEX='1',
                PIP_FIND_LINKS=wheels.resolve().as_uri(),PIP_CONFIG_FILE=os.devnull)
            env.pop('PIP_TARGET',None)
            command=[str(executable),'-I',str(repo/'bootstrap'/'setup_dependencies.py'),
                     'install',str(requirements),str(prefix)]
            for expected in ('setting up 1 missing','already installed'):
                result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=30,input='')
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                self.assertIn(expected,result.stdout)
            checked=subprocess.run([str(executable),'-I','-c','import setup_fixture; assert setup_fixture.value == 123'],capture_output=True,text=True,timeout=10)
            self.assertEqual(0,checked.returncode,checked.stdout+checked.stderr)


if __name__=='__main__':
    unittest.main()
