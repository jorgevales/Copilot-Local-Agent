"""Synthetic local tests only; no real agent, browser automation or model call."""
import importlib.util
import json
import secrets
import sys
import threading
import time
import unittest
from pathlib import Path
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

spec=importlib.util.spec_from_file_location('workspace',Path(__file__).resolve().parents[1]/'workspace.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class WorkspaceTests(unittest.TestCase):
    def test_no_runtime_never_sends(self):
        ws=module.Workspace()
        with self.assertRaises(ValueError): ws.submit('Synthetic request')
        self.assertEqual([],ws.events)
        self.assertFalse(ws.busy)

    def test_events_are_snapshots(self):
        ws=module.Workspace();payload={'summary':'Synthetic event','details':{'count':1}}
        ws.emit('system',payload);payload['details']['count']=2
        self.assertEqual(1,ws.snapshot()['events'][0]['payload']['details']['count'])
        self.assertEqual([],ws.snapshot(after=1)['events'])

    def test_action_status_tracks_busy_state(self):
        ws=module.Workspace()
        ws.emit('status',{'state':'action_active','summary':'Working'})
        self.assertTrue(ws.snapshot()['busy'])
        ws.emit('status',{'state':'awaiting_input','summary':'Ready'})
        self.assertFalse(ws.snapshot()['busy'])

    def test_unsupported_events_rejected(self):
        with self.assertRaises(ValueError): module.Workspace().emit('private_reasoning',{})

    def test_approval_hashes_and_single_use(self):
        ws=module.Workspace();result=[]
        thread=threading.Thread(target=lambda:result.append(ws.request_approval({'plan_hash':'plan-a','call_hash':'call-a','complete_pending_plan':{'tool_requests':[]}})))
        thread.start()
        deadline=time.monotonic()+2
        while not ws.snapshot()['approvals'] and time.monotonic()<deadline: time.sleep(.01)
        ticket=ws.snapshot()['approvals'][0]['ticket']
        with self.assertRaises(ValueError): ws.decide(ticket,'plan','changed','call-a')
        ws.decide(ticket,'once','plan-a','call-a');thread.join(2)
        self.assertEqual(['once'],result)
        with self.assertRaises(ValueError): ws.decide(ticket,'plan','plan-a','call-a')

    def test_close_denies_pending(self):
        ws=module.Workspace();result=[]
        thread=threading.Thread(target=lambda:result.append(ws.request_approval({'plan_hash':'p','call_hash':'c'})))
        thread.start();deadline=time.monotonic()+2
        while not ws.snapshot()['approvals'] and time.monotonic()<deadline: time.sleep(.01)
        ws.close();thread.join(2);self.assertEqual(['deny'],result)

    def test_busy_blocks_duplicate_turn(self):
        ws=module.Workspace();gate=threading.Event();calls=[]
        class Runtime:
            def submit(self,text): calls.append(text);gate.wait(2)
        ws.runtime=Runtime();ws.submit('Synthetic first')
        with self.assertRaises(ValueError): ws.submit('Synthetic duplicate')
        gate.set();deadline=time.monotonic()+2
        while ws.busy and time.monotonic()<deadline: time.sleep(.01)
        self.assertEqual(['Synthetic first'],calls)

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),module.Handler)
        self.server.token=secrets.token_urlsafe(32);self.server.workspace=module.Workspace()
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.workspace.close();self.server.shutdown();self.server.server_close();self.thread.join(2)
    def request(self,path,method='GET',body=None,auth=True,origin=True,host=None):
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=2)
        headers={}
        if auth: headers['Authorization']='Bearer '+self.server.token
        if origin: headers['Origin']=f'http://127.0.0.1:{self.server.server_port}'
        if host: headers['Host']=host
        if body is not None: headers['Content-Type']='application/json';body=json.dumps(body)
        connection.request(method,path,body=body,headers=headers)
        response=connection.getresponse();data=response.read();status=response.status;headers=dict(response.getheaders());connection.close()
        return status,data,headers
    def test_static_and_csp(self):
        status,data,headers=self.request('/')
        self.assertEqual(200,status);self.assertIn(b'Copilot Agent Workspace',data)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
    def test_state_requires_token(self):
        self.assertEqual(401,self.request('/api/state',auth=False)[0])
        self.assertEqual(200,self.request('/api/state')[0])
    def test_host_rejected(self):
        self.assertEqual(403,self.request('/api/state',host='attacker.invalid')[0])
    def test_origin_rejected(self):
        self.assertEqual(403,self.request('/api/submit','POST',{'text':'Synthetic'},origin=False)[0])
    def test_live_submit_disabled(self):
        status,data,_=self.request('/api/submit','POST',{'text':'Synthetic'})
        self.assertEqual(400,status);self.assertIn(b'No prompt was sent',data)
    def test_unsupported_action_disabled(self):
        self.assertEqual(400,self.request('/api/action','POST',{'action':'stop'})[0])
    def test_no_path_traversal(self):
        self.assertEqual(404,self.request('/../workspace.py')[0])

if __name__=='__main__': unittest.main()
