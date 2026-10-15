"""Public ToolRegistry execution of the no-Node REA backend."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

from jsonschema import Draft202012Validator

from copilot_agent.policy import PathPolicy
from copilot_agent.tools import ToolRegistry
from tests.test_rea_python_artifacts import managed_fixture


class PythonREARegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rea_python_registry_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = {'root': str(Path(__file__).resolve().parents[1]),
                       'allowed_roots':[str(self.root)], 'allowed_domains':['example.invalid'],
                       'rea_backend':'python_native', 'rea_max_parallel':1,
                       'rea_timeout_seconds':20}
        self.context = {'config':self.config,'session_dir':str(self.root/'session'),
                        'path_policy':PathPolicy([self.root]), '_rea_runtime':{}}
        self.registry = ToolRegistry(self.config)

    async def execute(self, tool, args):
        # A no-Node session must not even discover a Node installation. Worker
        # creation uses the already running project Python, never the target.
        with patch('copilot_agent.rea._node_health',side_effect=AssertionError('No Node probe allowed')):
            output = await self.registry.execute(tool,args,self.context)
            definition = self.registry.definition(tool)
        Draft202012Validator.check_schema(definition['output_schema'])
        Draft202012Validator(definition['output_schema']).validate(output)
        result = output.get('result',{})
        self.assertEqual('python_native',result.get('backend'),output)
        return output, result

    def evidence(self,result):
        evidence = Path(result['evidence_path'])
        if not evidence.is_absolute():
            evidence = Path(self.context['session_dir'])/evidence
        self.assertTrue(evidence.is_file(),result)
        data = evidence.read_bytes()
        self.assertEqual(result['evidence_sha256'],hashlib.sha256(data).hexdigest())
        return data

    def assert_sanitized(self,result,secrets=()):
        output=json.dumps(result)
        retained=self.evidence(result).decode('utf-8')
        for secret in tuple(secrets)+(str(self.root),self.root.as_posix()):
            self.assertNotIn(secret,output)
            self.assertNotIn(secret,retained)
        self.assertEqual('<approved-input>',result['target'])
        self.assertFalse(result['side_effects_uncertain'])

    async def test_all_static_kinds_execute_real_python_worker_with_useful_evidence(self):
        fixtures=[('javascript','app.js',b'import React from "react"; export function load(){return fetch("/api/users/934?token=fixture-secret");}'),
                  ('managed','assembly.bin',managed_fixture()),
                  ('go','go.bin',b'\x7fELF\x02\0go1.24.2\0net/http.Client\0runtime.main\0'),
                  ('rust','rust.bin',b'\x7fELF\x02\0std::panic::run\0panicked at fixture-secret\0tokio-abcdef1234\0')]
        for kind,name,data in fixtures:
            with self.subTest(kind=kind):
                path=self.root/name
                path.write_bytes(data)
                output,result=await self.execute('rea.analyze_artifact',{'path':str(path),'kind':kind})
                self.assertIn(result['status'],('completed','partial'),output)
                self.assertTrue(result['findings'],output)
                self.assertIn(result['confidence'],('observed','derived'))
                self.assertTrue(result['limitations'])
                self.assert_sanitized(result,('fixture-secret',))
                if kind=='javascript': self.assertTrue(result['findings']['imports'])
                if kind=='managed': self.assertTrue(result['findings']['types'])
                if kind=='go': self.assertIn('net/http',result['findings']['packages'])
                if kind=='rust': self.assertIn('tokio',result['findings']['packages'])

    async def test_invalid_pe_is_honest_partial_not_target_execution(self):
        path=self.root/'untrusted.exe'
        path.write_bytes(b'MZ'+b'\0'*100+b'fixture-secret')
        output,result=await self.execute('rea.analyze_artifact',{'path':str(path),'kind':'managed'})
        self.assertEqual('partial',result['status'],output)
        self.assertTrue(result['unknowns'])
        self.assertEqual('pe',result['findings']['file']['format'])
        self.assert_sanitized(result,('fixture-secret',))

    async def test_har_retains_only_safe_structural_evidence(self):
        path=self.root/'fixture.har'
        path.write_text(json.dumps({'log':{'version':'1.2','entries':[
            {'time':12,'timings':{'send':1,'wait':10,'receive':1},
             'request':{'method':'POST','url':'https://example.invalid/api/users/934?token=fixture-secret#private-fragment',
                        'headers':[{'name':'Authorization','value':'Bearer fixture-secret'}],
                        'cookies':[{'name':'sid','value':'cookie-secret'}],
                        'queryString':[{'name':'token','value':'fixture-secret'}],
                        'postData':{'text':'{"customer":"fixture-personal-record"}'}},
             'response':{'status':200,'headers':[{'name':'Set-Cookie','value':'cookie-secret'}],
                         'content':{'mimeType':'application/json','text':'fixture-response-payload'}}}]}}),encoding='utf-8')
        output,result=await self.execute('rea.analyze_capture',{'path':str(path),'format':'har'})
        self.assertIn(result['status'],('completed','partial'),output)
        self.assertTrue(result['findings'])
        self.assert_sanitized(result,('fixture-secret','cookie-secret','fixture-personal-record','fixture-response-payload','private-fragment','/934'))

    async def test_saz_uses_bounded_offline_reader_and_sanitizes_values(self):
        path=self.root/'fixture.saz'
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('raw/1_c.txt','GET https://example.invalid/api/users/934?token=fixture-secret HTTP/1.1\r\nHost: example.invalid\r\nAuthorization: Bearer fixture-secret\r\nCookie: sid=cookie-secret\r\n\r\nfixture-request-payload')
            archive.writestr('raw/1_s.txt','HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: sid=cookie-secret\r\n\r\n{"customer":"fixture-personal-record"}')
        output,result=await self.execute('rea.analyze_capture',{'path':str(path),'format':'saz'})
        self.assertIn(result['status'],('completed','partial'),output)
        self.assertTrue(result['findings'])
        self.assert_sanitized(result,('fixture-secret','cookie-secret','fixture-request-payload','fixture-personal-record','/934'))

    async def test_worker_timeout_output_limit_and_cancelled_statuses_stay_distinct(self):
        path=self.root/'app.js'
        path.write_text('export const answer = 42;',encoding='utf-8')
        for status in ('timeout','output_limit','cancelled'):
            with self.subTest(status=status):
                async def stopped(*args,**kwargs):
                    context=kwargs['context']
                    context['rea_execution_started']=True
                    context['rea_cleanup_confirmed']=True
                    return {'status':status,'side_effects_uncertain':False,'stdout':b'','stderr':b'', 'returncode':-1}
                with patch('copilot_agent.rea._run',side_effect=stopped):
                    output,result=await self.execute('rea.analyze_artifact',{'path':str(path),'kind':'javascript'})
                self.assertEqual(status,result['status'],output)
                self.assertFalse(result['side_effects_uncertain'])
                self.assertFalse(output['ok'])
                self.evidence(result)

    async def test_uncertain_worker_cleanup_is_not_a_clean_timeout(self):
        path=self.root/'app.js'
        path.write_text('export const answer = 42;',encoding='utf-8')
        async def uncertain(*args,**kwargs):
            kwargs['context']['rea_execution_started']=True
            kwargs['context']['rea_cleanup_confirmed']=False
            return {'status':'uncertain','side_effects_uncertain':True,'stdout':b'','stderr':b'','returncode':-1}
        with patch('copilot_agent.rea._run',side_effect=uncertain):
            output,result=await self.execute('rea.analyze_artifact',{'path':str(path),'kind':'javascript'})
        self.assertEqual('uncertain',result['status'],output)
        self.assertTrue(result['side_effects_uncertain'])
        self.assertFalse(output['ok'])


if __name__=='__main__': unittest.main()
