"""Installer path/reuse regressions; simulated VDI error, actual offline pip proof."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
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

    def test_missing_environment_folder_is_created_without_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            chosen=Path(root)/'chosen folder'
            installed={}
            def probe(path):
                if path!=chosen:
                    raise FileNotFoundError('No usable folder')
                self.helper.probe(path)
            def runner(args, env):
                if 'install' in args:
                    installed.update(jsonschema='4.26.0',lxml='6.1.3')
                    self.assertEqual(str(chosen),env['TEMP'])
                return SimpleNamespace(returncode=0,output='')
            self.helper.install(self.fixture(root),Path(root),versions=lambda:dict(installed),
                run=runner,health=lambda:None,probe_folder=probe,
                ask=lambda _:self.fail('Automatic setup must never ask for a folder'),
                environ={'TEMP':str(chosen)})
            self.assertTrue(chosen.is_dir())

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

    def test_all_folder_failures_report_categories_and_paths_without_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            def denied(path): raise PermissionError('secret raw OS text https://name:password@example.test/?token=secret')
            with self.assertRaisesRegex(RuntimeError,'automatic unpacking folders') as raised:
                self.helper.install(self.fixture(root),Path(root),versions=lambda:{},
                    run=lambda args,env:SimpleNamespace(returncode=0,output='') if 'install' not in args else self.fail('Unverified folder used'),health=lambda:None,
                    probe_folder=denied,ask=lambda _:self.fail('Must not ask for a folder'),environ={})
            message=str(raised.exception)
            self.assertIn('<PROJECT>',message)
            self.assertIn('write/read probe: access denied',message)
            self.assertIn('COPILOT_SETUP_TEMP',message)
            self.assertNotIn('password',message)
            self.assertNotIn('token',message)
            self.assertNotIn('secret raw',message)

    def test_misleading_space_error_tries_next_folder_and_keeps_partial_install(self):
        with tempfile.TemporaryDirectory() as root:
            installed,calls={},[]
            def runner(args,env):
                if 'install' in args:
                    calls.append((args,env['TEMP']))
                    if len(calls)==1:
                        installed['lxml']='6.1.3'
                        return SimpleNamespace(returncode=1,output='ERROR: [WinError 112] There is not enough space on the disk')
                    installed['jsonschema']='4.26.0'
                return SimpleNamespace(returncode=0,output='')
            self.helper.install(self.fixture(root),Path(root),versions=lambda:dict(installed),
                run=runner,health=lambda:None,environ={},ask=lambda _:self.fail('Wrong prompt'))
            self.assertEqual(2,len(calls))
            self.assertNotEqual(calls[0][1],calls[1][1])
            self.assertNotIn('lxml==6.1.3',calls[1][0])

    def test_invalid_cached_wheel_retries_uncached_in_another_folder(self):
        with tempfile.TemporaryDirectory() as root:
            installed,calls={},[]
            def runner(args,env):
                if 'install' in args:
                    calls.append(args)
                    if len(calls)==1:
                        return SimpleNamespace(returncode=1,output='ERROR: invalid wheel in cache')
                    installed.update(jsonschema='4.26.0',lxml='6.1.3')
                return SimpleNamespace(returncode=0,output='')
            self.helper.install(self.fixture(root),Path(root),versions=lambda:dict(installed),
                run=runner,health=lambda:None,environ={},ask=lambda _:self.fail('Wrong prompt'))
            self.assertIn('--cache-dir',calls[0])
            self.assertIn('--no-cache-dir',calls[1])

    def test_cache_location_failure_does_not_prevent_install(self):
        with tempfile.TemporaryDirectory() as root:
            installed={}
            def runner(args,env):
                if args==['-m','pip','cache','dir']:
                    raise FileNotFoundError('redirected cache unavailable')
                if 'install' in args:
                    installed.update(jsonschema='4.26.0',lxml='6.1.3')
                return SimpleNamespace(returncode=0,output='')
            self.helper.install(self.fixture(root),Path(root),versions=lambda:dict(installed),
                run=runner,health=lambda:None,environ={},ask=lambda _:self.fail('Wrong prompt'))

    def test_provider_discovery_is_deferred_until_established_candidates_are_used(self):
        with tempfile.TemporaryDirectory() as root, patch.object(self.helper,'shared_root') as lookup:
            locations=iter(self.helper.candidates(Path(root),{'TEMP':str(Path(root)/'new temp')}))
            self.assertEqual(Path(root)/'new temp',next(locations))
            self.assertEqual(Path(root)/'.setup-cache'/'temp',next(locations))
            lookup.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows mapping-provider fallbacks')
    def test_live_mapping_provider_output_adds_unc_alias_and_short_scratch(self):
        share=Path(r'\\server\proven-share')
        with patch.object(self.helper.os.path,'realpath',side_effect=OSError('mapping API unavailable')), \
             patch.object(self.helper.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(str(share)))) as provider:
            locations=list(self.helper.candidates(Path('S:/workspace/agent'),{}))
        self.assertIn(share/'workspace'/'agent'/'.setup-cache'/'temp',locations)
        self.assertTrue(any(str(path).startswith('S:\\.copilot-setup\\') for path in locations))
        self.assertTrue(any(str(path).startswith(str(share/'.copilot-setup')) for path in locations))
        command=provider.call_args.args[0]
        self.assertIn('-NonInteractive',command)
        self.assertIn('Get-PSDrive',command[-1])
        self.assertIn('Get-CimInstance',command[-1])
        self.assertIn('Get-SmbMapping',command[-1])
        self.assertEqual(5,provider.call_args.kwargs['timeout'])
        self.assertNotIn('shell',provider.call_args.kwargs)

    @unittest.skipUnless(os.name=='nt','Windows mapping-provider fallbacks')
    def test_each_mapping_provider_fallback_executes_when_prior_providers_fail(self):
        # Run the exact provider script with offline PowerShell fixture functions.
        # No actual share, CIM service or SMB mapping is contacted.
        with patch.object(self.helper.os.path,'realpath',side_effect=OSError('unavailable')), \
             patch.object(self.helper.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='')) as capture:
            self.helper.shared_root(dict(os.environ))
        command=capture.call_args.args[0]
        providers=('Get-PSDrive','Get-CimInstance','Get-SmbMapping')
        fields=('DisplayRoot','ProviderName','RemotePath')
        for chosen,field in zip(providers,fields):
            functions=[]
            for name in providers:
                body="[pscustomobject]@{"+field+"='\\\\server\\fixture-share'}" if name==chosen else "throw 'fixture unavailable'"
                functions.append('function '+name+' { '+body+' }')
            with self.subTest(provider=chosen):
                result=subprocess.run(command[:-1]+['\n'.join(functions)+'\n'+command[-1]],
                                      capture_output=True,text=True,timeout=10)
                self.assertEqual(0,result.returncode,result.stderr)
                self.assertEqual(r'\\server\fixture-share',json.loads(result.stdout))

    @unittest.skipUnless(os.name=='nt','Windows mapping-provider fallbacks')
    def test_unrelated_unc_project_is_never_aliased_to_s(self):
        with patch.object(self.helper,'shared_root',return_value=Path(r'\\server\proven-share')):
            locations=list(self.helper.candidates(Path(r'\\server\proven-share-other\agent'),{}))
        self.assertNotIn(Path('S:/agent/.setup-cache/temp'),locations)

    @unittest.skipUnless(os.name=='nt','Windows mapping-provider fallbacks')
    def test_mapping_timeout_and_invalid_provider_output_keep_local_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            for result in (subprocess.TimeoutExpired('powershell',5),
                           SimpleNamespace(returncode=0,stdout=json.dumps('S:')),
                           SimpleNamespace(returncode=0,stdout='invalid json')):
                with self.subTest(result=result), \
                     patch.object(self.helper.os.path,'realpath',side_effect=OSError('unavailable')), \
                     patch.object(self.helper.subprocess,'run',**({'side_effect':result} if isinstance(result,Exception) else {'return_value':result})):
                    locations=list(self.helper.candidates(Path(root),{'LOCALAPPDATA':root}))
                self.assertTrue(any(path.parent==Path(root)/'Temp'/'CopilotLocalAgent' for path in locations))

    def test_exhausted_installer_space_errors_are_reported_without_guessing_capacity(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError,'space/quota reported') as raised:
                self.helper.install(self.fixture(root),Path(root),versions=lambda:{},
                    run=lambda args,env:SimpleNamespace(returncode=1,output='[WinError 112] not enough space') if 'install' in args else SimpleNamespace(returncode=0,output=''),
                    probe_folder=lambda path:None,health=lambda:None,environ={},
                    ask=lambda _:self.fail('Wrong prompt'))
            self.assertIn('not a free-space verdict',str(raised.exception))

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
